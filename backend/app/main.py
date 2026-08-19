import logging
import hashlib
import json
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.agents import router as agents_router
from app.api.executions import router as executions_router
from app.api.knowledge_sources import router as knowledge_sources_router
from app.api.mcp_servers import router as mcp_servers_router
from app.api.memory import router as memory_router
from app.api.model_registrations import router as model_registrations_router
from app.api.multi_agent import router as multi_agent_router
from app.api.orchestration import router as orchestration_router
from app.api.publications import management_router as publications_router, public_router, versioned_public_router
from app.api.production import router as production_router
from app.api.runtimes import router as runtimes_router
from app.api.capabilities import router as capabilities_router
from app.api.console import router as console_router
from app.api.database_connections import router as database_connections_router
from app.api.schema_versions import router as schema_versions_router
from app.api.skills import router as skills_router
from app.config import get_settings
from app.db.session import SessionFactory, engine
from app.db.models import RuntimeFeatureProfile
from sqlalchemy import select
from app.memory import get_memory_store
from app.knowledge import KnowledgeServiceClient
from app.task_queue import get_task_queue
from app.storage import get_artifact_storage
from app.message_bus import get_agent_message_bus
from app.model_secrets import ModelSecretCipher
from app.repositories import model_registrations as model_repository
from app.repositories import runtimes as runtime_repository
from app.runtime import RuntimeAdapterError, get_runtime_adapter
from app.database_connections import ensure_postgres_builtins

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with SessionFactory() as session:
        await session.execute(text("SELECT 1"))
        await _register_legacy_model(session)
        await ensure_postgres_builtins(session)
        if settings.runtime_auto_register:
            await _register_builtin_runtimes(session)
    memory_store = get_memory_store()
    await memory_store.ping()
    task_queue = get_task_queue()
    await task_queue.ping()
    message_bus = get_agent_message_bus()
    await message_bus.ping()
    artifact_storage = get_artifact_storage()
    await artifact_storage.ping()
    await KnowledgeServiceClient().health()
    logger.info("control plane started", extra={"environment": settings.app_env})
    try:
        yield
    finally:
        await memory_store.close()
        await task_queue.close()
        await message_bus.close()
        await engine.dispose()


async def _register_builtin_runtimes(session) -> None:
    specifications = [
        (
            "Hermes Runtime",
            "hermes",
            settings.hermes_runtime_version,
            settings.hermes_endpoint,
            {"health_path": "/health"},
        ),
        (
            "Pi Runtime",
            "pi",
            settings.pi_runtime_version,
            settings.pi_runtime_endpoint,
            {"health_path": "/health"},
        ),
    ]
    if settings.deepseek_runtime_endpoint:
        specifications.append(
            (
                "DeepSeek Coding Runtime",
                "deepseek",
                settings.deepseek_runtime_version,
                settings.deepseek_runtime_endpoint,
                {
                    "health_path": "/health",
                    "workspace_type": "repository",
                    "transport": "hermes-http-bridge/json-rpc-stdio",
                    "harness_mcp_plugin": False,
                },
            )
        )
    for name, runtime_type, version, endpoint, config in specifications:
        value = await runtime_repository.ensure_runtime(
            session,
            name=name,
            runtime_type=runtime_type,
            version=version,
            endpoint=endpoint,
            config=config,
        )
        await _ensure_runtime_feature_profile(session, value)
        if value.status == "disabled":
            continue
        try:
            health = await get_runtime_adapter(
                runtime_type,
                endpoint=endpoint,
                version=version,
                config=config,
            ).health_check()
            await runtime_repository.record_health(session, value, online=True)
            logger.info("Runtime registered: %s version=%s", name, health.version or version)
        except RuntimeAdapterError as exc:
            await runtime_repository.record_health(session, value, online=False, error=str(exc))
            logger.warning("Runtime registered but offline: %s", name)


async def _ensure_runtime_feature_profile(session, runtime) -> None:
    existing = await session.scalar(
        select(RuntimeFeatureProfile).where(
            RuntimeFeatureProfile.runtime_registry_id == runtime.id,
            RuntimeFeatureProfile.runtime_version == runtime.version,
        )
    )
    features = {
        "tool_call": True,
        # All platform Runtime adapters own a per-run dispatcher. The model
        # sees only tool aliases and business arguments; cap1 tokens remain in
        # the adapter process and are attached to internal Gateway requests.
        "capability_gateway": runtime.type in {"hermes", "pi", "deepseek"},
        "structured_output": True,
        "streaming": True,
        "stop": True,
        "runtime_type": runtime.type,
    }
    raw = json.dumps(features, sort_keys=True, separators=(",", ":"))
    digest = f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"
    if existing is None:
        session.add(
            RuntimeFeatureProfile(
                runtime_registry_id=runtime.id,
                runtime_version=runtime.version,
                features=features,
                profile_digest=digest,
                health_status=runtime.status,
            )
        )
    else:
        existing.features = features
        existing.profile_digest = digest
        existing.health_status = runtime.status
    await session.commit()


async def _register_legacy_model(session) -> None:
    if not (
        settings.model_endpoint
        and settings.model_name
        and settings.model_registry_encryption_key is not None
    ):
        logger.warning("Model registry bootstrap skipped because legacy model settings are incomplete")
        return
    values = await model_repository.ensure_legacy_models(
        session,
        model_id=settings.model_name,
        base_url=settings.model_endpoint,
        upstream_model=settings.model_name,
        api_key=(
            settings.model_api_key.get_secret_value()
            if settings.model_api_key is not None
            else ""
        ),
        cipher=ModelSecretCipher(settings.model_registry_encryption_key.get_secret_value()),
    )
    if values:
        logger.info(
            "Legacy model configurations registered: %s",
            ", ".join(value.id for value in values),
        )


app = FastAPI(title=settings.app_name, version="0.4.0", lifespan=lifespan)


@app.middleware("http")
async def protect_control_plane_writes(request: Request, call_next):
    if (
        settings.platform_management_api_key_enabled
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and _is_control_plane_write(request.url.path)
    ):
        configured = settings.platform_management_api_key
        supplied = request.headers.get("X-Platform-Management-Key")
        if configured is None:
            return JSONResponse(
                {"detail": "平台管理密钥未配置，控制台当前为只读模式"},
                status_code=503,
            )
        if supplied is None or not secrets.compare_digest(
            supplied,
            configured.get_secret_value(),
        ):
            return JSONResponse({"detail": "平台管理密钥无效"}, status_code=401)
    return await call_next(request)


def _is_control_plane_write(path: str) -> bool:
    if path.startswith("/api/public/") or path.startswith("/internal/"):
        return False
    if path.endswith("/preflight"):
        return False
    if path.startswith("/api/agents/") and (
        path.endswith("/run") or path.endswith("/stream") or "/tasks" in path
    ):
        return False
    return path == "/api/agents" or path.startswith(
        (
            "/api/console/",
            "/api/agents/",
            "/api/skills",
            "/api/mcp-servers",
            "/api/runtimes",
            "/api/knowledge-sources",
            "/api/capabilities",
            "/api/capability-",
            "/api/connectors",
            "/api/connector-",
            "/api/credentials",
            "/api/resources",
            "/api/resource-scopes",
        )
    )
app.include_router(agents_router)
app.include_router(executions_router)
app.include_router(knowledge_sources_router)
app.include_router(mcp_servers_router)
app.include_router(memory_router)
app.include_router(model_registrations_router)
app.include_router(publications_router)
app.include_router(public_router)
app.include_router(versioned_public_router)
app.include_router(schema_versions_router)
app.include_router(skills_router)
app.include_router(orchestration_router)
app.include_router(multi_agent_router)
app.include_router(production_router)
app.include_router(runtimes_router)
app.include_router(capabilities_router)
app.include_router(console_router)
app.include_router(database_connections_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    async with SessionFactory() as session:
        await session.execute(text("SELECT 1"))
    await get_memory_store().ping()
    await get_task_queue().ping()
    await get_agent_message_bus().ping()
    await get_artifact_storage().ping()
    await KnowledgeServiceClient().health()
    return {
        "status": "ok",
        "database": "ok",
        "memory": "ok",
        "knowledge": "ok",
        "queue": "ok",
        "agent_message_bus": "ok",
        "artifact_storage": "ok",
    }

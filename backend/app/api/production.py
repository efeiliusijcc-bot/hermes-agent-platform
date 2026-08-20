from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Agent, AgentVersion
from app.db.session import get_session
from app.repositories import agents as agent_repository
from app.repositories import production as repository
from app.schemas.agent import AgentRead, AgentRunRequest, AgentRunResponse
from app.schemas.production import (
    APIClientCreate,
    APIClientRead,
    APIClientUpdate,
    APIKeyCreate,
    APIKeyRead,
    APIKeySecret,
    APIKeyStatusUpdate,
    AgentBindingCreate,
    AgentBindingRead,
    AgentHealthCheck,
    AgentHealthRead,
    AgentMetricRead,
    AgentVersionCreate,
    AgentVersionRead,
    AgentVersionStatusUpdate,
    AgentVersionUpdate,
    AuditLogRead,
    LifecycleUpdate,
    MetricsSummaryRead,
)
from app.skills import SkillLoadError, SkillLoader


router = APIRouter(tags=["production-runtime"])
LIFECYCLE_TRANSITIONS: dict[str, set[str]] = {
    "active": {"inactive", "archived"},
    "inactive": {"active", "archived"},
    "archived": set(),
}


@router.patch("/api/agents/{agent_id}/lifecycle", response_model=AgentRead)
@router.put("/api/agents/{agent_id}/lifecycle", response_model=AgentRead, include_in_schema=False)
async def update_agent_lifecycle(
    agent_id: str,
    payload: LifecycleUpdate,
    session: AsyncSession = Depends(get_session),
) -> AgentRead:
    agent = await _agent(session, agent_id)
    if payload.status == agent.status:
        return AgentRead.model_validate(agent)
    _transition(agent.status, payload.status)
    return AgentRead.model_validate(await repository.transition_agent(session, agent, payload.status))


@router.get("/api/agents/{agent_id}/health", response_model=AgentHealthRead)
async def get_agent_health(
    agent_id: str, session: AsyncSession = Depends(get_session)
) -> AgentHealthRead:
    agent = await _agent(session, agent_id)
    return await _agent_health(agent)


@router.get("/api/agents/{agent_id}/versions", response_model=list[AgentVersionRead])
async def list_agent_versions(
    agent_id: str, session: AsyncSession = Depends(get_session)
) -> list[AgentVersionRead]:
    await _agent(session, agent_id)
    return [
        AgentVersionRead.model_validate(item)
        for item in await repository.list_agent_versions(session, agent_id)
    ]


@router.post(
    "/api/agents/{agent_id}/versions",
    response_model=AgentVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_version(
    agent_id: str,
    payload: AgentVersionCreate,
    session: AsyncSession = Depends(get_session),
) -> AgentVersionRead:
    agent = await _agent(session, agent_id)
    if agent.status == "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="archived Agents are immutable")
    version = payload.version or await repository.next_agent_version(session, agent_id)
    try:
        value = await repository.create_agent_version(
            session,
            agent=agent,
            version=version,
            description=payload.description,
            created_by=payload.created_by,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent version already exists") from exc
    return AgentVersionRead.model_validate(value)


@router.get("/api/agents/{agent_id}/versions/{version}", response_model=AgentVersionRead)
async def get_agent_version(
    agent_id: str,
    version: str,
    session: AsyncSession = Depends(get_session),
) -> AgentVersionRead:
    await _agent(session, agent_id)
    return AgentVersionRead.model_validate(await _version(session, agent_id, version))


@router.patch("/api/agents/{agent_id}/versions/{version}", response_model=AgentVersionRead)
async def update_agent_version(
    agent_id: str,
    version: str,
    payload: AgentVersionUpdate,
    session: AsyncSession = Depends(get_session),
) -> AgentVersionRead:
    await _agent(session, agent_id)
    value = await _version(session, agent_id, version)
    try:
        value = await repository.update_agent_version(
            session,
            value,
            snapshot=payload.snapshot,
            description=payload.description,
            description_set="description" in payload.model_fields_set,
        )
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return AgentVersionRead.model_validate(value)


@router.patch(
    "/api/agents/{agent_id}/versions/{version}/status", response_model=AgentVersionRead,
)
async def update_agent_version_status(
    agent_id: str,
    version: str,
    payload: AgentVersionStatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> AgentVersionRead:
    await _agent(session, agent_id)
    value = await _version(session, agent_id, version)
    try:
        value = await repository.transition_agent_version(session, value, payload.status)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return AgentVersionRead.model_validate(value)


@router.post("/api/agents/{agent_id}/publish", response_model=AgentVersionRead)
async def publish_agent(
    agent_id: str,
    payload: AgentVersionCreate | None = None,
    session: AsyncSession = Depends(get_session),
) -> AgentVersionRead:
    agent = await _agent(session, agent_id)
    if agent.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="only active Agents can publish a Version",
        )
    version: AgentVersion | None = None
    if payload is not None and payload.version:
        version = await repository.get_agent_version(session, agent_id, payload.version)
        if version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent version not found")
    if version is None:
        existing = await repository.list_agent_versions(session, agent_id)
        version = next((item for item in existing if item.status == "release_candidate"), None)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no Release Candidate Agent version is available",
        )
    if version.status != "release_candidate":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="only a Release Candidate Agent version can be published",
        )
    if int((version.snapshot or {}).get("format_version") or version.snapshot_format_version or 1) == 2:
        from app.capabilities.resolver import resolve_agent_capabilities

        resolution = await resolve_agent_capabilities(session, version)
        if not resolution.ready:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Capability Preflight 未通过",
                    "issues": [item.as_dict() for item in resolution.issues],
                },
            )
        version.snapshot = {
            **version.snapshot,
            "capability_bindings": [tool.as_dict() for tool in resolution.tools],
            "resource_scope_revisions": sorted(
                {
                    tool.resource_scope_revision_id
                    for tool in resolution.tools
                    if tool.resource_scope_revision_id
                }
            ),
            "resolution_digest": resolution.resolution_digest,
        }
        version.snapshot_format_version = 2
        version.resolution_digest = resolution.resolution_digest
        await session.flush()
    try:
        runtime_agent, _ = await repository.build_version_runtime_agent(session, agent, version)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    health = await _agent_health(runtime_agent)
    if health.status != "healthy":
        failed = [name for name, check in health.checks.items() if check.status != "healthy"]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent Version health checks failed: {', '.join(failed)}",
        )
    try:
        published = await repository.publish_agent(session, agent=agent, version=version)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return AgentVersionRead.model_validate(published)


@router.post(
    "/api/agents/{agent_id}/versions/{version}/publish", response_model=AgentVersionRead,
)
async def publish_agent_version(
    agent_id: str,
    version: str,
    session: AsyncSession = Depends(get_session),
) -> AgentVersionRead:
    return await publish_agent(
        agent_id,
        AgentVersionCreate(version=version, created_by="api"),
        session,
    )


@router.post(
    "/api/agents/{agent_id}/versions/{version}/run", response_model=AgentRunResponse,
)
async def run_agent_version(
    agent_id: str,
    version: str,
    payload: AgentRunRequest,
    session: AsyncSession = Depends(get_session),
) -> AgentRunResponse:
    from app.api.agents import execute_agent_sync
    from app.memory import get_memory_store

    agent = await _agent(session, agent_id)
    if agent.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent is not active")
    value = await _version(session, agent_id, version)
    if value.status not in {"testing", "release_candidate"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="only Testing or Release Candidate versions can be executed",
        )
    try:
        runtime_agent, schema_runtime = await repository.build_version_runtime_agent(
            session, agent, value
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return await execute_agent_sync(
        runtime_agent,
        payload,
        session,
        get_memory_store(),
        schema_version=schema_runtime,
        response_mode="sync",
        agent_version_id=value.id,
    )


@router.post("/api/agents/{agent_id}/versions/{version}/rollback", response_model=AgentRead)
@router.post("/api/agents/{agent_id}/rollback/{version}", response_model=AgentRead, include_in_schema=False)
async def rollback_agent(
    agent_id: str,
    version: str,
    session: AsyncSession = Depends(get_session),
) -> AgentRead:
    agent = await _agent(session, agent_id)
    if agent.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="only active Agents can be rolled back",
        )
    value = await repository.get_agent_version(session, agent_id, version)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent version not found")
    try:
        restored = await repository.rollback_agent_version(session, agent=agent, version=value)
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return AgentRead.model_validate(restored)


@router.post("/api/api-clients", response_model=APIClientRead, status_code=status.HTTP_201_CREATED)
async def create_api_client(
    payload: APIClientCreate, session: AsyncSession = Depends(get_session)
) -> APIClientRead:
    try:
        value = await repository.create_api_client(session, **payload.model_dump())
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="API Client name already exists") from exc
    return await _client_read(session, value)


@router.get("/api/api-clients", response_model=list[APIClientRead])
async def list_api_clients(session: AsyncSession = Depends(get_session)) -> list[APIClientRead]:
    return [await _client_read(session, item) for item in await repository.list_api_clients(session)]


@router.get("/api/api-clients/{client_id}", response_model=APIClientRead)
async def get_api_client(
    client_id: UUID, session: AsyncSession = Depends(get_session)
) -> APIClientRead:
    return await _client_read(session, await _client(session, client_id))


@router.patch("/api/api-clients/{client_id}", response_model=APIClientRead)
async def update_api_client(
    client_id: UUID,
    payload: APIClientUpdate,
    session: AsyncSession = Depends(get_session),
) -> APIClientRead:
    client = await _client(session, client_id)
    try:
        client = await repository.update_api_client(
            session, client, **payload.model_dump(exclude_unset=True)
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="API Client name already exists") from exc
    return await _client_read(session, client)


@router.delete("/api/api-clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_client(
    client_id: UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    await repository.delete_api_client(session, await _client(session, client_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/api-clients/{client_id}/keys",
    response_model=APIKeySecret,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_key(
    client_id: UUID,
    payload: APIKeyCreate,
    session: AsyncSession = Depends(get_session),
) -> APIKeySecret:
    client = await _client(session, client_id)
    if client.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="API Client is not active")
    if payload.expires_at is not None:
        expires_at = payload.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="expires_at must be future")
    else:
        expires_at = None
    value, plaintext = await repository.create_api_key(
        session, client, name=payload.name, expires_at=expires_at
    )
    return APIKeySecret(**(await _key_read(session, value)).model_dump(), api_key=plaintext)


@router.get("/api/api-clients/{client_id}/keys", response_model=list[APIKeyRead])
async def list_api_keys(
    client_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[APIKeyRead]:
    await _client(session, client_id)
    return [await _key_read(session, item) for item in await repository.list_api_keys(session, client_id)]


@router.patch("/api/api-clients/{client_id}/keys/{key_id}", response_model=APIKeyRead)
async def update_api_key(
    client_id: UUID,
    key_id: UUID,
    payload: APIKeyStatusUpdate,
    session: AsyncSession = Depends(get_session),
) -> APIKeyRead:
    value = await repository.get_api_key(session, client_id, key_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key not found")
    return await _key_read(session, await repository.revoke_api_key(session, value))


@router.delete("/api/api-clients/{client_id}/keys/{key_id}", response_model=APIKeyRead)
async def revoke_api_key(
    client_id: UUID, key_id: UUID, session: AsyncSession = Depends(get_session)
) -> APIKeyRead:
    value = await repository.get_api_key(session, client_id, key_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key not found")
    return await _key_read(session, await repository.revoke_api_key(session, value))


@router.get("/api/api-clients/{client_id}/agents", response_model=list[AgentBindingRead])
async def list_client_agents(
    client_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[AgentBindingRead]:
    await _client(session, client_id)
    return [
        AgentBindingRead.model_validate(item)
        for item in await repository.list_agent_bindings(session, client_id)
    ]


@router.post(
    "/api/api-clients/{client_id}/agents",
    response_model=AgentBindingRead,
    status_code=status.HTTP_201_CREATED,
)
async def bind_client_agent(
    client_id: UUID,
    payload: AgentBindingCreate,
    session: AsyncSession = Depends(get_session),
) -> AgentBindingRead:
    await _client(session, client_id)
    await _agent(session, payload.agent_id)
    value = await repository.bind_agent(
        session,
        client_id=client_id,
        agent_id=payload.agent_id,
        permission=payload.permission,
    )
    return AgentBindingRead.model_validate(value)


@router.put(
    "/api/api-clients/{client_id}/agents/{agent_id}",
    response_model=AgentBindingRead,
    include_in_schema=False,
)
async def bind_client_agent_compat(
    client_id: UUID,
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> AgentBindingRead:
    return await bind_client_agent(
        client_id, AgentBindingCreate(agent_id=agent_id), session
    )


@router.delete("/api/api-clients/{client_id}/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unbind_client_agent(
    client_id: UUID,
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    await _client(session, client_id)
    if not await repository.unbind_agent(session, client_id, agent_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent binding not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/audit-logs", response_model=list[AuditLogRead])
async def list_audit_logs(
    agent_id: str | None = None,
    client_id: UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[AuditLogRead]:
    if status_filter not in {None, "succeeded", "failed", "rejected"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid audit status")
    return [
        AuditLogRead.model_validate(item)
        for item in await repository.list_audit_logs(
            session,
            agent_id=agent_id,
            client_id=client_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
    ]


@router.get("/api/metrics/summary", response_model=MetricsSummaryRead)
async def get_metrics_summary(
    session: AsyncSession = Depends(get_session),
) -> MetricsSummaryRead:
    return MetricsSummaryRead.model_validate(await repository.metrics_summary(session))


@router.get("/api/metrics/agents", response_model=list[AgentMetricRead])
async def list_metrics_agents(
    session: AsyncSession = Depends(get_session),
) -> list[AgentMetricRead]:
    return [AgentMetricRead.model_validate(item) for item in await repository.list_agent_metrics(session)]


@router.get("/api/metrics/agents/{agent_id}", response_model=AgentMetricRead)
async def get_metrics_agent(
    agent_id: str, session: AsyncSession = Depends(get_session)
) -> AgentMetricRead:
    await _agent(session, agent_id)
    value = await repository.get_agent_metrics(session, agent_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent metrics not found")
    return AgentMetricRead.model_validate(value)


async def _agent(session: AsyncSession, agent_id: str) -> Agent:
    value = await agent_repository.get_agent(session, agent_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return value


async def _version(session: AsyncSession, agent_id: str, version: str) -> AgentVersion:
    value = await repository.get_agent_version(session, agent_id, version)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent version not found")
    return value


def _transition(current: str, target: str) -> None:
    if target == current:
        return
    if target not in LIFECYCLE_TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"invalid Agent lifecycle transition: {current} -> {target}",
        )


def _validate_lifecycle_transition(current: str, target: str) -> None:
    """Stable test/integration alias for the deterministic lifecycle guard."""
    _transition(current, target)


async def _client(session: AsyncSession, client_id: UUID):
    value = await repository.get_api_client(session, client_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Client not found")
    return value


async def _client_read(session: AsyncSession, value) -> APIClientRead:
    return APIClientRead.model_validate(
        {**APIClientRead.model_validate(value).model_dump(), **await repository.api_client_counts(session, value.id)}
    )


async def _key_read(session: AsyncSession, value) -> APIKeyRead:
    return APIKeyRead.model_validate(
        {**APIKeyRead.model_validate(value).model_dump(), "call_count": await repository.api_key_call_count(session, value.id)}
    )


async def _agent_health(agent: Agent) -> AgentHealthRead:
    checks: dict[str, AgentHealthCheck] = {}
    started = monotonic()
    try:
        # A process-level /health check can stay green while the selected model
        # or its credentials are unusable.  Exercise the real adapter with a
        # minimal, non-sensitive prompt before permitting publication.
        from app.model_adapters import get_model_adapter

        result = await get_model_adapter(agent.model_adapter).chat(
            [{"role": "user", "content": "HEALTH_CHECK_OK"}],
            model=agent.model,
            agent_id=agent.id,
            execution_id=f"health-{agent.id}",
        )
        if result.status in {"completed", "succeeded"} and result.output:
            checks["model"] = AgentHealthCheck(
                status="healthy",
                detail=(
                    f"Model {agent.model} completed a probe "
                    f"({round((monotonic() - started) * 1000)} ms)"
                ),
            )
        else:
            checks["model"] = AgentHealthCheck(
                status="unhealthy", detail=f"Model {agent.model} probe did not complete"
            )
    except Exception as exc:
        checks["model"] = AgentHealthCheck(
            status="unhealthy",
            detail=f"Model {agent.model} unavailable: {type(exc).__name__}",
        )

    try:
        loaded = SkillLoader().load_many(agent.skills)
        checks["skills"] = AgentHealthCheck(
            status="healthy", detail=f"{len(loaded)} bound Skill package(s) loaded"
        )
    except SkillLoadError as exc:
        checks["skills"] = AgentHealthCheck(status="unhealthy", detail=str(exc))

    unavailable_mcp: list[str] = []
    for item in agent.mcp_servers:
        request_id = f"health-{agent.id}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    item.endpoint,
                    headers={"Accept": "application/json, text/event-stream"},
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "hermes-agent-platform", "version": "0.3.1"},
                        },
                    },
                )
            if not _valid_mcp_initialize_response(response, request_id=request_id):
                unavailable_mcp.append(item.id)
        except httpx.HTTPError:
            unavailable_mcp.append(item.id)
    checks["mcp"] = AgentHealthCheck(
        status="healthy" if not unavailable_mcp else "unhealthy",
        detail=(
            f"{len(agent.mcp_servers)} bound MCP server(s) responded"
            if not unavailable_mcp
            else f"MCP servers are unavailable: {', '.join(sorted(unavailable_mcp))}"
        ),
    )
    overall = "healthy" if all(item.status == "healthy" for item in checks.values()) else "unhealthy"
    return AgentHealthRead(
        agent_id=agent.id,
        status=overall,
        checks=checks,
        checked_at=datetime.now(timezone.utc),
    )


def _valid_mcp_initialize_response(response: httpx.Response, *, request_id: str) -> bool:
    """Accept only a successful, matching JSON-RPC initialize result."""
    if response.status_code < 200 or response.status_code >= 300:
        return False
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return False
    return bool(
        isinstance(payload, dict)
        and payload.get("jsonrpc") == "2.0"
        and payload.get("id") == request_id
        and isinstance(payload.get("result"), dict)
        and "error" not in payload
    )

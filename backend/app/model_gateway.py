from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import ModelRegistration
from app.model_secrets import ModelSecretCipher, ModelSecretError
from app.repositories import model_registrations as repository


logger = logging.getLogger(__name__)


class ModelGatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    model_endpoint: str
    model_api_key: SecretStr
    model_name: str
    model_gateway_api_key: SecretStr
    model_registry_encryption_key: SecretStr | None = None
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "hermes_agent"
    postgres_user: str = "hermes_agent"
    postgres_password: SecretStr | None = None
    model_timeout_seconds: int = 180
    model_max_concurrency: int = 5
    model_queue_timeout_seconds: float = 60
    model_max_retries: int = 2
    model_retry_delay_seconds: float = 1

    @property
    def database_url(self) -> str | None:
        if self.postgres_password is None:
            return None
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password.get_secret_value())
        return (
            f"postgresql+asyncpg://{user}:{password}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@dataclass(frozen=True)
class ResolvedModel:
    alias: str
    provider: str
    endpoint: str
    upstream_model: str
    api_key: str
    timeout_seconds: int
    max_retries: int


settings = ModelGatewaySettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.model_timeout_seconds, connect=10)
    )
    app.state.model_capacity = asyncio.Semaphore(settings.model_max_concurrency)
    app.state.model_active = 0
    app.state.model_peak = 0
    app.state.registry_session_factory = None
    app.state.registry_engine = None
    if settings.database_url:
        engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=3)
        app.state.registry_engine = engine
        app.state.registry_session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield
    await app.state.client.aclose()
    if app.state.registry_engine is not None:
        await app.state.registry_engine.dispose()


app = FastAPI(title="Hermes Model Gateway", version="0.2.0", lifespan=lifespan)


def authorize(authorization: str | None) -> None:
    expected = f"Bearer {settings.model_gateway_api_key.get_secret_value()}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid model gateway key")


@app.get("/health")
async def health(request: Request) -> dict[str, str | int]:
    return {
        "status": "ok",
        "active": request.app.state.model_active,
        "peak": request.app.state.model_peak,
        "max_concurrency": settings.model_max_concurrency,
        "registry": "configured" if request.app.state.registry_session_factory else "legacy-fallback",
    }


@app.get("/v1/models")
async def list_models(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    authorize(authorization)
    values, available = await _list_registry_models(request)
    if not available or not values:
        return {
            "object": "list",
            "data": [{"id": settings.model_name, "object": "model", "owned_by": "external"}],
        }
    return {
        "object": "list",
        "data": [
            {"id": value.id, "object": "model", "owned_by": value.provider}
            for value in values
        ],
    }


@app.get("/v1/models/{model_id}")
async def get_model(
    model_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    authorize(authorization)
    resolved = await _resolve_model(request, model_id)
    return {"id": resolved.alias, "object": "model", "owned_by": resolved.provider}


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse | StreamingResponse:
    authorize(authorization)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="request body must be an object",
        )
    requested_alias = payload.get("model")
    if requested_alias is not None and (
        not isinstance(requested_alias, str) or not requested_alias.strip()
    ):
        requested_alias = None
    resolved = await _resolve_model(request, requested_alias)
    payload["model"] = resolved.upstream_model
    headers = {"Content-Type": "application/json"}
    if resolved.api_key:
        headers["Authorization"] = f"Bearer {resolved.api_key}"
    client: httpx.AsyncClient = request.app.state.client
    capacity = request.app.state.model_capacity
    try:
        await asyncio.wait_for(capacity.acquire(), timeout=settings.model_queue_timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="model concurrency queue timed out",
        ) from exc
    request.app.state.model_active += 1
    request.app.state.model_peak = max(
        request.app.state.model_peak,
        request.app.state.model_active,
    )

    if not payload.get("stream"):
        try:
            upstream = await _send_with_retry(
                client,
                resolved.endpoint,
                headers,
                payload,
                timeout_seconds=resolved.timeout_seconds,
                max_retries=resolved.max_retries,
            )
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="model request timed out",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="model request failed",
            ) from exc
        finally:
            _release_capacity(request)
        return JSONResponse(status_code=upstream.status_code, content=_json_body(upstream))

    upstream_request = client.build_request(
        "POST",
        resolved.endpoint,
        headers=headers,
        json=payload,
        timeout=httpx.Timeout(resolved.timeout_seconds, connect=10),
    )
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.TimeoutException as exc:
        _release_capacity(request)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="model request timed out",
        ) from exc
    except httpx.HTTPError as exc:
        _release_capacity(request)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="model request failed",
        ) from exc

    if upstream.is_error:
        body = await upstream.aread()
        await upstream.aclose()
        _release_capacity(request)
        try:
            content: Any = upstream.json()
        except ValueError:
            content = {"error": {"message": body.decode(errors="replace")[:500]}}
        return JSONResponse(status_code=upstream.status_code, content=content)

    async def relay() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            _release_capacity(request)

    return StreamingResponse(
        relay(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


async def _resolve_model(request: Request, model_id: str | None) -> ResolvedModel:
    factory: async_sessionmaker[AsyncSession] | None = request.app.state.registry_session_factory
    registry_available = factory is not None
    value: ModelRegistration | None = None
    if factory is not None:
        try:
            async with factory() as session:
                value = await repository.resolve_model(session, model_id)
        except SQLAlchemyError:
            registry_available = False
            logger.warning("Model registry unavailable; legacy fallback is limited to the configured model")
    if value is not None:
        try:
            api_key = (
                _registry_cipher().decrypt(value.api_key_ciphertext)
                if value.api_key_ciphertext
                else ""
            )
        except ModelSecretError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="registered model credential cannot be decrypted",
            ) from exc
        return ResolvedModel(
            alias=value.id,
            provider=value.provider,
            endpoint=_chat_completions_url(value.base_url),
            upstream_model=value.upstream_model,
            api_key=api_key,
            timeout_seconds=value.timeout_seconds,
            max_retries=value.max_retries,
        )
    if model_id is None or model_id == settings.model_name:
        return _legacy_model()
    detail = "registered model is not found or disabled"
    if not registry_available:
        detail = "model registry is unavailable and the requested model has no legacy fallback"
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


async def _list_registry_models(
    request: Request,
) -> tuple[list[ModelRegistration], bool]:
    factory: async_sessionmaker[AsyncSession] | None = request.app.state.registry_session_factory
    if factory is None:
        return [], False
    try:
        async with factory() as session:
            return await repository.list_models(session, enabled_only=True), True
    except SQLAlchemyError:
        logger.warning("Model registry unavailable while listing models")
        return [], False


def _registry_cipher() -> ModelSecretCipher:
    if settings.model_registry_encryption_key is None:
        raise ModelSecretError("MODEL_REGISTRY_ENCRYPTION_KEY is not configured")
    return ModelSecretCipher(settings.model_registry_encryption_key.get_secret_value())


def _legacy_model() -> ResolvedModel:
    return ResolvedModel(
        alias=settings.model_name,
        provider="external",
        endpoint=_chat_completions_url(settings.model_endpoint),
        upstream_model=settings.model_name,
        api_key=settings.model_api_key.get_secret_value(),
        timeout_seconds=settings.model_timeout_seconds,
        max_retries=settings.model_max_retries,
    )


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


def _json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"error": {"message": response.text[:500]}}


async def _send_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    timeout_seconds: int,
    max_retries: int,
) -> httpx.Response:
    retry_statuses = {429, 502, 503, 504}
    response: httpx.Response | None = None
    for attempt in range(max_retries + 1):
        response = await client.post(
            url,
            headers=headers,
            json=payload,
            timeout=httpx.Timeout(timeout_seconds, connect=10),
        )
        if response.status_code not in retry_statuses or attempt >= max_retries:
            return response
        await asyncio.sleep(settings.model_retry_delay_seconds * (attempt + 1))
    assert response is not None
    return response


def _release_capacity(request: Request) -> None:
    request.app.state.model_active = max(0, request.app.state.model_active - 1)
    request.app.state.model_capacity.release()

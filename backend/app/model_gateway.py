from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelGatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    model_endpoint: str
    model_api_key: SecretStr
    model_name: str
    model_gateway_api_key: SecretStr
    model_timeout_seconds: int = 180
    model_max_concurrency: int = 5
    model_queue_timeout_seconds: float = 60
    model_max_retries: int = 2
    model_retry_delay_seconds: float = 1

    @property
    def chat_completions_url(self) -> str:
        base = self.model_endpoint.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


settings = ModelGatewaySettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(settings.model_timeout_seconds, connect=10))
    app.state.model_capacity = asyncio.Semaphore(settings.model_max_concurrency)
    app.state.model_active = 0
    app.state.model_peak = 0
    yield
    await app.state.client.aclose()


app = FastAPI(title="Hermes Model Gateway", version="0.1.0", lifespan=lifespan)


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
    }


@app.get("/v1/models")
async def list_models(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    authorize(authorization)
    return {
        "object": "list",
        "data": [{"id": settings.model_name, "object": "model", "owned_by": "external"}],
    }


@app.get("/v1/models/{model_id}")
async def get_model(model_id: str, authorization: str | None = Header(default=None)) -> dict[str, str]:
    authorize(authorization)
    if model_id != settings.model_name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="model not found")
    return {"id": settings.model_name, "object": "model", "owned_by": "external"}


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse | StreamingResponse:
    authorize(authorization)
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="request body must be an object")
    if not isinstance(payload.get("model"), str) or not payload["model"].strip():
        payload["model"] = settings.model_name
    headers = {
        "Authorization": f"Bearer {settings.model_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }
    client: httpx.AsyncClient = request.app.state.client
    capacity = request.app.state.model_capacity
    try:
        await asyncio.wait_for(capacity.acquire(), timeout=settings.model_queue_timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="model concurrency queue timed out") from exc
    request.app.state.model_active += 1
    request.app.state.model_peak = max(request.app.state.model_peak, request.app.state.model_active)

    if not payload.get("stream"):
        try:
            upstream = await _send_with_retry(client, settings.chat_completions_url, headers, payload)
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="model request timed out") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="model request failed") from exc
        finally:
            _release_capacity(request)
        return JSONResponse(status_code=upstream.status_code, content=_json_body(upstream))

    upstream_request = client.build_request("POST", settings.chat_completions_url, headers=headers, json=payload)
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.TimeoutException as exc:
        _release_capacity(request)
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="model request timed out") from exc
    except httpx.HTTPError as exc:
        _release_capacity(request)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="model request failed") from exc

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

    return StreamingResponse(relay(), status_code=upstream.status_code, media_type=upstream.headers.get("content-type"))


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
) -> httpx.Response:
    retry_statuses = {429, 502, 503, 504}
    response: httpx.Response | None = None
    for attempt in range(settings.model_max_retries + 1):
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code not in retry_statuses or attempt >= settings.model_max_retries:
            return response
        await asyncio.sleep(settings.model_retry_delay_seconds * (attempt + 1))
    assert response is not None
    return response


def _release_capacity(request: Request) -> None:
    request.app.state.model_active = max(0, request.app.state.model_active - 1)
    request.app.state.model_capacity.release()

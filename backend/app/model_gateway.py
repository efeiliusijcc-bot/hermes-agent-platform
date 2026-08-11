from __future__ import annotations

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

    @property
    def chat_completions_url(self) -> str:
        base = self.model_endpoint.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


settings = ModelGatewaySettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(settings.model_timeout_seconds, connect=10))
    yield
    await app.state.client.aclose()


app = FastAPI(title="Hermes Model Gateway", version="0.1.0", lifespan=lifespan)


def authorize(authorization: str | None) -> None:
    expected = f"Bearer {settings.model_gateway_api_key.get_secret_value()}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid model gateway key")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
    payload["model"] = settings.model_name
    headers = {
        "Authorization": f"Bearer {settings.model_api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }
    client: httpx.AsyncClient = request.app.state.client

    if not payload.get("stream"):
        try:
            upstream = await client.post(settings.chat_completions_url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="model request timed out") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="model request failed") from exc
        return JSONResponse(status_code=upstream.status_code, content=_json_body(upstream))

    upstream_request = client.build_request("POST", settings.chat_completions_url, headers=headers, json=payload)
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="model request timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="model request failed") from exc

    if upstream.is_error:
        body = await upstream.aread()
        await upstream.aclose()
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

    return StreamingResponse(relay(), status_code=upstream.status_code, media_type=upstream.headers.get("content-type"))


def _json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"error": {"message": response.text[:500]}}

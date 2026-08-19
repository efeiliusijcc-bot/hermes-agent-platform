from __future__ import annotations

import hmac
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse


def _required_secret(name: str) -> str:
    value = os.getenv(name, "")
    if len(value) < 32:
        raise RuntimeError(f"{name} must contain at least 32 characters")
    return value


RUNTIME_API_KEY = _required_secret("DEEPSEEK_RUNTIME_API_KEY")
MODEL_GATEWAY_API_KEY = _required_secret("MODEL_GATEWAY_API_KEY")
CORE_ENDPOINT = os.getenv("DEEPSEEK_HARNESS_CORE_ENDPOINT", "http://deepseek-harness-core:8771").rstrip("/")
MODEL_ENDPOINT = os.getenv("MODEL_GATEWAY_ENDPOINT", "http://model-gateway:8080").rstrip("/")
CAPABILITY_ENDPOINT = os.getenv(
    "CAPABILITY_GATEWAY_ENDPOINT",
    "http://mcp-gateway:8090/internal/capabilities",
).rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("DEEPSEEK_RUNTIME_REQUEST_TIMEOUT_SECONDS", "900"))
MAX_REQUEST_BYTES = int(os.getenv("DEEPSEEK_RUNTIME_REQUEST_MAX_BYTES", "2097152"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS + 30, connect=10)
    )
    try:
        yield
    finally:
        await app.state.client.aclose()


app = FastAPI(title="Hermes DeepSeek Runtime Security Gateway", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health(request: Request) -> StreamingResponse:
    return await _relay(request, f"{CORE_ENDPOINT}/health", authorization=None)


@app.api_route("/model/v1/{path:path}", methods=["GET", "POST"])
async def model_proxy(path: str, request: Request) -> StreamingResponse:
    if path not in {"models", "chat/completions"} and not path.startswith("models/"):
        raise HTTPException(status_code=404, detail="unsupported model gateway path")
    return await _relay(
        request,
        f"{MODEL_ENDPOINT}/v1/{path}",
        authorization=f"Bearer {MODEL_GATEWAY_API_KEY}",
    )


@app.post("/capability/{operation}")
async def capability_proxy(
    operation: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    if operation not in {"resolve", "invoke"}:
        raise HTTPException(status_code=404, detail="unsupported Capability Gateway path")
    if not authorization or not authorization.startswith("Bearer cap1."):
        raise HTTPException(status_code=401, detail="missing Execution Capability Token")
    return await _relay(
        request,
        f"{CAPABILITY_ENDPOINT}/{operation}",
        authorization=authorization,
    )


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def runtime_proxy(
    path: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    _authorize(authorization)
    return await _relay(request, f"{CORE_ENDPOINT}/{path}", authorization=None)


def _authorize(authorization: str | None) -> None:
    expected = f"Bearer {RUNTIME_API_KEY}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid DeepSeek Runtime key")


async def _relay(
    request: Request,
    target: str,
    *,
    authorization: str | None,
) -> StreamingResponse:
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="request body is too large")
    headers: dict[str, str] = {}
    content_type = request.headers.get("content-type")
    accept = request.headers.get("accept")
    if content_type:
        headers["Content-Type"] = content_type
    if accept:
        headers["Accept"] = accept
    if authorization:
        headers["Authorization"] = authorization
    client: httpx.AsyncClient = request.app.state.client
    upstream_request = client.build_request(
        request.method,
        target,
        params=request.query_params,
        headers=headers,
        content=body,
    )
    try:
        upstream = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="DeepSeek Runtime upstream is unavailable") from exc

    async def chunks() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()

    response_headers: dict[str, str] = {"Cache-Control": "no-store"}
    if upstream.headers.get("content-type") == "text/event-stream":
        response_headers["X-Accel-Buffering"] = "no"
    return StreamingResponse(
        chunks(),
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
        headers=response_headers,
    )

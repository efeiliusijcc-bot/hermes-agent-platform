from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class SourceRecallGatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    source_recall_upstream_endpoint: str = ""
    source_recall_upstream_api_key: SecretStr | None = None
    source_recall_gateway_api_key: SecretStr | None = None
    source_recall_upstream_timeout_seconds: int = 60
    source_recall_upstream_max_retries: int = 1
    source_recall_upstream_retry_delay_seconds: float = 0.5
    source_recall_max_lookback_days: int = 3650
    source_recall_max_limit: int = 20

    @property
    def configured(self) -> bool:
        return bool(
            self.source_recall_upstream_endpoint
            and self.source_recall_upstream_api_key
            and self.source_recall_gateway_api_key
        )


class RecallRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=20_000)
    lookback_days: int = Field(default=3650, alias="lookbackDays", ge=1)
    limit: int = Field(default=20, ge=1)


settings = SourceRecallGatewaySettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.source_recall_upstream_timeout_seconds, connect=10)
    )
    yield
    await app.state.client.aclose()


app = FastAPI(title="Hermes Source Recall Gateway", version="0.1.0", lifespan=lifespan)


def authorize(authorization: str | None) -> None:
    configured = settings.source_recall_gateway_api_key
    if configured is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="gateway is not configured")
    expected = f"Bearer {configured.get_secret_value()}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid gateway key")


@app.get("/health")
async def health() -> dict[str, str | bool]:
    return {"status": "ok", "configured": settings.configured}


@app.post("/v1/recall")
async def recall(
    payload: RecallRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    authorize(authorization)
    if not settings.configured:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="gateway is not configured")
    if payload.lookback_days > settings.source_recall_max_lookback_days:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="lookbackDays exceeds limit")
    if payload.limit > settings.source_recall_max_limit:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="limit exceeds limit")
    upstream_key = settings.source_recall_upstream_api_key
    assert upstream_key is not None
    headers = {
        "Content-Type": "application/json",
        "X-Hermes-Recall-Key": upstream_key.get_secret_value(),
    }
    body = {
        "topic": payload.topic,
        "lookbackDays": payload.lookback_days,
        "limit": payload.limit,
    }
    client: httpx.AsyncClient = request.app.state.client
    response: httpx.Response | None = None
    try:
        for attempt in range(settings.source_recall_upstream_max_retries + 1):
            response = await client.post(settings.source_recall_upstream_endpoint, headers=headers, json=body)
            if response.status_code not in {429, 502, 503, 504}:
                break
            if attempt < settings.source_recall_upstream_max_retries:
                await asyncio.sleep(settings.source_recall_upstream_retry_delay_seconds * (attempt + 1))
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="source recall timed out") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="source recall request failed") from exc
    assert response is not None
    if response.is_error:
        raise HTTPException(
            status_code=response.status_code if 400 <= response.status_code < 500 else 502,
            detail=f"source recall upstream returned {response.status_code}",
        )
    try:
        value = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="source recall returned invalid JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get("sources"), list):
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="source recall returned invalid data")
    return value

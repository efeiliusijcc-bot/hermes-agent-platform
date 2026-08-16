from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings


class SourceRecallError(RuntimeError):
    pass


class SourceRecallSource(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    document_id: str = Field(alias="documentId")
    title: str
    url: str | None = None
    summary: str = ""
    excerpt: str = ""
    source_name: str | None = Field(default=None, alias="sourceName")
    published_at: str | None = Field(default=None, alias="publishedAt")
    retrieval_sources: list[str] = Field(default_factory=list, alias="retrievalSources")
    scores: dict[str, Any] = Field(default_factory=dict)


class SourceRecallResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    status: str
    request_id: str | None = Field(default=None, alias="requestId")
    retrieval_mode: str | None = Field(default=None, alias="retrievalMode")
    sources: list[SourceRecallSource] = Field(default_factory=list)
    total_hits: int = Field(default=0, alias="totalHits")
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    updated_at: str | None = Field(default=None, alias="updatedAt")


class SourceRecallClient:
    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        enabled: bool | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        settings = get_settings()
        self.enabled = settings.source_recall_enabled if enabled is None else enabled
        self.endpoint = (endpoint or settings.source_recall_gateway_endpoint).rstrip("/")
        configured_key = settings.source_recall_gateway_api_key
        self.api_key = api_key if api_key is not None else (
            configured_key.get_secret_value() if configured_key is not None else ""
        )
        self.timeout = timeout_seconds or settings.source_recall_timeout_seconds

    async def recall(self, *, topic: str, lookback_days: int, limit: int) -> SourceRecallResult:
        if not self.enabled:
            raise SourceRecallError("source recall is disabled")
        if not self.endpoint or not self.api_key:
            raise SourceRecallError("source recall gateway is not configured")
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=10)) as client:
                response = await client.post(
                    f"{self.endpoint}/v1/recall",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={"topic": topic, "lookbackDays": lookback_days, "limit": limit},
                )
        except httpx.TimeoutException as exc:
            raise SourceRecallError("source recall gateway timed out") from exc
        except httpx.HTTPError as exc:
            raise SourceRecallError("source recall gateway request failed") from exc
        if response.is_error:
            raise SourceRecallError(f"source recall gateway rejected the request ({response.status_code})")
        try:
            return SourceRecallResult.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise SourceRecallError("source recall gateway returned invalid JSON") from exc


def prompt_sources(result: SourceRecallResult) -> list[dict[str, Any]]:
    settings = get_settings()
    values: list[dict[str, Any]] = []
    for item in result.sources:
        values.append(
            {
                "source_id": f"external-recall:{item.document_id}",
                "document_id": item.document_id,
                "title": item.title,
                "url": item.url,
                "summary": item.summary[: settings.source_recall_summary_max_chars],
                "excerpt": item.excerpt[: settings.source_recall_excerpt_max_chars],
                "source_name": item.source_name,
                "published_at": item.published_at,
                "retrieval_sources": item.retrieval_sources,
                "scores": item.scores,
            }
        )
    return values

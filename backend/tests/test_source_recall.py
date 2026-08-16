from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.api.agents import _render_knowledge_prompt, _source_recall_options
from app.source_recall import SourceRecallClient, SourceRecallError, SourceRecallResult, prompt_sources
from app import source_recall_gateway


@pytest.mark.asyncio
async def test_source_recall_client_calls_internal_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "requestId": "request-1",
                "retrievalMode": "hybrid",
                "sources": [
                    {
                        "documentId": "doc-1",
                        "title": "内部材料",
                        "summary": "摘要",
                        "excerpt": "证据",
                        "sourceName": "内网信源",
                        "publishedAt": "2026-08-17T00:00:00Z",
                        "scores": {"final": 0.9},
                    }
                ],
                "totalHits": 1,
            },
        )

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def client_factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    result = await SourceRecallClient(
        endpoint="http://source-recall-gateway:8082",
        api_key="internal-secret",
        enabled=True,
        timeout_seconds=10,
    ).recall(topic="测试主题", lookback_days=3650, limit=20)

    assert result.request_id == "request-1"
    assert result.sources[0].document_id == "doc-1"
    assert seen["authorization"] == "Bearer internal-secret"
    assert '"topic":"测试主题"' in str(seen["body"])


@pytest.mark.asyncio
async def test_source_recall_client_fails_closed_without_gateway_key() -> None:
    with pytest.raises(SourceRecallError, match="not configured"):
        await SourceRecallClient(
            endpoint="http://source-recall-gateway:8082",
            api_key="",
            enabled=True,
        ).recall(topic="测试主题", lookback_days=30, limit=5)


def test_skill_config_enables_bounded_source_recall() -> None:
    skills = [
        SimpleNamespace(
            config={"source_recall": {"enabled": True, "lookback_days": 999_999, "limit": 999}}
        )
    ]
    assert _source_recall_options(skills) == {"lookback_days": 36_500, "limit": 20}


def test_source_recall_prompt_is_truncated_and_marks_fallback() -> None:
    result = SourceRecallResult.model_validate(
        {
            "status": "fallback",
            "retrievalMode": "hybrid",
            "sources": [
                {
                    "documentId": "doc-1",
                    "title": "召回材料",
                    "summary": "摘" * 5000,
                    "excerpt": "证" * 5000,
                }
            ],
            "diagnostics": {"retrieverErrors": [{"source": "embedding", "message": "unavailable"}]},
        }
    )
    values = prompt_sources(result)
    assert len(values[0]["summary"]) == 1200
    assert len(values[0]["excerpt"]) == 2000
    rendered = _render_knowledge_prompt([], source_recall_result=result)
    assert '"status":"fallback"' in rendered
    assert "does not prove relevance" in rendered


def test_gateway_authorization_uses_internal_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        source_recall_gateway.settings,
        "source_recall_gateway_api_key",
        SecretStr("gateway-secret"),
    )
    source_recall_gateway.authorize("Bearer gateway-secret")
    with pytest.raises(Exception) as exc_info:
        source_recall_gateway.authorize("Bearer wrong")
    assert getattr(exc_info.value, "status_code", None) == 401

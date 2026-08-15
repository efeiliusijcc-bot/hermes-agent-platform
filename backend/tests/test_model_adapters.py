from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.model_adapters import get_model_adapter, supported_model_adapters
from app.runtime.hermes import HermesClient, HermesRunResult


def test_supported_provider_adapters_share_the_chat_interface() -> None:
    assert supported_model_adapters() == ("hermes", "qwen", "deepseek", "gpt", "claude")
    for name in supported_model_adapters():
        adapter = get_model_adapter(name)
        assert adapter.name == name
        assert adapter.render_messages([{"role": "user", "content": "hello"}]) == "USER:\nhello"


def test_runtime_token_usage_requires_an_explicit_total() -> None:
    assert HermesClient._extract_token_usage({"usage": {"total_tokens": 19}}) == 19
    assert HermesClient._extract_token_usage({"usage": {"total_tokens": 0}}) == 0
    assert HermesClient._extract_token_usage({"usage": {"input_tokens": 10, "output_tokens": 9}}) is None
    assert HermesClient._extract_token_usage({"usage": {"total_tokens": "19"}}) is None
    assert HermesClient._extract_token_usage({}) is None


@pytest.mark.asyncio
async def test_adapter_passes_model_and_provider_to_hermes_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    async def fake_run(self: object, **kwargs: Any) -> HermesRunResult:
        received.update(kwargs)
        return HermesRunResult(output="ok", run_id="run-1", status="completed")

    monkeypatch.setattr("app.model_adapters.registry.HermesClient.run", fake_run)
    result = await get_model_adapter("gpt").chat(
        [{"role": "user", "content": "hello"}],
        model="gpt-5",
        agent_id="agent-a",
        execution_id="execution-a",
    )
    assert result.output == "ok"
    assert received["requested_model"] == "gpt-5"
    assert received["model_adapter"] == "gpt"


@pytest.mark.asyncio
async def test_runtime_sync_result_preserves_explicit_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads = iter(
        [
            {"id": "run-usage", "status": "running"},
            {
                "id": "run-usage",
                "status": "completed",
                "output": "ok",
                "usage": {"input_tokens": 7, "output_tokens": 4, "total_tokens": 11},
            },
        ]
    )

    async def request_json(*args: object, **kwargs: object) -> dict[str, Any]:
        return next(payloads)

    async def no_sleep(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.runtime.hermes.HermesClient._request_json", request_json)
    monkeypatch.setattr("app.runtime.hermes.asyncio.sleep", no_sleep)
    result = await get_model_adapter("hermes").chat(
        [{"role": "user", "content": "hello"}],
        model="test-model",
        agent_id="agent-a",
        execution_id="execution-a",
    )
    assert result.token_usage == 11


@pytest.mark.asyncio
async def test_adapter_streams_native_runtime_events(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream(self: object, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"event": "message.delta", "delta": "A", "metadata": kwargs}
        yield {"event": "run.completed", "output": "A"}

    monkeypatch.setattr("app.model_adapters.registry.HermesClient.stream", fake_stream)
    events = [
        event
        async for event in get_model_adapter("claude").stream_chat(
            [{"role": "user", "content": "hello"}],
            model="claude-4",
            agent_id="agent-a",
            execution_id="execution-a",
        )
    ]
    assert events[0]["metadata"]["requested_model"] == "claude-4"
    assert events[0]["metadata"]["model_adapter"] == "claude"


@pytest.mark.asyncio
async def test_runtime_stream_preserves_explicit_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream(self: object, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {
            "event": "run.completed",
            "output": "A",
            "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
        }

    monkeypatch.setattr("app.model_adapters.registry.HermesClient.stream", fake_stream)
    events = [
        event
        async for event in get_model_adapter("qwen").stream_chat(
            [{"role": "user", "content": "hello"}],
            model="qwen-test",
            agent_id="agent-a",
            execution_id="execution-a",
        )
    ]
    assert events[-1]["usage"]["total_tokens"] == 8

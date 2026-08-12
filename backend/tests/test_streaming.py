from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from app.api.agents import _map_hermes_event, _sse
from app.runtime.hermes import HermesClient
from app.schemas.agent import AgentCreate, AgentResponseModeUpdate


def test_response_mode_defaults_to_sync_and_accepts_stream() -> None:
    payload = AgentCreate(
        id="stream-agent",
        name="Stream Agent",
        role="tester",
        system_prompt="test",
        model_config={},
        status="active",
    )
    assert payload.response_mode == "sync"
    assert AgentResponseModeUpdate(response_mode="stream").response_mode == "stream"
    with pytest.raises(ValidationError):
        AgentResponseModeUpdate(response_mode="websocket")


def test_maps_native_hermes_events_to_phase25_contract() -> None:
    assert _map_hermes_event({"event": "message.delta", "delta": "分析"}) == (
        "token",
        {"event": "token", "text": "分析"},
    )
    assert _map_hermes_event({"event": "tool.started", "tool": "database_query"}) == (
        "tool",
        {
            "event": "tool",
            "type": "started",
            "name": "database_query",
            "duration": None,
            "error": False,
        },
    )
    assert _map_hermes_event({"event": "run.completed", "output": "done"}) is None
    assert _sse("token", {"event": "token", "text": "分析"}) == (
        'event: token\ndata: {"event":"token","text":"分析"}\n\n'
    )


@pytest.mark.asyncio
async def test_hermes_client_streams_native_run_events(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        {"event": "message.delta", "run_id": "run_test", "delta": "分"},
        {"event": "message.delta", "run_id": "run_test", "delta": "析"},
        {"event": "run.completed", "run_id": "run_test", "output": "分析"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"run_id": "run_test", "status": "started"})
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def client_factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    received = [
        event
        async for event in HermesClient().stream(
            prompt="test",
            agent_id="stream-agent",
            execution_id="execution-1",
        )
    ]
    assert received[0] == {"event": "run.created", "run_id": "run_test", "status": "started"}
    assert received[1:] == events

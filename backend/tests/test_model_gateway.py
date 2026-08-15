from __future__ import annotations

import json

import httpx
import pytest
from fastapi import Request
import asyncio

from app import model_gateway
from app.model_stub import _flatten_messages, _phase6_tool_call, _streamed_tool_call


class FakeClient:
    def __init__(self) -> None:
        self.payload: dict[str, object] = {}

    async def post(self, url: str, *, headers: dict[str, str], json: dict[str, object]) -> httpx.Response:
        self.payload = json
        return httpx.Response(200, json={"model": json["model"], "choices": []})


def request_with(payload: bytes, client: FakeClient) -> Request:
    sent = False

    async def receive() -> dict[str, object]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []}, receive)
    request.scope["app"] = type(
        "App",
        (),
        {
            "state": type(
                "State",
                (),
                {"client": client, "model_capacity": asyncio.Semaphore(5), "model_active": 0, "model_peak": 0},
            )()
        },
    )()
    return request


@pytest.mark.asyncio
async def test_model_gateway_preserves_explicit_agent_model(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(model_gateway, "authorize", lambda value: None)
    await model_gateway.chat_completions(request_with(b'{"model":"qwen-32b","messages":[]}', client))
    assert client.payload["model"] == "qwen-32b"


@pytest.mark.asyncio
async def test_model_gateway_uses_platform_default_when_model_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(model_gateway, "authorize", lambda value: None)
    await model_gateway.chat_completions(request_with(b'{"messages":[]}', client))
    assert client.payload["model"] == model_gateway.settings.model_name


def test_contract_stub_can_distinguish_phase3_concurrent_agents() -> None:
    prompt = _flatten_messages([{"role": "user", "content": "run PHASE3_AGENT_B"}])
    assert "PHASE3_AGENT_B" in prompt


def test_contract_stub_issues_phase6_filesystem_bridge_call_once() -> None:
    payload = {
        "messages": [
            {
                "role": "user",
                "content": "access_token mcp2.abc.def; call filesystem_read for phase6-agent-a.txt",
            }
        ]
    }
    call = _phase6_tool_call(payload)
    assert call is not None
    assert call["function"]["name"] == "tool_call"
    arguments = json.loads(call["function"]["arguments"])
    assert arguments == {
        "name": "mcp__mcp_gateway__filesystem_read",
        "arguments": {"access_token": "mcp2.abc.def", "path": "phase6-agent-a.txt"},
    }
    payload["messages"].append({"role": "tool", "content": "ISOLATION_FILE_SIGNAL_19"})
    assert _phase6_tool_call(payload) is None


@pytest.mark.asyncio
async def test_contract_stub_streams_openai_tool_call_chunks() -> None:
    tool_call = {
        "id": "call-test",
        "type": "function",
        "function": {"name": "tool_call", "arguments": '{"name":"filesystem_read"}'},
    }
    response = _streamed_tool_call(model="stub", tool_call=tool_call)
    body = "".join([chunk async for chunk in response.body_iterator])
    assert '"tool_calls"' in body
    assert '"finish_reason": "tool_calls"' in body
    assert body.endswith("data: [DONE]\n\n")

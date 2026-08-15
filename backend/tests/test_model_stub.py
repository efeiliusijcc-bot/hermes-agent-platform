from __future__ import annotations

import json

import pytest

from app.model_stub import _streamed_tool_call, chat_completions


class Request:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    async def json(self) -> dict[str, object]:
        return self.payload


async def _events(response: object) -> list[dict[str, object]]:
    body_iterator = getattr(response, "body_iterator")
    chunks = [chunk async for chunk in body_iterator]
    lines = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in chunks)
    return [
        json.loads(line[6:])
        for line in lines.splitlines()
        if line.startswith("data: {")
    ]


@pytest.mark.asyncio
async def test_regular_stream_finishes_with_explicit_usage_chunk() -> None:
    response = await chat_completions(
        Request(  # type: ignore[arg-type]
            {"model": "contract", "stream": True, "messages": [{"role": "user", "content": "hello"}]}
        )
    )
    events = await _events(response)
    assert events[-1]["choices"] == []
    assert events[-1]["usage"] == {
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_tokens": 2,
    }


@pytest.mark.asyncio
async def test_tool_stream_finishes_with_explicit_usage_chunk() -> None:
    response = _streamed_tool_call(
        model="contract",
        tool_call={
            "id": "call-1",
            "type": "function",
            "function": {"name": "tool_call", "arguments": "{}"},
        },
    )
    events = await _events(response)
    assert events[-1]["choices"] == []
    assert events[-1]["usage"]["total_tokens"] == 2

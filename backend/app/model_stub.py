from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="OpenAI Contract Test Stub", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": "contract-test-only"}


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(request: Request) -> dict[str, Any] | StreamingResponse:
    payload = await request.json()
    prompt = _flatten_messages(payload.get("messages", []))
    model = str(payload.get("model") or "contract-stub")
    phase3_marker = re.search(r"PHASE3_AGENT_[A-Z0-9_]+", prompt)
    if phase3_marker:
        await asyncio.sleep(0.25)
        content = phase3_marker.group(0)
    elif "OUTPUT_JSON_OK" in prompt:
        content = json.dumps(
            {"summary": f"OUTPUT_JSON_OK:{model}", "recommendations": []},
            separators=(",", ":"),
        )
    elif tool_call := _phase6_tool_call(payload):
        if payload.get("stream"):
            return _streamed_tool_call(model=model, tool_call=tool_call)
        return _completion(model=model, message={"role": "assistant", "content": None, "tool_calls": [tool_call]})
    elif "ISOLATION_FILE_SIGNAL_19" in prompt:
        content = "ISOLATION_FILE_SIGNAL_19 A_MEMORY_SIGNAL_83"
    elif "ISOLATION_DATABASE_SIGNAL" in prompt:
        content = "ISOLATION_DATABASE_SIGNAL 64"
    elif "A_MEMORY_SIGNAL_83" in prompt:
        content = "A_MEMORY_SIGNAL_83"
    else:
        marker_match = re.search(r"[A-Z][A-Z0-9_]{5,}", prompt)
        content = marker_match.group(0) if marker_match else "MODEL_CONTRACT_OK"
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    if payload.get("stream"):
        async def stream() -> AsyncIterator[str]:
            chunks = [
                {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]},
                {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                },
            ]
            for chunk in chunks:
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _phase6_tool_call(payload: dict[str, Any]) -> dict[str, Any] | None:
    messages = payload.get("messages")
    if not isinstance(messages, list) or any(
        isinstance(message, dict) and message.get("role") == "tool" for message in messages
    ):
        return None
    prompt = _flatten_messages(messages)
    token_match = re.search(r"mcp2\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", prompt)
    if token_match is None:
        return None
    if "filesystem_read" in prompt and "phase6-agent-a.txt" in prompt:
        name = "mcp__mcp_gateway__filesystem_read"
        arguments = {"access_token": token_match.group(0), "path": "phase6-agent-a.txt"}
    elif "database_query" in prompt and "phase6_isolation_metrics" in prompt:
        name = "mcp__mcp_gateway__database_query"
        arguments = {
            "access_token": token_match.group(0),
            "sql": "SELECT metric, value FROM phase6_isolation_metrics ORDER BY metric",
        }
    else:
        return None
    return {
        "id": f"call-{uuid.uuid4().hex}",
        "type": "function",
        "function": {
            "name": "tool_call",
            "arguments": json.dumps({"name": name, "arguments": arguments}, separators=(",", ":")),
        },
    }


def _completion(*, model: str, message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _streamed_tool_call(*, model: str, tool_call: dict[str, Any]) -> StreamingResponse:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    async def stream() -> AsyncIterator[str]:
        chunks = [
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            },
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": [{"index": 0, **tool_call}]},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            },
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        ]
        for chunk in chunks:
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


def _flatten_messages(messages: Any) -> str:
    parts: list[str] = []
    if not isinstance(messages, list):
        return ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
    return "\n".join(parts)

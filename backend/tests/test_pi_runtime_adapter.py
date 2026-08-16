from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import configure_mappers

from app.db.models import Agent, AgentRuntime, ExecutionLog, Skill
from app.main import app
from app.runtime.base import RuntimeContext
from app.runtime.pi import PiRuntimeAdapter
from app.schemas.agent import AgentCreate
from app.schemas.runtime import RuntimeCreate, RuntimeUpdate


def test_pi_runtime_migration_and_control_plane_contract() -> None:
    migration = Path("backend/alembic/versions/0012_pi_runtime_adapter.py").read_text()
    for value in (
        "agent_runtimes",
        "runtime_config",
        "runtime_support",
        "runtime_type",
        "runtime_version",
    ):
        assert f'"{value}"' in migration
    configure_mappers()
    assert AgentRuntime.__tablename__ == "agent_runtimes"
    assert "runtime_config" in Agent.__table__.columns
    assert "runtime_support" in Skill.__table__.columns
    assert {"runtime_type", "runtime_id", "runtime_version"}.issubset(
        ExecutionLog.__table__.columns.keys()
    )
    paths = {route.path for route in app.routes}
    assert "/api/runtimes" in paths
    assert "/api/runtimes/{runtime_id}/health" in paths


@pytest.mark.parametrize(
    "secret_config",
    [
        {"api_key": "must-not-be-stored"},
        {"nested": {"access_token": "must-not-be-stored"}},
        {"nested": [{"client_secret": "must-not-be-stored"}]},
        {"authToken": "must-not-be-stored"},
        {"database-password": "must-not-be-stored"},
        {"credentials": {"value": "must-not-be-stored"}},
    ],
)
def test_runtime_and_agent_configs_reject_embedded_secrets(
    secret_config: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="credentials"):
        RuntimeCreate(
            name="Pi",
            type="pi",
            version="1.0.0",
            endpoint="http://pi-runtime:8765",
            config=secret_config,
        )
    with pytest.raises(ValidationError, match="credentials"):
        RuntimeUpdate(config=secret_config)
    with pytest.raises(ValidationError, match="credentials"):
        AgentCreate(
            id="pi-agent",
            name="Pi Agent",
            role="analysis",
            system_prompt="Analyze.",
            runtime_type="pi",
            runtime_config=secret_config,
        )


def test_runtime_config_allows_noncredential_token_settings() -> None:
    config = {"timeout_seconds": 180, "token_limit": 4096, "model": {"max_tokens": 2048}}
    assert RuntimeCreate(
        name="Pi",
        type="pi",
        version="1.0.0",
        endpoint="http://pi-runtime:8765",
        config=config,
    ).config == config


@pytest.mark.asyncio
async def test_pi_adapter_injects_context_and_converts_result_trace() -> None:
    requests: list[tuple[str, str, dict[str, object] | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, payload))
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "healthy", "version": "0.20.0"})
        if request.url.path == "/sessions":
            return httpx.Response(200, json={"session_id": "pi-session-1"})
        if request.url.path.endswith("/execute"):
            return httpx.Response(
                200,
                json={
                    "run_id": "pi-run-1",
                    "status": "completed",
                    "output": "risk report",
                    "usage": {"total_tokens": 42},
                    "trace": [
                        {"type": "model_call", "status": "succeeded", "duration_ms": 12}
                    ],
                },
            )
        if request.url.path == "/runs/pi-run-1/stop":
            return httpx.Response(200, json={"status": "stopped"})
        return httpx.Response(404)

    adapter = PiRuntimeAdapter(
        endpoint="http://pi-runtime:8765",
        version="0.20.0",
        transport=httpx.MockTransport(handler),
    )
    context = RuntimeContext(
        agent_id="pi-agent",
        session_id="platform-session-1",
        workspace="/data/workspaces/pi-agent/platform-session-1",
        memory_namespace="agent:pi-agent:session:test",
        tools=("filesystem", "vector_recall"),
        skills=("write-hb",),
        metadata={"mcp_gateway": "http://mcp-gateway:8090/mcp"},
    )
    health = await adapter.health_check()
    runtime_session = await adapter.create_session(
        agent_id="pi-agent", execution_id="execution-1", context=context
    )
    result = await adapter.execute(
        [{"role": "user", "content": "generate report"}],
        session_id=runtime_session.id,
        model="300b",
        model_adapter="qwen",
        agent_id="pi-agent",
        execution_id="execution-1",
        context=context,
    )
    await adapter.stop("pi-run-1")

    assert health.version == "0.20.0"
    assert runtime_session.id == "pi-session-1"
    assert result.output == "risk report" and result.token_usage == 42
    assert result.trace[0]["type"] == "model_call"
    assert any(method == "POST" and path == "/runs/pi-run-1/stop" for method, path, _ in requests)
    session_payload = next(payload for _, path, payload in requests if path == "/sessions")
    assert session_payload is not None
    assert session_payload["context"]["memory_namespace"] == "agent:pi-agent:session:test"
    assert session_payload["context"]["tools"] == ["filesystem", "vector_recall"]
    assert session_payload["context"]["skills"] == ["write-hb"]
    assert session_payload["context"]["metadata"]["mcp_gateway"] == (
        "http://mcp-gateway:8090/mcp"
    )


@pytest.mark.asyncio
async def test_pi_stream_normalizes_common_event_names() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sessions/pi-session/stream"
        return httpx.Response(
            200,
            text=(
                'data: {"type":"token","text":"hello "}\n\n'
                'data: {"type":"token","text":"world"}\n\n'
                'data: {"type":"done","result":"hello world"}\n\n'
            ),
            headers={"content-type": "text/event-stream"},
        )

    adapter = PiRuntimeAdapter(
        endpoint="http://pi-runtime:8765", transport=httpx.MockTransport(handler)
    )
    events = [
        event
        async for event in adapter.stream(
            [{"role": "user", "content": "hello"}],
            session_id="pi-session",
            model="300b",
            model_adapter="qwen",
            agent_id="pi-agent",
            execution_id="execution-1",
        )
    ]
    assert [item["event"] for item in events] == [
        "message.delta",
        "message.delta",
        "run.completed",
    ]
    assert events[-1]["output"] == "hello world"

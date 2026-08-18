from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import configure_mappers

from app import worker as worker_module
from app.db.models import Agent, AgentRuntime, ExecutionLog, Skill
from app.api import executions as executions_api
from app.api.agents import _complete_execution, _render_mcp_prompt
from app.main import _register_builtin_runtimes, app
from app.runtime.base import RuntimeCancelledError, RuntimeContext, RuntimeHealth
from app.runtime.hermes import HermesRunResult
from app.runtime.pi import PiRuntimeAdapter
from app.schemas.agent import AgentCreate
from app.schemas.runtime import RuntimeCreate, RuntimeUpdate
from app.worker import AgentWorker, _is_runtime_cancellation


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
    assert "/api/executions/{execution_id}/stop" in paths


def test_phase5_deploys_the_official_pi_core_as_an_internal_service() -> None:
    package = json.loads(Path("services/pi-runtime/package.json").read_text())
    compose = Path("docker-compose.yml").read_text()
    dockerfile = Path("services/pi-runtime/Dockerfile").read_text()
    assert package["dependencies"]["@earendil-works/pi-agent-core"] == "0.84.2"
    assert package["dependencies"]["@earendil-works/pi-ai"] == "0.84.2"
    assert "pi-runtime:" in compose
    assert "hermes-agent-platform/pi-runtime:phase5" in compose
    assert "MODEL_GATEWAY_ENDPOINT: http://model-gateway:8080/v1" in compose
    assert "MCP_GATEWAY_ENDPOINT: http://mcp-gateway:8090/mcp" in compose
    pi_service = compose.split("\n  pi-runtime:\n", 1)[1].split("\n  mcp-gateway:\n", 1)[0]
    assert "ports:" not in pi_service
    assert "- pi-runtime-internal" in pi_service
    assert "- platform-internal" not in pi_service
    assert "read_only: true" in pi_service
    assert "node:22.22-alpine" in dockerfile


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


@pytest.mark.asyncio
async def test_pi_adapter_recognizes_explicit_runtime_cancellation() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"run_id": "execution-1", "status": "cancelled"})

    adapter = PiRuntimeAdapter(
        endpoint="http://pi-runtime:8765", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(RuntimeCancelledError, match="cancelled"):
        await adapter.execute(
            [{"role": "user", "content": "cancel me"}],
            session_id="pi-session",
            model="internal-model",
            model_adapter="qwen",
            agent_id="pi-agent",
            execution_id="execution-1",
        )


def test_worker_recognizes_only_the_runtime_cancellation_conflict() -> None:
    assert _is_runtime_cancellation(
        HTTPException(status_code=409, detail="Agent Runtime execution cancelled")
    )
    assert not _is_runtime_cancellation(HTTPException(status_code=409, detail="other conflict"))
    assert not _is_runtime_cancellation(RuntimeError("Agent Runtime execution cancelled"))


@pytest.mark.asyncio
async def test_worker_cancellation_keeps_task_and_session_cancelled() -> None:
    finished_at = datetime.now(timezone.utc)
    task = SimpleNamespace(
        status="running",
        error="old failure",
        finished_at=finished_at,
        session=SimpleNamespace(status="running", finished_at=finished_at),
    )
    session = SimpleNamespace(commit=AsyncMock())
    worker = AgentWorker.__new__(AgentWorker)

    await worker._cancel_task(task, session)

    assert task.status == task.session.status == "cancelled"
    assert task.error is None
    assert task.finished_at is finished_at
    assert task.session.finished_at is finished_at
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_converges_request_validation_failure_to_terminal_state(monkeypatch) -> None:
    task_id = uuid4()
    orchestration_session = SimpleNamespace(
        status="queued",
        input="analyze supplied files",
        memory_session_id="invalid:runtime:session",
        started_at=None,
        finished_at=None,
    )
    task = SimpleNamespace(
        id=task_id,
        agent_id="worker-agent",
        status="pending",
        attempt=0,
        max_attempts=1,
        priority=5,
        worker_id=None,
        started_at=None,
        finished_at=None,
        error=None,
        execution_id=None,
        parent_task_id=None,
        session=orchestration_session,
    )

    class FakeSession:
        commit = AsyncMock()
        rollback = AsyncMock()
        refresh = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def get(self, model, identity):
            return None

    fake_session = FakeSession()
    monkeypatch.setattr(worker_module, "SessionFactory", lambda: fake_session)
    monkeypatch.setattr(worker_module.repository, "get_task", AsyncMock(return_value=task))
    monkeypatch.setattr(
        worker_module.agent_repository,
        "get_agent",
        AsyncMock(return_value=SimpleNamespace(id="worker-agent", status="active")),
    )
    worker = AgentWorker.__new__(AgentWorker)
    worker._publish_result = AsyncMock()

    await worker._execute(task_id, "worker-1")

    assert task.status == orchestration_session.status == "failed"
    assert "session_id" in task.error
    fake_session.rollback.assert_awaited_once()


def test_pi_hides_legacy_mcp_token_while_hermes_keeps_v1_compatibility() -> None:
    secret = "mcp2.execution.signature"
    capabilities = {
        "filesystem": {"mcp_id": "filesystem-mcp", "permission": "read_only"}
    }
    pi_prompt = _render_mcp_prompt(capabilities, secret, runtime_type="pi")
    hermes_prompt = _render_mcp_prompt(capabilities, secret, runtime_type="hermes")
    assert secret not in pi_prompt
    assert "injects the per-execution credential" in pi_prompt
    assert secret in hermes_prompt
    assert "Legacy Hermes MCP access_token" in hermes_prompt
    assert "cap1." not in hermes_prompt


@pytest.mark.asyncio
async def test_completed_result_cannot_overwrite_a_concurrent_cancellation() -> None:
    execution = SimpleNamespace(status="cancelled")
    context = SimpleNamespace(execution=execution)
    session = SimpleNamespace(refresh=AsyncMock())
    with pytest.raises(RuntimeCancelledError, match="cancelled"):
        await _complete_execution(
            context,
            HermesRunResult(output="too late", run_id="run-1", status="completed"),
            session,
        )


@pytest.mark.asyncio
async def test_stop_endpoint_cancels_execution_session_task_and_trace(monkeypatch) -> None:
    execution_id = uuid4()
    runtime_id = uuid4()
    platform_session = SimpleNamespace(status="running", finished_at=None)
    task = SimpleNamespace(status="running", error="old", finished_at=None)
    execution = SimpleNamespace(
        id=execution_id,
        status="running",
        runtime_type="pi",
        runtime_id=None,
        details={"runtime_run_id": str(execution_id)},
        started_at=datetime.now(timezone.utc),
        finished_at=None,
        duration_ms=None,
        error="old",
        session=platform_session,
        agent=SimpleNamespace(runtime_config={}),
    )
    runtime = SimpleNamespace(
        id=runtime_id,
        endpoint="http://pi-runtime:8765",
        version="0.84.2",
        config={},
    )
    adapter = SimpleNamespace(stop=AsyncMock())
    session = SimpleNamespace(commit=AsyncMock())
    cancel_steps = AsyncMock()
    monkeypatch.setattr(
        executions_api.repository, "get_execution", AsyncMock(return_value=execution)
    )
    monkeypatch.setattr(
        executions_api.repository, "get_task_for_execution", AsyncMock(return_value=task)
    )
    monkeypatch.setattr(executions_api.repository, "cancel_running_steps", cancel_steps)
    monkeypatch.setattr(
        executions_api.runtime_repository, "resolve_runtime", AsyncMock(return_value=runtime)
    )
    monkeypatch.setattr(executions_api, "get_runtime_adapter", lambda *args, **kwargs: adapter)

    result = await executions_api.stop_execution(execution_id, session)

    adapter.stop.assert_awaited_once_with(str(execution_id))
    assert result.status == "cancelled" and result.runtime_type == "pi"
    assert execution.status == platform_session.status == task.status == "cancelled"
    assert execution.error is None and task.error is None
    cancel_steps.assert_awaited_once_with(session, execution_id)


@pytest.mark.asyncio
async def test_builtin_runtime_registration_checks_hermes_and_pi_health(monkeypatch) -> None:
    runtimes = [
        SimpleNamespace(status="unknown", id=uuid4()),
        SimpleNamespace(status="unknown", id=uuid4()),
    ]
    ensure = AsyncMock(side_effect=runtimes)
    record = AsyncMock()
    adapters = {
        "hermes": SimpleNamespace(
            health_check=AsyncMock(return_value=RuntimeHealth(status="online", version="0.20.0"))
        ),
        "pi": SimpleNamespace(
            health_check=AsyncMock(return_value=RuntimeHealth(status="online", version="0.84.2"))
        ),
    }
    from app import main as main_module

    monkeypatch.setattr(main_module.runtime_repository, "ensure_runtime", ensure)
    monkeypatch.setattr(main_module.runtime_repository, "record_health", record)
    monkeypatch.setattr(main_module, "_ensure_runtime_feature_profile", AsyncMock())
    monkeypatch.setattr(
        main_module,
        "get_runtime_adapter",
        lambda runtime_type, **kwargs: adapters[runtime_type],
    )

    await _register_builtin_runtimes(SimpleNamespace())

    assert [call.kwargs["runtime_type"] for call in ensure.await_args_list] == ["hermes", "pi"]
    assert [call.kwargs["version"] for call in ensure.await_args_list] == ["0.20.0", "0.84.2"]
    assert record.await_count == 2

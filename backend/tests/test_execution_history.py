from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.executions import _summary, _trace
from app.db.models import ExecutionLog, ExecutionStep
from app.schemas.agent import AgentRunRequest


def test_execution_history_migration_preserves_logs_and_adds_trace_links() -> None:
    migration = (
        Path(__file__).parents[1] / "alembic/versions/0009_execution_history_center.py"
    ).read_text()
    assert 'revision: str = "0009_execution_history"' in migration
    assert 'down_revision: str | None = "0008_production_runtime"' in migration
    assert '"execution_steps"' in migration
    assert '"execution_artifacts"' in migration
    assert 'op.add_column("agent_tasks", sa.Column("execution_id"' in migration
    assert "DELETE FROM execution_logs" not in migration
    assert "DROP TABLE execution_logs" not in migration


def test_execution_models_keep_structured_input_trace_and_artifact_relationships() -> None:
    assert ExecutionLog.__table__.c.input_json.type.__class__.__name__ == "JSONB"
    assert ExecutionLog.__table__.c.output_json.type.__class__.__name__ == "JSONB"
    assert ExecutionStep.__table__.c.input_data.type.__class__.__name__ == "JSONB"
    assert "steps" in ExecutionLog.__mapper__.relationships
    assert "artifacts" in ExecutionLog.__mapper__.relationships


def test_agent_run_request_accepts_schema_parameters_and_bounded_temperature() -> None:
    value = AgentRunRequest(
        input="生成报告",
        session_id="studio-1",
        parameters={"topic": "AI", "period": "2026"},
        temperature=0.3,
    )
    assert value.parameters == {"topic": "AI", "period": "2026"}
    with pytest.raises(ValueError):
        AgentRunRequest(input="test", temperature=2.1)


def test_execution_summary_uses_real_counts_and_never_fabricates_metrics() -> None:
    now = datetime.now(timezone.utc)
    execution = SimpleNamespace(
        id=uuid4(),
        agent_id="history-agent",
        agent=SimpleNamespace(name="History Agent"),
        session_id=uuid4(),
        session=SimpleNamespace(memory_session_id="review"),
        status="succeeded",
        input="生成报告",
        input_json={"task": "生成报告", "parameters": {"topic": "AI"}},
        response_mode="sync",
        priority=None,
        duration_ms=1250,
        token_usage=None,
        retry_of_execution_id=None,
        agent_version_id=None,
        agent_version=None,
        started_at=now,
        finished_at=now,
        artifacts=[SimpleNamespace(id=uuid4())],
        details={
            "skills_loaded": ["report"],
            "mcp_calls": [{"tool": "filesystem_read"}],
            "memory_scope": {"history_messages_loaded": 2},
        },
    )
    summary = _summary(execution)  # type: ignore[arg-type]
    assert summary.task == "生成报告"
    assert summary.skill_count == 1
    assert summary.mcp_call_count == 1
    assert summary.memory_read_count == 2
    assert summary.artifact_count == 1
    assert summary.token_usage is None


def test_trace_contract_uses_persisted_nodes_artifacts_and_missing_token_fields() -> None:
    now = datetime.now(timezone.utc)
    execution_id = uuid4()
    session_id = uuid4()
    artifact_id = uuid4()
    runtime_step = SimpleNamespace(
        id=uuid4(),
        execution_id=execution_id,
        step_key="hermes_runtime",
        sequence=700,
        step_type="runtime",
        step_name="Hermes Runtime",
        status="succeeded",
        input_data={"model": "qwen-offline"},
        output_data={"run_id": "run-1", "status": "completed"},
        error=None,
        latency_ms=321,
        started_at=now,
        finished_at=now,
        created_at=now,
    )
    failed_mcp_step = SimpleNamespace(
        id=uuid4(),
        execution_id=execution_id,
        step_key="mcp_call_0",
        sequence=710,
        step_type="mcp",
        step_name="MCP Call: database.query",
        status="failed",
        input_data={"sql": "select 1"},
        output_data={"mcp_id": "database-mcp"},
        error="connection refused",
        latency_ms=50,
        started_at=now,
        finished_at=now,
        created_at=now,
    )
    artifact = SimpleNamespace(
        id=artifact_id,
        agent_id="trace-agent",
        session_id=session_id,
        filename="result.txt",
        storage_type="filesystem",
        storage_path="trace-agent/session/result.txt",
        content_type="text/plain",
        artifact_type="text",
        runtime_source="platform",
        size_bytes=10,
        sha256="a" * 64,
        created_at=now,
    )
    execution = SimpleNamespace(
        id=execution_id,
        agent_id="trace-agent",
        agent=SimpleNamespace(name="Trace Agent"),
        agent_version_id=None,
        agent_version=None,
        session_id=session_id,
        session=SimpleNamespace(memory_session_id="trace-review"),
        status="failed",
        details={"model": "qwen-offline", "model_adapter": "openai_compatible"},
        token_usage=None,
        duration_ms=500,
        error="connection refused",
        started_at=now,
        finished_at=now,
        steps=[runtime_step, failed_mcp_step],
        artifacts=[artifact],
    )

    trace = _trace(execution)  # type: ignore[arg-type]

    assert trace.execution_id == execution_id
    assert trace.metrics.total_nodes == 2
    assert trace.metrics.failed_nodes == 1
    assert trace.metrics.mcp_calls == 1
    assert trace.metrics.model_calls == 1
    assert trace.metrics.slowest_node_ms == 321
    assert trace.token_usage is None
    assert trace.artifacts[0].sha256 == "a" * 64


@pytest.mark.asyncio
async def test_retry_rejects_an_active_execution() -> None:
    from app.api.executions import retry_execution

    source = SimpleNamespace(status="running")

    class Session:
        pass

    async def get_execution(*args: object, **kwargs: object):
        return source

    from app.api import executions

    original = executions.repository.get_execution
    executions.repository.get_execution = get_execution
    try:
        with pytest.raises(HTTPException) as caught:
            await retry_execution(uuid4(), None, Session(), SimpleNamespace())  # type: ignore[arg-type]
        assert caught.value.status_code == 409
    finally:
        executions.repository.get_execution = original


def test_worker_reuses_queue_execution_instead_of_creating_a_second_record() -> None:
    from app import worker

    source = inspect.getsource(worker.AgentWorker._execute)
    assert "existing_execution=execution" in source
    assert 'response_mode="async"' in source
    assert "retry_attempt=max(0, task.attempt - 1)" in source


def test_sync_execution_does_not_lazy_load_task_relationship_for_retry_attempt() -> None:
    from app.api import agents

    source = inspect.getsource(agents.execute_agent_sync)
    assert "orchestration_session.task" not in source
    assert "retry_attempt=retry_attempt" in source


def test_input_schema_failure_is_recorded_as_a_failed_trace_step() -> None:
    from app.api import agents

    source = inspect.getsource(agents._prepare_agent_execution)
    assert 'step_name="Input Schema Validate"' in source
    assert 'status="failed"' in source
    assert "error=str(exc)" in source


def test_record_step_does_not_reference_an_undefined_preserve_flag() -> None:
    from app.repositories import executions

    source = inspect.getsource(executions.record_step)
    assert "preserve_existing" not in source


def test_cancelling_a_task_also_cancels_its_execution() -> None:
    from app.api import orchestration

    source = inspect.getsource(orchestration.cancel_task)
    assert 'execution.status = "cancelled"' in source
    assert "execution.finished_at = cancelled_at" in source


def test_task_creation_flushes_foreign_key_dependencies_in_order() -> None:
    from app.repositories import orchestration

    source = inspect.getsource(orchestration.create_task)
    session_flush = source.index("session.add(agent_session)")
    execution_flush = source.index("session.add(execution)")
    task_add = source.index("session.add(task)")
    assert session_flush < execution_flush < task_add

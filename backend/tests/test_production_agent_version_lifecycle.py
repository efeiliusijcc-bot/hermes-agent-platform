from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.db.models import Agent, AgentVersion, ExecutionLog
from app.schemas.production import AgentVersionStatusUpdate, AgentVersionUpdate


def test_migration_preserves_rows_and_adds_version_provenance() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic/versions/0010_production_agent_version_lifecycle.py"
    ).read_text()
    assert 'revision: str = "0010_agent_version_lifecycle"' in migration
    assert 'down_revision: str | None = "0009_execution_history"' in migration
    assert '"current_version_id"' in migration
    assert '"agent_version_id"' in migration
    assert "WHEN 'snapshot' THEN 'development'" in migration
    assert "WHEN 'superseded' THEN 'deprecated'" in migration
    assert "execution.started_at >= version.published_at" in migration
    assert "DELETE FROM agent_versions" not in migration
    assert "DELETE FROM execution_logs" not in migration


def test_models_expose_business_and_version_lifecycles() -> None:
    agent_status = next(
        constraint
        for constraint in Agent.__table__.constraints
        if getattr(constraint, "name", None) == "ck_agents_status"
    )
    version_status = next(
        constraint
        for constraint in AgentVersion.__table__.constraints
        if getattr(constraint, "name", None) == "ck_agent_versions_status"
    )
    assert "'active', 'inactive', 'archived'" in str(agent_status.sqltext)
    for value in (
        "development",
        "testing",
        "release_candidate",
        "published",
        "deprecated",
    ):
        assert value in str(version_status.sqltext)
    assert "current_version" in Agent.__mapper__.relationships
    assert "agent_version" in ExecutionLog.__mapper__.relationships


@pytest.mark.asyncio
async def test_version_state_machine_is_deterministic() -> None:
    from app.repositories import production

    version = SimpleNamespace(status="development", updated_at=None)

    class Session:
        async def commit(self) -> None:
            return None

        async def refresh(self, value: object) -> None:
            return None

    await production.transition_agent_version(Session(), version, "testing")  # type: ignore[arg-type]
    await production.transition_agent_version(Session(), version, "release_candidate")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid Agent Version transition"):
        await production.transition_agent_version(Session(), version, "development")  # type: ignore[arg-type]


def test_published_and_deprecated_versions_are_immutable_contract() -> None:
    from app.repositories import production

    source = inspect.getsource(production.update_agent_version)
    assert '{"development", "testing", "release_candidate"}' in source
    assert "published and deprecated Agent versions are immutable" in source
    assert AgentVersionStatusUpdate(status="release_candidate").status == "release_candidate"
    with pytest.raises(ValueError):
        AgentVersionStatusUpdate(status="published")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        AgentVersionUpdate()


def test_version_snapshot_validates_prompt_and_schema_contract() -> None:
    from app.repositories.production import validate_agent_snapshot

    value = {
        "format_version": 1,
        "prompt": {
            "role": "analyst",
            "system_prompt": "verified data only",
            "prompt_template": "analyze {{topic}}",
        },
        "model": {"name": "qwen", "adapter": "qwen", "config": {}},
        "schema": {
            "version": "v2",
            "input_schema": {"type": "object", "properties": {"topic": {"type": "string"}}},
            "output_schema": {},
        },
        "runtime": {"response_mode": "sync"},
        "skill_ids": [],
        "mcp_ids": [],
    }
    validate_agent_snapshot(value)
    value["prompt"]["prompt_template"] = "analyze {{undeclared}}"
    with pytest.raises(ValueError, match="not declared"):
        validate_agent_snapshot(value)


def test_all_execution_paths_capture_or_preserve_version_id() -> None:
    from app.api import agents, executions, orchestration, publications
    from app import worker

    assert "agent_version_id=agent_version_id" in inspect.getsource(agents._prepare_agent_execution)
    assert "agent_version_id=agent.current_version_id" in inspect.getsource(orchestration.submit_task)
    assert "agent_version_id=source.agent_version_id" in inspect.getsource(executions.retry_execution)
    assert "agent_version_id=agent.current_version_id" in inspect.getsource(publications._execute_public_agent)
    assert "execution.agent_version_id" in inspect.getsource(worker.AgentWorker._execute)


def test_version_test_uses_snapshot_without_restoring_live_agent() -> None:
    from app.api import production

    source = inspect.getsource(production.run_agent_version)
    assert "build_version_runtime_agent" in source
    assert "restore_agent_version" not in source
    assert "agent_version_id=value.id" in source


def test_execution_foreign_key_is_nullable_for_unprovable_history() -> None:
    assert ExecutionLog.__table__.c.agent_version_id.nullable is True
    assert Agent.__table__.c.current_version_id.nullable is True
    assert uuid4()  # keep UUID fixtures importable for downstream contract tests

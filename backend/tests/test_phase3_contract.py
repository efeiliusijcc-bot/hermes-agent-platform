from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import selectinload

from app.db.models import AgentTask


def test_phase3_migration_defines_sessions_tasks_artifacts_and_binding_permission() -> None:
    migration = Path("backend/alembic/versions/0006_agent_isolation_concurrency.py").read_text()
    for table in ("agent_sessions", "agent_tasks", "artifacts"):
        assert f'"{table}"' in migration
    assert '"agent_mcp",' in migration and "op.add_column" in migration
    assert '"permission"' in migration


def test_compose_runs_worker_against_isolated_workspace_mount() -> None:
    compose = Path("docker-compose.yml").read_text()
    assert "agent-worker:" in compose
    assert "WORKSPACE_ROOT: /data/workspaces" in compose
    assert "./data/hermes-workspace:/data/workspaces" in compose
    assert 'entrypoint: ["python", "-m", "app.worker"]' in compose
    runtime_block = compose.rsplit("\n  hermes-runtime:\n", 1)[1].split("\n  pi-runtime:\n", 1)[0]
    assert "hermes-workspace" not in runtime_block
    assert "TERMINAL_CWD: /opt/data" in runtime_block


def test_hermes_initializer_uses_current_stateless_runtime_config() -> None:
    initializer = Path("docker/hermes-init.py").read_text()
    assert '"_config_version": 33' in initializer
    assert '"cwd": "/opt/data"' in initializer
    assert '"home_mode": "auto"' in initializer


def test_worker_task_claim_locks_only_task_row_not_eager_session_join() -> None:
    statement = (
        select(AgentTask)
        .options(selectinload(AgentTask.session))
        .where(AgentTask.id.is_not(None))
        .with_for_update(of=AgentTask)
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE OF agent_tasks" in sql
    assert "JOIN agent_sessions" not in sql

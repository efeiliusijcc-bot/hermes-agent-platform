from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import configure_mappers

from app.db.models import Agent, AgentTask, AgentTeam, Workflow, WorkflowRun
from app.main import app
from app.orchestrator import AgentOrchestrator
from app.runtime import get_runtime_adapter, supported_runtime_types
from app.schemas.agent import AgentCreate
from app.schemas.multi_agent import WorkflowCreate


def test_multi_agent_migration_defines_team_workflow_and_task_tree_contracts() -> None:
    migration = Path("backend/alembic/versions/0011_multi_agent_orchestration.py").read_text()
    for table in ("agent_teams", "team_members", "workflows", "workflow_runs"):
        assert f'"{table}"' in migration
    for column in (
        "agent_type",
        "parent_agent_id",
        "runtime_type",
        "parent_task_id",
        "workflow_run_id",
        "node_key",
        "depends_on",
    ):
        assert f'"{column}"' in migration
    assert "waiting_child" in migration
    assert "human_review" in migration


def test_multi_agent_models_configure_and_expose_required_columns() -> None:
    configure_mappers()
    assert {"agent_type", "parent_agent_id", "runtime_type"}.issubset(Agent.__table__.columns.keys())
    assert {"parent_task_id", "workflow_id", "workflow_run_id"}.issubset(
        AgentTask.__table__.columns.keys()
    )
    assert AgentTeam.__tablename__ == "agent_teams"
    assert Workflow.__tablename__ == "workflows"
    assert WorkflowRun.__tablename__ == "workflow_runs"
    assert "delete" not in Workflow.runs.property.cascade
    assert Workflow.runs.property.passive_deletes is True


def test_agent_contract_supports_manager_worker_and_runtime_selection() -> None:
    manager = AgentCreate(
        id="manager-agent",
        name="Manager",
        role="manager",
        system_prompt="Coordinate the team.",
        agent_type="manager",
        runtime_type="pi",
    )
    worker = AgentCreate(
        id="worker-agent",
        name="Worker",
        role="analyst",
        system_prompt="Analyze evidence.",
        parent_agent_id=manager.id,
    )
    assert manager.agent_type == "manager"
    assert manager.runtime_type == "pi"
    assert worker.parent_agent_id == manager.id
    assert worker.runtime_type == "hermes"


def test_workflow_schema_accepts_dag_and_rejects_cycles() -> None:
    valid = WorkflowCreate(
        team_id=uuid4(),
        name="Research",
        status="active",
        nodes=[
            {"key": "research", "type": "agent", "name": "Research", "agent_id": "worker-agent"},
            {
                "key": "review",
                "type": "human_approval",
                "name": "Review",
                "depends_on": ["research"],
            },
        ],
    )
    assert valid.nodes[1].depends_on == ["research"]
    with pytest.raises(ValidationError, match="cycle"):
        WorkflowCreate(
            team_id=uuid4(),
            name="Cycle",
            nodes=[
                {"key": "a", "type": "agent", "name": "A", "agent_id": "agent-a", "depends_on": ["b"]},
                {"key": "b", "type": "agent", "name": "B", "agent_id": "agent-b", "depends_on": ["a"]},
            ],
        )


@pytest.mark.asyncio
async def test_runtime_interface_supports_hermes_and_pi_without_direct_dependency() -> None:
    assert supported_runtime_types() == ("hermes", "pi")
    hermes = get_runtime_adapter("hermes")
    runtime_session = await hermes.create_session(
        agent_id="worker-agent", execution_id="execution-1"
    )
    assert runtime_session.id == "execution-1"
    assert runtime_session.runtime_type == "hermes"
    assert get_runtime_adapter("pi").runtime_type == "pi"
    with pytest.raises(ValueError, match="unsupported runtime"):
        get_runtime_adapter("unknown")


def test_manager_aggregation_prompt_preserves_agent_provenance() -> None:
    children = [
        SimpleNamespace(
            node_key="market",
            agent_id="market-agent",
            session=SimpleNamespace(output="market result"),
        ),
        SimpleNamespace(
            node_key="competition",
            agent_id="competition-agent",
            session=SimpleNamespace(output="competition result"),
        ),
    ]
    prompt = AgentOrchestrator._manager_prompt("analyze energy", children)  # type: ignore[arg-type]
    assert "原始任务：analyze energy" in prompt
    assert "market-agent" in prompt and "market result" in prompt
    assert "competition-agent" in prompt and "competition result" in prompt


def test_multi_agent_control_plane_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/agent-teams" in paths
    assert "/api/workflows" in paths
    assert "/api/workflows/{workflow_id}/runs" in paths
    assert "/api/workflow-runs/{run_id}/tasks" in paths
    assert "/api/tasks/{task_id}/approval" in paths
    assert "/api/agent-messages" in paths

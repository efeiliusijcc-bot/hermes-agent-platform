"""add Multi-Agent teams, workflows, task trees, and runtime sessions

Revision ID: 0011_multi_agent_orchestration
Revises: 0010_agent_version_lifecycle
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0011_multi_agent_orchestration"
down_revision: str | None = "0010_agent_version_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_skill",
        sa.Column("version", sa.String(length=64), nullable=False, server_default="latest"),
    )

    op.add_column(
        "agents",
        sa.Column("agent_type", sa.String(length=32), nullable=False, server_default="worker"),
    )
    op.add_column("agents", sa.Column("parent_agent_id", sa.String(length=64), nullable=True))
    op.add_column(
        "agents",
        sa.Column("runtime_type", sa.String(length=32), nullable=False, server_default="hermes"),
    )
    op.create_check_constraint(
        "ck_agents_agent_type", "agents", "agent_type IN ('manager', 'worker')"
    )
    op.create_check_constraint(
        "ck_agents_runtime_type", "agents", "runtime_type IN ('hermes', 'pi')"
    )
    op.create_foreign_key(
        "fk_agents_parent_agent_id",
        "agents",
        "agents",
        ["parent_agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agents_parent_agent_id", "agents", ["parent_agent_id"])

    op.add_column(
        "agent_sessions",
        sa.Column("runtime_type", sa.String(length=32), nullable=False, server_default="hermes"),
    )
    op.add_column(
        "agent_sessions", sa.Column("runtime_session_id", sa.String(length=255), nullable=True)
    )
    op.create_check_constraint(
        "ck_agent_sessions_runtime_type",
        "agent_sessions",
        "runtime_type IN ('hermes', 'pi')",
    )

    op.create_table(
        "agent_teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_agent_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'archived')", name="ck_agent_teams_status"
        ),
        sa.ForeignKeyConstraint(
            ["owner_agent_id"], ["agents.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_agent_teams_name"),
    )
    op.create_index("ix_agent_teams_owner_agent_id", "agent_teams", ["owner_agent_id"])

    op.create_table(
        "team_members",
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=128), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("priority BETWEEN 0 AND 100", name="ck_team_members_priority"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("team_id", "agent_id"),
    )
    op.create_index("ix_team_members_agent_id", "team_members", ["agent_id"])

    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'inactive', 'archived')", name="ck_workflows_status"
        ),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "name", name="uq_workflows_team_name"),
    )
    op.create_index("ix_workflows_team_id", "workflows", ["team_id"])

    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'human_review', 'succeeded', 'failed', 'cancelled')",
            name="ck_workflow_runs_status",
        ),
        sa.ForeignKeyConstraint(["team_id"], ["agent_teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_runs_team_id", "workflow_runs", ["team_id"])
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])

    op.drop_constraint("ck_agent_tasks_status", "agent_tasks", type_="check")
    op.create_check_constraint(
        "ck_agent_tasks_status",
        "agent_tasks",
        "status IN ('pending', 'running', 'waiting_child', 'human_review', 'retrying', 'succeeded', 'failed', 'cancelled')",
    )
    op.add_column(
        "agent_tasks",
        sa.Column("parent_task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "agent_tasks", sa.Column("workflow_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "agent_tasks",
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("agent_tasks", sa.Column("node_key", sa.String(length=128), nullable=True))
    op.add_column(
        "agent_tasks",
        sa.Column("node_type", sa.String(length=32), nullable=False, server_default="agent"),
    )
    op.add_column(
        "agent_tasks",
        sa.Column(
            "depends_on",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "agent_tasks",
        sa.Column(
            "input_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "agent_tasks",
        sa.Column(
            "output_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_foreign_key(
        "fk_agent_tasks_parent_task_id",
        "agent_tasks",
        "agent_tasks",
        ["parent_task_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_agent_tasks_workflow_id",
        "agent_tasks",
        "workflows",
        ["workflow_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_agent_tasks_workflow_run_id",
        "agent_tasks",
        "workflow_runs",
        ["workflow_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_agent_tasks_parent_task_id", "agent_tasks", ["parent_task_id"])
    op.create_index("ix_agent_tasks_workflow_run_id", "agent_tasks", ["workflow_run_id"])
    op.create_index(
        "uq_agent_tasks_workflow_run_node",
        "agent_tasks",
        ["workflow_run_id", "node_key"],
        unique=True,
        postgresql_where=sa.text("node_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_tasks_workflow_run_node", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_workflow_run_id", table_name="agent_tasks")
    op.drop_index("ix_agent_tasks_parent_task_id", table_name="agent_tasks")
    op.drop_constraint("fk_agent_tasks_workflow_run_id", "agent_tasks", type_="foreignkey")
    op.drop_constraint("fk_agent_tasks_workflow_id", "agent_tasks", type_="foreignkey")
    op.drop_constraint("fk_agent_tasks_parent_task_id", "agent_tasks", type_="foreignkey")
    for column in (
        "output_data",
        "input_data",
        "depends_on",
        "node_type",
        "node_key",
        "workflow_run_id",
        "workflow_id",
        "parent_task_id",
    ):
        op.drop_column("agent_tasks", column)
    op.drop_constraint("ck_agent_tasks_status", "agent_tasks", type_="check")
    op.create_check_constraint(
        "ck_agent_tasks_status",
        "agent_tasks",
        "status IN ('pending', 'running', 'retrying', 'succeeded', 'failed', 'cancelled')",
    )

    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_workflow_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_team_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_workflows_team_id", table_name="workflows")
    op.drop_table("workflows")
    op.drop_index("ix_team_members_agent_id", table_name="team_members")
    op.drop_table("team_members")
    op.drop_index("ix_agent_teams_owner_agent_id", table_name="agent_teams")
    op.drop_table("agent_teams")

    op.drop_constraint("ck_agent_sessions_runtime_type", "agent_sessions", type_="check")
    op.drop_column("agent_sessions", "runtime_session_id")
    op.drop_column("agent_sessions", "runtime_type")

    op.drop_index("ix_agents_parent_agent_id", table_name="agents")
    op.drop_constraint("fk_agents_parent_agent_id", "agents", type_="foreignkey")
    op.drop_constraint("ck_agents_runtime_type", "agents", type_="check")
    op.drop_constraint("ck_agents_agent_type", "agents", type_="check")
    op.drop_column("agents", "runtime_type")
    op.drop_column("agents", "parent_agent_id")
    op.drop_column("agents", "agent_type")
    op.drop_column("agent_skill", "version")

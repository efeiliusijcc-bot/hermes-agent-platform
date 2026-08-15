"""add Phase 3 Agent isolation and concurrency records

Revision ID: 0006_agent_isolation
Revises: 0005_agent_gateway_contract
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0006_agent_isolation"
down_revision: str | None = "0005_agent_gateway_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_mcp",
        sa.Column("permission", sa.String(length=32), nullable=False, server_default="read_only"),
    )
    op.create_check_constraint("ck_agent_mcp_permission", "agent_mcp", "permission = 'read_only'")

    op.create_table(
        "agent_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("memory_session_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("workspace_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_agent_sessions_status",
        ),
    )
    op.create_index("ix_agent_sessions_agent_created", "agent_sessions", ["agent_id", "created_at"])
    op.create_index("ix_agent_sessions_status", "agent_sessions", ["status"])

    op.add_column(
        "execution_logs",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_execution_logs_session_id",
        "execution_logs",
        "agent_sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_execution_logs_session_id", "execution_logs", ["session_id"])

    op.create_table(
        "agent_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'retrying', 'succeeded', 'failed', 'cancelled')",
            name="ck_agent_tasks_status",
        ),
        sa.CheckConstraint("priority BETWEEN 0 AND 9", name="ck_agent_tasks_priority"),
        sa.CheckConstraint("attempt >= 0 AND max_attempts >= 1", name="ck_agent_tasks_attempts"),
    )
    op.create_index("ix_agent_tasks_status_priority", "agent_tasks", ["status", "priority", "created_at"])
    op.create_index("ix_agent_tasks_agent_created", "agent_tasks", ["agent_id", "created_at"])

    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("path", sa.Text(), nullable=False, unique=True),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("session_id", "filename", name="uq_artifacts_session_filename"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_artifacts_size"),
    )
    op.create_index("ix_artifacts_agent_created", "artifacts", ["agent_id", "created_at"])
    op.create_index("ix_artifacts_session_id", "artifacts", ["session_id"])


def downgrade() -> None:
    op.drop_table("artifacts")
    op.drop_table("agent_tasks")
    op.drop_index("ix_execution_logs_session_id", table_name="execution_logs")
    op.drop_constraint("fk_execution_logs_session_id", "execution_logs", type_="foreignkey")
    op.drop_column("execution_logs", "session_id")
    op.drop_table("agent_sessions")
    op.drop_constraint("ck_agent_mcp_permission", "agent_mcp", type_="check")
    op.drop_column("agent_mcp", "permission")

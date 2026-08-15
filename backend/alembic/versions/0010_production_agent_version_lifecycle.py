"""add production Agent Version lifecycle and execution provenance

Revision ID: 0010_agent_version_lifecycle
Revises: 0009_execution_history
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0010_agent_version_lifecycle"
down_revision: str | None = "0009_execution_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_agents_status", "agents", type_="check")
    op.execute(
        """
        UPDATE agents
        SET status = CASE
            WHEN status = 'archived' THEN 'archived'
            WHEN status IN ('suspended', 'disabled') THEN 'inactive'
            ELSE 'active'
        END
        """
    )
    op.create_check_constraint(
        "ck_agents_status", "agents", "status IN ('active', 'inactive', 'archived')"
    )

    op.add_column(
        "agent_versions",
        sa.Column("created_by", sa.String(length=255), nullable=False, server_default="system"),
    )
    op.add_column(
        "agent_versions",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "agent_versions",
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_constraint("ck_agent_versions_status", "agent_versions", type_="check")
    op.execute(
        """
        UPDATE agent_versions
        SET status = CASE status
            WHEN 'snapshot' THEN 'development'
            WHEN 'superseded' THEN 'deprecated'
            ELSE status
        END,
        deprecated_at = CASE
            WHEN status = 'superseded' THEN COALESCE(published_at, created_at)
            ELSE deprecated_at
        END,
        updated_at = COALESCE(published_at, created_at)
        """
    )
    op.create_check_constraint(
        "ck_agent_versions_status",
        "agent_versions",
        "status IN ('development', 'testing', 'release_candidate', 'published', 'deprecated')",
    )
    op.create_index(
        "uq_agent_versions_one_published",
        "agent_versions",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )

    op.add_column(
        "agents",
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agents_current_version_id",
        "agents",
        "agent_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agents_current_version_id", "agents", ["current_version_id"])
    op.execute(
        """
        UPDATE agents agent
        SET current_version_id = (
            SELECT version.id
            FROM agent_versions version
            WHERE version.agent_id = agent.id
              AND version.status = 'published'
            ORDER BY version.published_at DESC NULLS LAST, version.created_at DESC, version.id DESC
            LIMIT 1
        )
        WHERE EXISTS (
            SELECT 1 FROM agent_versions version
            WHERE version.agent_id = agent.id AND version.status = 'published'
        )
        """
    )

    op.add_column(
        "execution_logs",
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_execution_logs_agent_version_id",
        "execution_logs",
        "agent_versions",
        ["agent_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_execution_logs_agent_version_id", "execution_logs", ["agent_version_id"])
    # Existing executions are attributed only when the current published
    # version had already been published at execution time. Older rows remain
    # NULL because assigning a historical version without evidence would lie.
    op.execute(
        """
        UPDATE execution_logs execution
        SET agent_version_id = agent.current_version_id
        FROM agents agent
        JOIN agent_versions version ON version.id = agent.current_version_id
        WHERE execution.agent_id = agent.id
          AND execution.agent_version_id IS NULL
          AND version.published_at IS NOT NULL
          AND execution.started_at >= version.published_at
        """
    )


def downgrade() -> None:
    op.drop_index("ix_execution_logs_agent_version_id", table_name="execution_logs")
    op.drop_constraint("fk_execution_logs_agent_version_id", "execution_logs", type_="foreignkey")
    op.drop_column("execution_logs", "agent_version_id")

    op.drop_index("ix_agents_current_version_id", table_name="agents")
    op.drop_constraint("fk_agents_current_version_id", "agents", type_="foreignkey")
    op.drop_column("agents", "current_version_id")

    op.drop_index("uq_agent_versions_one_published", table_name="agent_versions")
    op.drop_constraint("ck_agent_versions_status", "agent_versions", type_="check")
    op.execute(
        """
        UPDATE agent_versions
        SET status = CASE status
            WHEN 'development' THEN 'snapshot'
            WHEN 'testing' THEN 'snapshot'
            WHEN 'release_candidate' THEN 'snapshot'
            WHEN 'deprecated' THEN 'superseded'
            ELSE status
        END
        """
    )
    op.create_check_constraint(
        "ck_agent_versions_status",
        "agent_versions",
        "status IN ('snapshot', 'published', 'superseded')",
    )
    op.drop_column("agent_versions", "deprecated_at")
    op.drop_column("agent_versions", "updated_at")
    op.drop_column("agent_versions", "created_by")

    op.drop_constraint("ck_agents_status", "agents", type_="check")
    op.execute(
        """
        UPDATE agents
        SET status = CASE
            WHEN status = 'archived' THEN 'archived'
            WHEN status = 'inactive' THEN 'suspended'
            ELSE 'testing'
        END
        """
    )
    op.create_check_constraint(
        "ck_agents_status",
        "agents",
        "status IN ('draft', 'testing', 'published', 'suspended', 'archived')",
    )

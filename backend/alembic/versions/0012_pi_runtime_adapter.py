"""add Pi Runtime registry, compatibility, and execution provenance

Revision ID: 0012_pi_runtime_adapter
Revises: 0011_multi_agent_orchestration
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0012_pi_runtime_adapter"
down_revision: str | None = "0011_multi_agent_orchestration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runtimes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column(
            "config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("type IN ('hermes', 'pi')", name="ck_agent_runtimes_type"),
        sa.CheckConstraint(
            "status IN ('unknown', 'online', 'offline', 'disabled')",
            name="ck_agent_runtimes_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_agent_runtimes_name"),
    )
    op.create_index("ix_agent_runtimes_type_status", "agent_runtimes", ["type", "status"])

    op.add_column(
        "agents",
        sa.Column(
            "runtime_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "skills",
        sa.Column(
            "runtime_support",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[\"hermes\"]'::jsonb"),
        ),
    )
    op.add_column(
        "execution_logs",
        sa.Column("runtime_type", sa.String(length=32), nullable=False, server_default="hermes"),
    )
    op.add_column(
        "execution_logs",
        sa.Column("runtime_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "execution_logs", sa.Column("runtime_version", sa.String(length=64), nullable=True)
    )
    op.create_check_constraint(
        "ck_execution_logs_runtime_type",
        "execution_logs",
        "runtime_type IN ('hermes', 'pi')",
    )
    op.create_foreign_key(
        "fk_execution_logs_runtime_id",
        "execution_logs",
        "agent_runtimes",
        ["runtime_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_execution_logs_runtime_type", "execution_logs", ["runtime_type"])
    op.create_index("ix_execution_logs_runtime_id", "execution_logs", ["runtime_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_logs_runtime_id", table_name="execution_logs")
    op.drop_index("ix_execution_logs_runtime_type", table_name="execution_logs")
    op.drop_constraint("fk_execution_logs_runtime_id", "execution_logs", type_="foreignkey")
    op.drop_constraint("ck_execution_logs_runtime_type", "execution_logs", type_="check")
    op.drop_column("execution_logs", "runtime_version")
    op.drop_column("execution_logs", "runtime_id")
    op.drop_column("execution_logs", "runtime_type")
    op.drop_column("skills", "runtime_support")
    op.drop_column("agents", "runtime_config")
    op.drop_index("ix_agent_runtimes_type_status", table_name="agent_runtimes")
    op.drop_table("agent_runtimes")

"""add capability bindings, invocations, and snapshot v2 metadata

Revision ID: 0016_capability_binding_and_invocation
Revises: 0015_general_capability_registry
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0016_capability_binding_and_invocation"
down_revision: str | None = "0015_general_capability_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "agent_versions",
        sa.Column("snapshot_format_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("agent_versions", sa.Column("resolution_digest", sa.String(71)))
    op.create_index("ix_agent_versions_snapshot_format_version", "agent_versions", ["snapshot_format_version"])
    op.create_table(
        "agent_capability_bindings",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("agent_version_id", UUID, sa.ForeignKey("agent_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_alias", sa.String(128), nullable=False),
        sa.Column("capability_version_id", UUID, sa.ForeignKey("capability_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("implementation_mode", sa.String(32), nullable=False, server_default="PINNED"),
        sa.Column("implementation_id", UUID, sa.ForeignKey("capability_implementations.id", ondelete="RESTRICT")),
        sa.Column("resource_scope_revision_id", UUID, sa.ForeignKey("resource_scope_revisions.id", ondelete="RESTRICT")),
        sa.Column("parameter_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("quota_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("approval_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="direct"),
        sa.Column("source_ref_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("agent_version_id", "tool_alias", name="uq_agent_capability_bindings_alias"),
        sa.CheckConstraint(
            "implementation_mode IN ('PINNED', 'DEFAULT_PRIORITY')",
            name="ck_agent_capability_bindings_mode",
        ),
        sa.CheckConstraint(
            "source_type IN ('direct', 'skill', 'workflow', 'template', 'legacy')",
            name="ck_agent_capability_bindings_source",
        ),
    )
    op.create_table(
        "capability_invocations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("execution_id", UUID, sa.ForeignKey("execution_logs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(64), sa.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("agent_version_id", UUID, sa.ForeignKey("agent_versions.id", ondelete="SET NULL")),
        sa.Column("binding_id", UUID, sa.ForeignKey("agent_capability_bindings.id", ondelete="SET NULL")),
        sa.Column("capability_key", sa.String(255), nullable=False),
        sa.Column("capability_version", sa.String(64), nullable=False),
        sa.Column("tool_alias", sa.String(128), nullable=False),
        sa.Column("connector_instance_revision_id", UUID, sa.ForeignKey("connector_instance_revisions.id", ondelete="SET NULL")),
        sa.Column("resource_scope_revision_id", UUID, sa.ForeignKey("resource_scope_revisions.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("input_summary", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_summary", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_code", sa.String(64)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'DENIED')",
            name="ck_capability_invocations_status",
        ),
    )
    op.create_table(
        "connector_health_checks",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("connector_instance_revision_id", UUID, sa.ForeignKey("connector_instance_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_id", UUID, sa.ForeignKey("connector_operations.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_capability_bindings_agent_version", "agent_capability_bindings", ["agent_version_id"])
    op.create_index("ix_capability_invocations_execution", "capability_invocations", ["execution_id", "created_at"])
    op.create_index("ix_capability_invocations_agent", "capability_invocations", ["agent_id", "created_at"])
    op.create_index("ix_capability_invocations_status", "capability_invocations", ["status"])
    op.create_index("ix_connector_health_checks_revision", "connector_health_checks", ["connector_instance_revision_id", "checked_at"])


def downgrade() -> None:
    op.drop_table("connector_health_checks")
    op.drop_table("capability_invocations")
    op.drop_table("agent_capability_bindings")
    op.drop_index("ix_agent_versions_snapshot_format_version", table_name="agent_versions")
    op.drop_column("agent_versions", "resolution_digest")
    op.drop_column("agent_versions", "snapshot_format_version")

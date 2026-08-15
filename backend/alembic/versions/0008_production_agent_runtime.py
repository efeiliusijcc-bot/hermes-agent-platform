"""add production Agent lifecycle, authorization, audit, metrics, and versions

Revision ID: 0008_production_runtime
Revises: 0007_schema_storage
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008_production_runtime"
down_revision: str | None = "0007_schema_storage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Publication is the authoritative source for already published Agents.  The
    # fallback mappings retain the intent of the three-state legacy lifecycle.
    op.drop_constraint("ck_agents_status", "agents", type_="check")
    op.execute(
        """
        UPDATE agents
        SET status = CASE
            WHEN EXISTS (
                SELECT 1 FROM agent_publications publication
                WHERE publication.agent_id = agents.id AND publication.status = 'published'
            ) THEN 'published'
            WHEN status = 'active' THEN 'testing'
            WHEN status = 'disabled' THEN 'suspended'
            ELSE 'draft'
        END
        """
    )
    op.create_check_constraint(
        "ck_agents_status",
        "agents",
        "status IN ('draft', 'testing', 'published', 'suspended', 'archived')",
    )

    op.create_table(
        "api_clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_api_clients_name"),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'revoked')", name="ck_api_clients_status"
        ),
        sa.CheckConstraint("rate_limit_per_minute > 0", name="ck_api_clients_rate_limit"),
    )
    op.create_index("ix_api_clients_status", "api_clients", ["status"])

    op.create_table(
        "agent_api_clients",
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("permission", sa.String(length=32), nullable=False, server_default="invoke"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], ["api_clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("client_id", "agent_id"),
        sa.CheckConstraint("permission = 'invoke'", name="ck_agent_api_clients_permission"),
    )
    op.create_index("ix_agent_api_clients_agent_id", "agent_api_clients", ["agent_id"])

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], ["api_clients.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        sa.CheckConstraint("status IN ('active', 'revoked')", name="ck_api_keys_status"),
    )
    op.create_index("ix_api_keys_client_status", "api_keys", ["client_id", "status"])

    # Preserve already issued Phase 2 keys without ever recovering or logging
    # their plaintext.  They become ordinary client keys with an invoke binding.
    op.execute(
        """
        INSERT INTO api_clients (id, name, owner, status, rate_limit_per_minute)
        SELECT md5('phase4-client:' || publication.agent_id)::uuid,
               'legacy-' || publication.agent_id,
               'legacy-publication',
               'active',
               60
        FROM agent_publications publication
        WHERE publication.api_key_hash IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO agent_api_clients (client_id, agent_id, permission)
        SELECT md5('phase4-client:' || publication.agent_id)::uuid,
               publication.agent_id,
               'invoke'
        FROM agent_publications publication
        WHERE publication.api_key_hash IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO api_keys (id, client_id, name, key_hash, prefix, status, last_used_at)
        SELECT md5('phase4-key:' || publication.agent_id)::uuid,
               md5('phase4-client:' || publication.agent_id)::uuid,
               'legacy-publication-key',
               publication.api_key_hash,
               COALESCE(publication.api_key_prefix, 'legacy'),
               'active',
               publication.last_called_at
        FROM agent_publications publication
        WHERE publication.api_key_hash IS NOT NULL
        """
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("token_usage", sa.BigInteger(), nullable=True),
        sa.Column("mcp_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["client_id"], ["api_clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["api_key_id"], ["api_keys.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("request_id", name="uq_audit_logs_request_id"),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'rejected')", name="ck_audit_logs_status"
        ),
        sa.CheckConstraint("latency_ms >= 0", name="ck_audit_logs_latency"),
        sa.CheckConstraint(
            "token_usage IS NULL OR token_usage >= 0", name="ck_audit_logs_token_usage"
        ),
        sa.CheckConstraint("mcp_call_count >= 0", name="ck_audit_logs_mcp_calls"),
    )
    op.create_index("ix_audit_logs_agent_created", "audit_logs", ["agent_id", "created_at"])
    op.create_index("ix_audit_logs_client_created", "audit_logs", ["client_id", "created_at"])
    op.create_index("ix_audit_logs_status_created", "audit_logs", ["status", "created_at"])

    op.create_table(
        "agent_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("call_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_latency_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_token_usage", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("token_usage_observed_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("mcp_call_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("agent_id", "metric_date", name="uq_agent_metrics_agent_date"),
        sa.CheckConstraint(
            "call_count >= 0 AND success_count >= 0 AND failure_count >= 0",
            name="ck_agent_metrics_call_counts",
        ),
        sa.CheckConstraint(
            "total_latency_ms >= 0 AND total_token_usage >= 0 AND "
            "token_usage_observed_count >= 0 AND mcp_call_count >= 0",
            name="ck_agent_metrics_totals",
        ),
    )
    op.create_index("ix_agent_metrics_date", "agent_metrics", ["metric_date"])

    op.create_table(
        "agent_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="snapshot"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
        sa.CheckConstraint(
            "status IN ('snapshot', 'published', 'superseded')",
            name="ck_agent_versions_status",
        ),
    )
    op.create_index("ix_agent_versions_agent_created", "agent_versions", ["agent_id", "created_at"])


def downgrade() -> None:
    op.drop_table("agent_versions")
    op.drop_table("agent_metrics")
    op.drop_table("audit_logs")
    op.drop_table("api_keys")
    op.drop_table("agent_api_clients")
    op.drop_table("api_clients")
    op.drop_constraint("ck_agents_status", "agents", type_="check")
    op.execute(
        """
        UPDATE agents SET status = CASE
            WHEN status IN ('testing', 'published') THEN 'active'
            WHEN status IN ('suspended', 'archived') THEN 'disabled'
            ELSE 'draft'
        END
        """
    )
    op.create_check_constraint(
        "ck_agents_status", "agents", "status IN ('draft', 'active', 'disabled')"
    )

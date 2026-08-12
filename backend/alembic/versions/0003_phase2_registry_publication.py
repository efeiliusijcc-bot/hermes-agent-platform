"""add Phase 2 registry, schemas, and public Agent publication

Revision ID: 0003_phase2_registry_publication
Revises: 0002_knowledge_service
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_phase2_registry_publication"
down_revision: str | None = "0002_knowledge_service"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    empty_json = sa.text("'{}'::jsonb")
    op.add_column("agents", sa.Column("input_schema", postgresql.JSONB(), nullable=False, server_default=empty_json))
    op.add_column("agents", sa.Column("output_schema", postgresql.JSONB(), nullable=False, server_default=empty_json))

    op.add_column("skills", sa.Column("version", sa.String(length=64), nullable=False, server_default="0.0.0"))
    op.add_column("skills", sa.Column("manifest", postgresql.JSONB(), nullable=False, server_default=empty_json))
    op.add_column("skills", sa.Column("package_sha256", sa.String(length=64), nullable=True))
    op.add_column("skills", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_unique_constraint("uq_skills_package_sha256", "skills", ["package_sha256"])

    op.add_column("mcp_servers", sa.Column("permission", sa.String(length=32), nullable=False, server_default="read_only"))
    op.add_column("mcp_servers", sa.Column("status", sa.String(length=32), nullable=False, server_default="unknown"))
    op.add_column("mcp_servers", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_check_constraint("ck_mcp_servers_permission", "mcp_servers", "permission = 'read_only'")
    op.create_check_constraint("ck_mcp_servers_status", "mcp_servers", "status IN ('unknown', 'online', 'offline')")
    op.create_index("ix_mcp_servers_status", "mcp_servers", ["status"])

    op.create_table(
        "agent_publications",
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("api_key_hash", sa.String(length=64), nullable=True),
        sa.Column("api_key_prefix", sa.String(length=16), nullable=True),
        sa.Column("call_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id"),
        sa.UniqueConstraint("api_key_hash", name="uq_agent_publications_api_key_hash"),
        sa.CheckConstraint(
            "status IN ('draft', 'testing', 'published', 'disabled')",
            name="ck_agent_publications_status",
        ),
    )
    op.create_index("ix_agent_publications_status", "agent_publications", ["status"])


def downgrade() -> None:
    op.drop_table("agent_publications")
    op.drop_index("ix_mcp_servers_status", table_name="mcp_servers")
    op.drop_constraint("ck_mcp_servers_status", "mcp_servers", type_="check")
    op.drop_constraint("ck_mcp_servers_permission", "mcp_servers", type_="check")
    op.drop_column("mcp_servers", "updated_at")
    op.drop_column("mcp_servers", "status")
    op.drop_column("mcp_servers", "permission")
    op.drop_constraint("uq_skills_package_sha256", "skills", type_="unique")
    op.drop_column("skills", "updated_at")
    op.drop_column("skills", "package_sha256")
    op.drop_column("skills", "manifest")
    op.drop_column("skills", "version")
    op.drop_column("agents", "output_schema")
    op.drop_column("agents", "input_schema")

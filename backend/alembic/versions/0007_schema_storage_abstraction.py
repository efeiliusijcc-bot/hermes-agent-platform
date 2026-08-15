"""add Schema versions and storage abstractions

Revision ID: 0007_schema_storage
Revises: 0006_agent_isolation
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_schema_storage"
down_revision: str | None = "0006_agent_isolation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    empty_json = sa.text("'{}'::jsonb")
    op.create_table(
        "agent_schema_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("input_schema", postgresql.JSONB(), nullable=False, server_default=empty_json),
        sa.Column("output_schema", postgresql.JSONB(), nullable=False, server_default=empty_json),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_schema_versions_agent_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'testing', 'published', 'deprecated', 'disabled')",
            name="ck_agent_schema_versions_status",
        ),
    )
    op.create_index("ix_agent_schema_versions_agent_status", "agent_schema_versions", ["agent_id", "status"])
    op.execute(
        """
        INSERT INTO agent_schema_versions (id, agent_id, version, input_schema, output_schema, status, published_at)
        SELECT md5('schema:' || agents.id)::uuid, agents.id, 'v1', agents.input_schema, agents.output_schema,
               CASE WHEN publications.status = 'published' THEN 'published' ELSE 'draft' END,
               CASE WHEN publications.status = 'published' THEN now() ELSE NULL END
        FROM agents
        LEFT JOIN agent_publications publications ON publications.agent_id = agents.id
        """
    )

    op.create_table(
        "agent_api_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("api_version", sa.String(length=32), nullable=False),
        sa.Column("schema_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["schema_version_id"], ["agent_schema_versions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("agent_id", "api_version", name="uq_agent_api_versions_agent_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'testing', 'published', 'deprecated', 'disabled')",
            name="ck_agent_api_versions_status",
        ),
    )
    op.create_index("ix_agent_api_versions_agent_status", "agent_api_versions", ["agent_id", "status"])
    op.execute(
        """
        INSERT INTO agent_api_versions (id, agent_id, api_version, schema_version_id, status, published_at)
        SELECT md5('api:' || agents.id)::uuid, agents.id, 'v1', versions.id,
               CASE WHEN publications.status = 'published' THEN 'published' ELSE 'draft' END,
               CASE WHEN publications.status = 'published' THEN now() ELSE NULL END
        FROM agents
        JOIN agent_schema_versions versions ON versions.agent_id = agents.id AND versions.version = 'v1'
        LEFT JOIN agent_publications publications ON publications.agent_id = agents.id
        """
    )

    op.add_column("artifacts", sa.Column("storage_type", sa.String(length=32), nullable=True))
    op.add_column("artifacts", sa.Column("storage_path", sa.Text(), nullable=True))
    op.execute("UPDATE artifacts SET storage_type = 'workspace', storage_path = path")
    op.alter_column("artifacts", "storage_type", nullable=False)
    op.alter_column("artifacts", "storage_path", nullable=False)
    op.create_unique_constraint(
        "uq_artifacts_storage_location", "artifacts", ["storage_type", "storage_path"]
    )
    op.drop_constraint("artifacts_path_key", "artifacts", type_="unique")
    op.drop_column("artifacts", "path")

    op.create_table(
        "agent_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("memory_type", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "agent_id", "session_id", "memory_type", "key",
            name="uq_agent_memories_namespace_key",
        ),
    )
    op.create_index(
        "ix_agent_memories_namespace",
        "agent_memories",
        ["agent_id", "session_id", "memory_type"],
    )
    op.create_index("ix_agent_memories_expires_at", "agent_memories", ["expires_at"])
    op.execute(
        """
        CREATE TABLE agent_memory_vectors (
            memory_id uuid PRIMARY KEY REFERENCES agent_memories(id) ON DELETE CASCADE,
            embedding vector(384) NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_agent_memory_vectors_embedding_hnsw "
        "ON agent_memory_vectors USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE agent_memory_vectors")
    op.drop_table("agent_memories")
    op.add_column("artifacts", sa.Column("path", sa.Text(), nullable=True))
    op.execute("UPDATE artifacts SET path = storage_path")
    op.alter_column("artifacts", "path", nullable=False)
    op.create_unique_constraint("artifacts_path_key", "artifacts", ["path"])
    op.drop_constraint("uq_artifacts_storage_location", "artifacts", type_="unique")
    op.drop_column("artifacts", "storage_path")
    op.drop_column("artifacts", "storage_type")
    op.drop_table("agent_api_versions")
    op.drop_table("agent_schema_versions")

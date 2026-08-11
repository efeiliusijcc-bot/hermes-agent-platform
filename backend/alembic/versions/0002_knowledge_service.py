"""create knowledge source and vector tables

Revision ID: 0002_knowledge_service
Revises: 0001_agent_registry
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002_knowledge_service"
down_revision: str | None = "0001_agent_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_knowledge_sources_status"),
    )
    op.create_index("ix_knowledge_sources_status", "knowledge_sources", ["status"])

    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False, unique=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("parser", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_id", "sha256", name="uq_knowledge_documents_source_sha256"),
        sa.CheckConstraint("size_bytes > 0", name="ck_knowledge_documents_size"),
        sa.CheckConstraint("chunk_count > 0", name="ck_knowledge_documents_chunks"),
    )
    op.create_index("ix_knowledge_documents_source_id", "knowledge_documents", ["source_id"])

    op.create_table(
        "agent_knowledge",
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "source_id"),
    )

    op.execute(
        """
        CREATE TABLE knowledge_chunks (
            id uuid PRIMARY KEY,
            document_id uuid NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            source_id varchar(64) NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
            chunk_index integer NOT NULL,
            content text NOT NULL,
            char_count integer NOT NULL,
            embedding vector(384) NOT NULL,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_knowledge_chunks_document_index UNIQUE (document_id, chunk_index),
            CONSTRAINT ck_knowledge_chunks_index CHECK (chunk_index >= 0),
            CONSTRAINT ck_knowledge_chunks_content CHECK (char_count > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_knowledge_chunks_source_id ON knowledge_chunks(source_id)")
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding_hnsw "
        "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE knowledge_chunks")
    op.drop_table("agent_knowledge")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_sources")

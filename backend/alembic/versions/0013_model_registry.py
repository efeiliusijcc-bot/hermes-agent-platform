"""add encrypted model registry

Revision ID: 0013_model_registry
Revises: 0012_pi_runtime_adapter
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0013_model_registry"
down_revision: str | None = "0012_pi_runtime_adapter"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_registrations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="custom"),
        sa.Column("adapter", sa.String(length=32), nullable=False, server_default="hermes"),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("upstream_model", sa.String(length=255), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="180"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="unknown"),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "adapter IN ('hermes', 'qwen', 'deepseek', 'gpt', 'claude')",
            name="ck_model_registrations_adapter",
        ),
        sa.CheckConstraint(
            "status IN ('unknown', 'online', 'offline')",
            name="ck_model_registrations_status",
        ),
        sa.CheckConstraint("timeout_seconds BETWEEN 5 AND 1800", name="ck_model_registrations_timeout"),
        sa.CheckConstraint("max_retries BETWEEN 0 AND 5", name="ck_model_registrations_retries"),
        sa.CheckConstraint("NOT is_default OR is_enabled", name="ck_model_registrations_default_enabled"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_model_registrations_one_default",
        "model_registrations",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_index(
        "ix_model_registrations_enabled_status",
        "model_registrations",
        ["is_enabled", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_model_registrations_enabled_status", table_name="model_registrations")
    op.drop_index("uq_model_registrations_one_default", table_name="model_registrations")
    op.drop_table("model_registrations")

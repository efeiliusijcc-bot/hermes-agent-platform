"""add Agent prompt, model adapter, and API gateway configuration

Revision ID: 0005_agent_gateway_contract
Revises: 0004_agent_response_mode
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_agent_gateway_contract"
down_revision: str | None = "0004_agent_response_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("model", sa.String(length=255), nullable=False, server_default="hermes-agent"),
    )
    op.add_column(
        "agents",
        sa.Column("prompt_template", sa.Text(), nullable=False, server_default="{{input}}"),
    )
    op.add_column(
        "agents",
        sa.Column("model_adapter", sa.String(length=32), nullable=False, server_default="hermes"),
    )
    op.add_column(
        "agents",
        sa.Column("api_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_agents_model_adapter",
        "agents",
        "model_adapter IN ('hermes', 'qwen', 'deepseek', 'gpt', 'claude')",
    )
    op.execute(
        """
        UPDATE agents
        SET api_enabled = EXISTS (
                SELECT 1 FROM agent_publications publication
                WHERE publication.agent_id = agents.id
                  AND publication.status = 'published'
            )
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_agents_model_adapter", "agents", type_="check")
    op.drop_column("agents", "api_enabled")
    op.drop_column("agents", "model_adapter")
    op.drop_column("agents", "prompt_template")
    op.drop_column("agents", "model")

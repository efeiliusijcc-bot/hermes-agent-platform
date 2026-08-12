"""add selectable Agent response mode

Revision ID: 0004_agent_response_mode
Revises: 0003_phase2_registry_publication
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_agent_response_mode"
down_revision: str | None = "0003_phase2_registry_publication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("response_mode", sa.String(length=16), nullable=False, server_default="sync"),
    )
    op.create_check_constraint(
        "ck_agents_response_mode",
        "agents",
        "response_mode IN ('sync', 'stream')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agents_response_mode", "agents", type_="check")
    op.drop_column("agents", "response_mode")

"""add durable Team conversation context

Revision ID: 0018_team_conversation_context
Revises: 0017_postgresql_mcp_connector
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0018_team_conversation_context"
down_revision: str | None = "0017_postgresql_mcp_connector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("session_id", sa.String(length=128), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE workflow_runs "
            "SET session_id = 'legacy-' || id::text "
            "WHERE session_id IS NULL"
        )
    )
    op.create_index(
        "ix_workflow_runs_team_session_created",
        "workflow_runs",
        ["team_id", "session_id", "created_at"],
    )
    op.create_index(
        "uq_workflow_runs_active_team_session",
        "workflow_runs",
        ["team_id", "session_id"],
        unique=True,
        postgresql_where=sa.text(
            "session_id IS NOT NULL AND status IN ('pending', 'running', 'human_review')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_workflow_runs_active_team_session", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_team_session_created", table_name="workflow_runs")
    op.drop_column("workflow_runs", "session_id")

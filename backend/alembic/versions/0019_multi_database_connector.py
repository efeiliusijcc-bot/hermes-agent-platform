"""add generic multi-database MCP connector type

Revision ID: 0019_multi_database_connector
Revises: 0018_team_conversation_context
"""
from collections.abc import Sequence

from alembic import op


revision: str = "0019_multi_database_connector"
down_revision: str | None = "0018_team_conversation_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_connectors_type", "connectors", type_="check")
    op.create_check_constraint(
        "ck_connectors_type",
        "connectors",
        "type IN ('internal_rest', 'mcp', 'postgresql_mcp', 'database_mcp')",
    )


def downgrade() -> None:
    op.execute("UPDATE connectors SET status = 'disabled' WHERE type = 'database_mcp'")
    op.execute("UPDATE connectors SET type = 'mcp' WHERE type = 'database_mcp'")
    op.drop_constraint("ck_connectors_type", "connectors", type_="check")
    op.create_check_constraint(
        "ck_connectors_type",
        "connectors",
        "type IN ('internal_rest', 'mcp', 'postgresql_mcp')",
    )

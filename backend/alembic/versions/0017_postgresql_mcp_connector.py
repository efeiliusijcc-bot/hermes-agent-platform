"""add PostgreSQL MCP connector support

Revision ID: 0017_postgresql_mcp_connector
Revises: 0016_capability_binding_and_invocation
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0017_postgresql_mcp_connector"
down_revision: str | None = "0016_capability_binding_and_invocation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.drop_constraint("ck_connectors_type", "connectors", type_="check")
    op.create_check_constraint(
        "ck_connectors_type",
        "connectors",
        "type IN ('internal_rest', 'mcp', 'postgresql_mcp')",
    )
    op.add_column(
        "connector_health_checks",
        sa.Column(
            "details",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.drop_constraint("uq_resources_connector_key", "resources", type_="unique")
    op.create_unique_constraint(
        "uq_resources_connector_type_key",
        "resources",
        ["connector_instance_id", "resource_type", "key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_resources_connector_type_key", "resources", type_="unique")
    op.create_unique_constraint(
        "uq_resources_connector_key",
        "resources",
        ["connector_instance_id", "key"],
    )
    op.drop_column("connector_health_checks", "details")
    op.drop_constraint("ck_connectors_type", "connectors", type_="check")
    op.create_check_constraint(
        "ck_connectors_type",
        "connectors",
        "type IN ('internal_rest', 'mcp')",
    )

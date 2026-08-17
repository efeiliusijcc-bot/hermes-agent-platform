"""upgrade the Runtime Integration Layer for multi-runtime agents

Revision ID: 0014_runtime_integration_layer
Revises: 0013_model_registry
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0014_runtime_integration_layer"
down_revision: str | None = "0013_model_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table, constraint in (
        ("agents", "ck_agents_runtime_type"),
        ("agent_runtimes", "ck_agent_runtimes_type"),
        ("execution_logs", "ck_execution_logs_runtime_type"),
        ("agent_sessions", "ck_agent_sessions_runtime_type"),
    ):
        op.drop_constraint(constraint, table, type_="check")

    op.create_check_constraint(
        "ck_agents_runtime_type",
        "agents",
        "runtime_type IN ('hermes', 'pi', 'deepseek')",
    )
    op.create_check_constraint(
        "ck_agent_runtimes_type",
        "agent_runtimes",
        "type IN ('hermes', 'pi', 'deepseek')",
    )
    op.create_check_constraint(
        "ck_execution_logs_runtime_type",
        "execution_logs",
        "runtime_type IN ('hermes', 'pi', 'deepseek')",
    )
    op.create_check_constraint(
        "ck_agent_sessions_runtime_type",
        "agent_sessions",
        "runtime_type IN ('hermes', 'pi', 'deepseek')",
    )

    op.add_column(
        "agents",
        sa.Column("runtime_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agents_runtime_id",
        "agents",
        "agent_runtimes",
        ["runtime_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_agents_runtime_id", "agents", ["runtime_id"])
    op.add_column(
        "agents",
        sa.Column(
            "capability_profile",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.execute(
        """
        UPDATE agents AS agent
        SET runtime_id = runtime.id
        FROM agent_runtimes AS runtime
        WHERE agent.runtime_config ? 'runtime_id'
          AND agent.runtime_config->>'runtime_id' = runtime.id::text
          AND agent.runtime_type = runtime.type
        """
    )
    op.execute(
        """
        UPDATE agents
        SET capability_profile = jsonb_build_object(
            'workspace_type', 'repository',
            'artifact_types', jsonb_build_array('code_patch', 'git_diff', 'test_report')
        )
        WHERE runtime_type = 'deepseek' AND capability_profile = '{}'::jsonb
        """
    )

    op.add_column(
        "agent_sessions",
        sa.Column("workspace_type", sa.String(length=32), nullable=False, server_default="document"),
    )
    op.create_check_constraint(
        "ck_agent_sessions_workspace_type",
        "agent_sessions",
        "workspace_type IN ('document', 'repository')",
    )
    op.execute(
        "UPDATE agent_sessions SET workspace_type = 'repository' WHERE runtime_type = 'deepseek'"
    )

    op.add_column(
        "artifacts",
        sa.Column("artifact_type", sa.String(length=64), nullable=False, server_default="text"),
    )
    op.add_column(
        "artifacts",
        sa.Column("runtime_source", sa.String(length=32), nullable=False, server_default="platform"),
    )
    op.execute(
        """
        UPDATE artifacts AS artifact
        SET artifact_type = CASE
                WHEN artifact.filename LIKE '%.md' THEN 'markdown'
                WHEN artifact.filename LIKE '%.json' THEN 'json'
                WHEN artifact.filename LIKE '%.pdf' THEN 'pdf'
                WHEN artifact.filename LIKE '%.xlsx' THEN 'xlsx'
                ELSE 'text'
            END
        """
    )
    op.create_check_constraint(
        "ck_artifacts_runtime_source",
        "artifacts",
        "runtime_source IN ('platform', 'hermes', 'pi', 'deepseek')",
    )

    op.drop_constraint("ck_execution_steps_type", "execution_steps", type_="check")
    op.create_check_constraint(
        "ck_execution_steps_type",
        "execution_steps",
        "step_type IN ("
        "'request', 'schema', 'memory', 'skill', 'mcp', 'knowledge', 'model', "
        "'artifact', 'runtime', 'plan', 'repository', 'code', 'test', 'git'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint("ck_execution_steps_type", "execution_steps", type_="check")
    op.create_check_constraint(
        "ck_execution_steps_type",
        "execution_steps",
        "step_type IN ("
        "'request', 'schema', 'memory', 'skill', 'mcp', 'knowledge', 'model', "
        "'artifact', 'runtime'"
        ")",
    )

    op.drop_constraint("ck_artifacts_runtime_source", "artifacts", type_="check")
    op.drop_column("artifacts", "runtime_source")
    op.drop_column("artifacts", "artifact_type")
    op.drop_constraint("ck_agent_sessions_workspace_type", "agent_sessions", type_="check")
    op.drop_column("agent_sessions", "workspace_type")
    op.drop_column("agents", "capability_profile")
    op.drop_index("ix_agents_runtime_id", table_name="agents")
    op.drop_constraint("fk_agents_runtime_id", "agents", type_="foreignkey")
    op.drop_column("agents", "runtime_id")

    for table, constraint in (
        ("agents", "ck_agents_runtime_type"),
        ("agent_runtimes", "ck_agent_runtimes_type"),
        ("execution_logs", "ck_execution_logs_runtime_type"),
        ("agent_sessions", "ck_agent_sessions_runtime_type"),
    ):
        op.drop_constraint(constraint, table, type_="check")
    op.create_check_constraint(
        "ck_agents_runtime_type", "agents", "runtime_type IN ('hermes', 'pi')"
    )
    op.create_check_constraint(
        "ck_agent_runtimes_type", "agent_runtimes", "type IN ('hermes', 'pi')"
    )
    op.create_check_constraint(
        "ck_execution_logs_runtime_type",
        "execution_logs",
        "runtime_type IN ('hermes', 'pi')",
    )
    op.create_check_constraint(
        "ck_agent_sessions_runtime_type",
        "agent_sessions",
        "runtime_type IN ('hermes', 'pi')",
    )

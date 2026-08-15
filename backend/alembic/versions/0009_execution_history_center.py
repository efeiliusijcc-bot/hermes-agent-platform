"""add Execution Studio history, trace, retry, and artifact links

Revision ID: 0009_execution_history
Revises: 0008_production_runtime
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0009_execution_history"
down_revision: str | None = "0008_production_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    empty_object = sa.text("'{}'::jsonb")
    op.drop_constraint("ck_execution_logs_status", "execution_logs", type_="check")
    op.create_check_constraint(
        "ck_execution_logs_status",
        "execution_logs",
        "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
    )
    op.add_column(
        "execution_logs",
        sa.Column("input_json", postgresql.JSONB(), nullable=False, server_default=empty_object),
    )
    op.add_column("execution_logs", sa.Column("output_json", postgresql.JSONB(), nullable=True))
    op.add_column(
        "execution_logs",
        sa.Column("response_mode", sa.String(length=16), nullable=False, server_default="sync"),
    )
    op.add_column("execution_logs", sa.Column("priority", sa.Integer(), nullable=True))
    op.add_column("execution_logs", sa.Column("duration_ms", sa.BigInteger(), nullable=True))
    op.add_column("execution_logs", sa.Column("token_usage", sa.BigInteger(), nullable=True))
    op.add_column(
        "execution_logs",
        sa.Column("retry_of_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_execution_logs_retry_of",
        "execution_logs",
        "execution_logs",
        ["retry_of_execution_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_execution_logs_response_mode",
        "execution_logs",
        "response_mode IN ('sync', 'stream', 'async')",
    )
    op.create_check_constraint(
        "ck_execution_logs_priority",
        "execution_logs",
        "priority IS NULL OR priority BETWEEN 0 AND 9",
    )
    op.create_check_constraint(
        "ck_execution_logs_duration",
        "execution_logs",
        "duration_ms IS NULL OR duration_ms >= 0",
    )
    op.create_check_constraint(
        "ck_execution_logs_token_usage",
        "execution_logs",
        "token_usage IS NULL OR token_usage >= 0",
    )
    op.create_index("ix_execution_logs_status_started", "execution_logs", ["status", "started_at"])
    op.create_index("ix_execution_logs_retry_of", "execution_logs", ["retry_of_execution_id"])
    op.execute(
        """
        UPDATE execution_logs
        SET input_json = jsonb_build_object('task', input, 'parameters', '{}'::jsonb),
            duration_ms = CASE
                WHEN finished_at IS NOT NULL
                THEN GREATEST(0, (EXTRACT(EPOCH FROM (finished_at - started_at)) * 1000)::bigint)
                ELSE NULL
            END,
            token_usage = CASE
                WHEN jsonb_typeof(details->'token_usage') = 'number'
                THEN (details->>'token_usage')::bigint
                ELSE NULL
            END
        """
    )

    op.create_table(
        "execution_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_key", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=32), nullable=False),
        sa.Column("step_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("input_data", postgresql.JSONB(), nullable=False, server_default=empty_object),
        sa.Column("output_data", postgresql.JSONB(), nullable=False, server_default=empty_object),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.BigInteger(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["execution_logs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("execution_id", "step_key", name="uq_execution_steps_execution_key"),
        sa.CheckConstraint(
            "step_type IN ('request', 'schema', 'memory', 'skill', 'mcp', 'knowledge', 'model', 'artifact', 'runtime')",
            name="ck_execution_steps_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped', 'cancelled')",
            name="ck_execution_steps_status",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_execution_steps_sequence"),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="ck_execution_steps_latency"
        ),
    )
    op.create_index(
        "ix_execution_steps_execution_sequence",
        "execution_steps",
        ["execution_id", "sequence"],
    )
    op.create_index("ix_execution_steps_type_status", "execution_steps", ["step_type", "status"])
    op.execute(
        """
        INSERT INTO execution_steps (
            id, execution_id, step_key, sequence, step_type, step_name, status,
            input_data, output_data, latency_ms, started_at, finished_at
        )
        SELECT md5('execution-request:' || execution.id::text)::uuid,
               execution.id, 'request_received', 0, 'request', 'Request Received', 'succeeded',
               '{}'::jsonb, '{}'::jsonb, 0, execution.started_at, execution.started_at
        FROM execution_logs execution
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO execution_steps (
            id, execution_id, step_key, sequence, step_type, step_name, status,
            input_data, output_data, error, latency_ms, started_at, finished_at
        )
        SELECT md5('execution-runtime:' || execution.id::text)::uuid,
               execution.id, 'hermes_runtime', 70, 'model', 'Hermes Runtime',
               CASE execution.status
                   WHEN 'succeeded' THEN 'succeeded'
                   WHEN 'failed' THEN 'failed'
                   WHEN 'cancelled' THEN 'cancelled'
                   WHEN 'running' THEN 'running'
                   ELSE 'pending'
               END,
               '{}'::jsonb,
               jsonb_build_object('hermes_run_id', execution.details->'hermes_run_id'),
               execution.error,
               execution.duration_ms,
               execution.started_at,
               execution.finished_at
        FROM execution_logs execution
        ON CONFLICT DO NOTHING
        """
    )

    op.create_table(
        "execution_artifacts",
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["execution_id"], ["execution_logs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("execution_id", "artifact_id"),
    )
    op.create_index("ix_execution_artifacts_artifact", "execution_artifacts", ["artifact_id"])
    op.execute(
        """
        INSERT INTO execution_artifacts (execution_id, artifact_id)
        SELECT DISTINCT ON (artifact.id) execution.id, artifact.id
        FROM artifacts artifact
        JOIN execution_logs execution ON execution.session_id = artifact.session_id
        ORDER BY artifact.id, execution.started_at DESC
        ON CONFLICT DO NOTHING
        """
    )

    op.add_column("agent_tasks", sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_agent_tasks_execution_id",
        "agent_tasks",
        "execution_logs",
        ["execution_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint("uq_agent_tasks_execution_id", "agent_tasks", ["execution_id"])
    op.execute(
        """
        UPDATE agent_tasks task
        SET execution_id = (
            SELECT execution.id
            FROM execution_logs execution
            WHERE execution.session_id = task.session_id
            ORDER BY execution.started_at DESC
            LIMIT 1
        )
        WHERE task.execution_id IS NULL
          AND EXISTS (
              SELECT 1 FROM execution_logs execution
              WHERE execution.session_id = task.session_id
          )
        """
    )


def downgrade() -> None:
    op.drop_constraint("uq_agent_tasks_execution_id", "agent_tasks", type_="unique")
    op.drop_constraint("fk_agent_tasks_execution_id", "agent_tasks", type_="foreignkey")
    op.drop_column("agent_tasks", "execution_id")
    op.drop_table("execution_artifacts")
    op.drop_table("execution_steps")
    op.drop_index("ix_execution_logs_retry_of", table_name="execution_logs")
    op.drop_index("ix_execution_logs_status_started", table_name="execution_logs")
    op.drop_constraint("ck_execution_logs_token_usage", "execution_logs", type_="check")
    op.drop_constraint("ck_execution_logs_duration", "execution_logs", type_="check")
    op.drop_constraint("ck_execution_logs_priority", "execution_logs", type_="check")
    op.drop_constraint("ck_execution_logs_response_mode", "execution_logs", type_="check")
    op.drop_constraint("fk_execution_logs_retry_of", "execution_logs", type_="foreignkey")
    op.drop_column("execution_logs", "retry_of_execution_id")
    op.drop_column("execution_logs", "token_usage")
    op.drop_column("execution_logs", "duration_ms")
    op.drop_column("execution_logs", "priority")
    op.drop_column("execution_logs", "response_mode")
    op.drop_column("execution_logs", "output_json")
    op.drop_column("execution_logs", "input_json")
    op.drop_constraint("ck_execution_logs_status", "execution_logs", type_="check")
    op.create_check_constraint(
        "ck_execution_logs_status",
        "execution_logs",
        "status IN ('running', 'succeeded', 'failed')",
    )

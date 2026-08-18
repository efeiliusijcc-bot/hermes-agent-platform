"""add the general capability and connector registry

Revision ID: 0015_general_capability_registry
Revises: 0014_runtime_integration_layer
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0015_general_capability_registry"
down_revision: str | None = "0014_runtime_integration_layer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    op.create_table(
        "capabilities",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("namespace", sa.String(128), nullable=False, server_default="platform"),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("risk_level", sa.String(16), nullable=False, server_default="LOW"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("owner_type", sa.String(32), nullable=False, server_default="platform"),
        sa.Column("owner_id", sa.String(128)),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        *_timestamps(),
        sa.UniqueConstraint("namespace", "key", name="uq_capabilities_namespace_key"),
        sa.CheckConstraint("risk_level IN ('LOW', 'MEDIUM', 'HIGH')", name="ck_capabilities_risk_level"),
        sa.CheckConstraint(
            "status IN ('draft', 'testing', 'published', 'deprecated', 'disabled')",
            name="ck_capabilities_status",
        ),
    )
    op.create_table(
        "capability_versions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("capability_id", UUID, sa.ForeignKey("capabilities.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("input_schema", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output_schema", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ui_schema", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_schema", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("side_effect", sa.String(32), nullable=False, server_default="READ_ONLY"),
        sa.Column("idempotency", sa.String(32), nullable=False, server_default="SAFE_RETRY"),
        sa.Column("cache_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("default_timeout_ms", sa.Integer(), nullable=False, server_default="15000"),
        sa.Column("compatibility", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("capability_id", "version", name="uq_capability_versions_capability_version"),
        sa.CheckConstraint(
            "status IN ('draft', 'testing', 'published', 'deprecated', 'disabled')",
            name="ck_capability_versions_status",
        ),
        sa.CheckConstraint(
            "side_effect IN ('READ_ONLY', 'WRITE', 'DESTRUCTIVE', 'EXTERNAL_COMMUNICATION', 'LONG_RUNNING')",
            name="ck_capability_versions_side_effect",
        ),
        sa.CheckConstraint(
            "idempotency IN ('SAFE_RETRY', 'IDEMPOTENT', 'NON_IDEMPOTENT')",
            name="ck_capability_versions_idempotency",
        ),
    )
    op.create_table(
        "connector_credentials",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("credential_type", sa.String(64), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("masked_label", sa.String(255), nullable=False),
        sa.Column("key_id", sa.String(64), nullable=False, server_default="fernet-v1"),
        sa.Column("rotation_status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("last_rotated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *_timestamps(),
        sa.CheckConstraint(
            "rotation_status IN ('active', 'rotation_due', 'revoked')",
            name="ck_connector_credentials_rotation_status",
        ),
    )
    op.create_table(
        "connectors",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("owner_type", sa.String(32), nullable=False, server_default="platform"),
        sa.Column("owner_id", sa.String(128)),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        *_timestamps(),
        sa.UniqueConstraint("key", name="uq_connectors_key"),
        sa.CheckConstraint("type IN ('internal_rest', 'mcp')", name="ck_connectors_type"),
        sa.CheckConstraint("status IN ('draft', 'published', 'disabled')", name="ck_connectors_status"),
    )
    op.create_table(
        "connector_instances",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("connector_id", UUID, sa.ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("environment", sa.String(64), nullable=False, server_default="production"),
        sa.Column("current_revision_id", UUID),
        sa.Column("health_status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint("connector_id", "name", name="uq_connector_instances_connector_name"),
        sa.CheckConstraint(
            "health_status IN ('unknown', 'healthy', 'degraded', 'offline')",
            name="ck_connector_instances_health",
        ),
    )
    op.create_table(
        "connector_instance_revisions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("connector_instance_id", UUID, sa.ForeignKey("connector_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("auth_type", sa.String(64), nullable=False, server_default="none"),
        sa.Column("credential_ref", UUID, sa.ForeignKey("connector_credentials.id", ondelete="RESTRICT")),
        sa.Column("network_zone", sa.String(64), nullable=False, server_default="internal"),
        sa.Column("connection_config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("timeout_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("retry_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("health_check_config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("config_digest", sa.String(71), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("connector_instance_id", "revision", name="uq_connector_instance_revisions_revision"),
    )
    op.create_foreign_key(
        "fk_connector_instances_current_revision_id",
        "connector_instances",
        "connector_instance_revisions",
        ["current_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "connector_operations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("connector_id", UUID, sa.ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_key", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("method", sa.String(16)),
        sa.Column("path_or_tool", sa.Text(), nullable=False),
        sa.Column("request_schema", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_schema", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("request_mapping", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_mapping", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_mapping", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("side_effect", sa.String(32), nullable=False, server_default="READ_ONLY"),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        *_timestamps(),
        sa.UniqueConstraint("connector_id", "operation_key", name="uq_connector_operations_connector_key"),
        sa.CheckConstraint("protocol IN ('internal_rest', 'mcp')", name="ck_connector_operations_protocol"),
        sa.CheckConstraint("status IN ('draft', 'published', 'disabled')", name="ck_connector_operations_status"),
    )
    op.create_table(
        "capability_implementations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("capability_version_id", UUID, sa.ForeignKey("capability_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("connector_operation_id", UUID, sa.ForeignKey("connector_operations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("connector_instance_revision_id", UUID, sa.ForeignKey("connector_instance_revisions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("mapping_override", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("routing_weight", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_capability_implementations_status"),
    )
    op.create_table(
        "resources",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("connector_instance_id", UUID, sa.ForeignKey("connector_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        *_timestamps(),
        sa.UniqueConstraint("connector_instance_id", "key", name="uq_resources_connector_key"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_resources_status"),
    )
    op.create_table(
        "resource_scopes",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("current_revision_id", UUID),
        sa.Column("owner_type", sa.String(32), nullable=False, server_default="platform"),
        sa.Column("owner_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "resource_scope_revisions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("resource_scope_id", UUID, sa.ForeignKey("resource_scopes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("scope_definition", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("scope_digest", sa.String(71), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("resource_scope_id", "revision", name="uq_resource_scope_revisions_revision"),
    )
    op.create_foreign_key(
        "fk_resource_scopes_current_revision_id",
        "resource_scopes",
        "resource_scope_revisions",
        ["current_revision_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "skill_versions",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("skill_id", sa.String(64), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("manifest", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("package_sha256", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False, server_default="published"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),
        sa.CheckConstraint("status IN ('draft', 'published', 'deprecated')", name="ck_skill_versions_status"),
    )
    op.create_table(
        "skill_capability_requirements",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("skill_version_id", UUID, sa.ForeignKey("skill_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias", sa.String(128), nullable=False),
        sa.Column("capability_key", sa.String(255), nullable=False),
        sa.Column("version_range", sa.String(128), nullable=False, server_default="*"),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("minimum_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_policy", sa.String(32), nullable=False, server_default="fail_closed"),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("skill_version_id", "alias", name="uq_skill_capability_requirements_alias"),
        sa.CheckConstraint(
            "failure_policy IN ('fail_closed', 'continue_with_warning')",
            name="ck_skill_capability_requirements_failure_policy",
        ),
    )
    op.create_table(
        "runtime_feature_profiles",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("runtime_registry_id", UUID, sa.ForeignKey("agent_runtimes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("runtime_version", sa.String(64), nullable=False),
        sa.Column("features", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("profile_digest", sa.String(71), nullable=False),
        sa.Column("health_status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("runtime_registry_id", "runtime_version", name="uq_runtime_feature_profiles_runtime_version"),
        sa.CheckConstraint(
            "health_status IN ('unknown', 'online', 'offline', 'disabled')",
            name="ck_runtime_feature_profiles_health",
        ),
    )
    op.execute(
        """
        INSERT INTO skill_versions (skill_id, version, manifest, package_sha256, status)
        SELECT id, version, manifest, package_sha256, 'published' FROM skills
        ON CONFLICT (skill_id, version) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO runtime_feature_profiles
            (runtime_registry_id, runtime_version, features, profile_digest, health_status)
        SELECT id, version,
               jsonb_build_object(
                   'tool_call', true,
                   'structured_output', true,
                   'streaming', true,
                   'stop', true,
                   'runtime_type', type
               ),
               'sha256:' || encode(sha256(convert_to(
                   jsonb_build_object('runtime_type', type, 'version', version)::text,
                   'UTF8'
               )), 'hex'),
               status
        FROM agent_runtimes
        ON CONFLICT (runtime_registry_id, runtime_version) DO NOTHING
        """
    )
    for table, columns in (
        ("capability_versions", ["status"]),
        ("connector_instances", ["health_status"]),
        ("connector_instance_revisions", ["connector_instance_id"]),
        ("capability_implementations", ["capability_version_id", "status"]),
        ("resources", ["resource_type", "status"]),
        ("skill_capability_requirements", ["capability_key"]),
        ("runtime_feature_profiles", ["health_status"]),
    ):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("runtime_feature_profiles")
    op.drop_table("skill_capability_requirements")
    op.drop_table("skill_versions")
    op.drop_constraint("fk_resource_scopes_current_revision_id", "resource_scopes", type_="foreignkey")
    op.drop_table("resource_scope_revisions")
    op.drop_table("resource_scopes")
    op.drop_table("resources")
    op.drop_table("capability_implementations")
    op.drop_table("connector_operations")
    op.drop_constraint("fk_connector_instances_current_revision_id", "connector_instances", type_="foreignkey")
    op.drop_table("connector_instance_revisions")
    op.drop_table("connector_instances")
    op.drop_table("connectors")
    op.drop_table("connector_credentials")
    op.drop_table("capability_versions")
    op.drop_table("capabilities")

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.database_connections import (
    POSTGRES_MCP_TOOLS,
    decrypt_credential,
    encrypt_credential,
    invalidate_connector_pools,
    masked_username,
    revise_scopes_for_connector_revision,
    scope_definition,
    validate_scope,
)
from app.api.console import (
    _capability_binding_display_context,
    _database_scope_context,
    _editor_version,
    _require_database_operation_permission,
)
from app.api.database_connections import require_database_console_bff
from app.db.models import (
    AgentVersion,
    CapabilityImplementation,
    Connector,
    ConnectorCredential,
    ConnectorInstance,
    ConnectorInstanceRevision,
    ResourceScope,
    ResourceScopeRevision,
)
from app.main import app
from app.schemas.database_connection import (
    DatabaseAgentBinding,
    DatabaseConnectionTestRequest,
    DatabaseObjectSelection,
    DatabaseScopeSelection,
    PostgreSQLCredentialInput,
)


def scope() -> DatabaseScopeSelection:
    return DatabaseScopeSelection(
        database="business_db",
        schemas=[DatabaseObjectSelection(name="public", tables=["items"], views=["item_report"])],
    )


def discovery() -> dict[str, object]:
    return {
        "status": "READY",
        "databases": [
            {
                "name": "business_db",
                "status": "READY",
                "schemas": [
                    {
                        "name": "public",
                        "tables": [{"name": "items", "columns": []}],
                        "views": [{"name": "item_report", "columns": []}],
                    }
                ],
            }
        ],
    }


def test_postgresql_credentials_round_trip_as_encrypted_json_and_never_mask_password() -> None:
    plain = PostgreSQLCredentialInput(username="hermes_reader", password="database-secret")
    encrypted = encrypt_credential(plain)
    assert "hermes_reader" not in encrypted and "database-secret" not in encrypted
    model = ConnectorCredential(
        name="test",
        credential_type="postgresql_password",
        encrypted_payload=encrypted,
        masked_label=masked_username("hermes_reader"),
    )
    assert decrypt_credential(model) == {"username": "hermes_reader", "password": "database-secret"}
    assert model.masked_label == "her***"


def test_scope_is_one_database_and_contains_no_endpoint_or_credentials() -> None:
    instance_id, revision_id = uuid4(), uuid4()
    value = scope_definition(instance_id, revision_id, scope())
    assert value["database"] == "business_db"
    assert value["connector_revision_id"] == str(revision_id)
    assert "host" not in value and "username" not in value and "password" not in value


def test_scope_selection_is_revalidated_against_discovery() -> None:
    validate_scope(discovery(), scope())
    invalid = scope().model_copy(
        update={"schemas": [DatabaseObjectSelection(name="public", tables=["missing"], views=[])]}
    )
    with pytest.raises(HTTPException, match="未发现"):
        validate_scope(discovery(), invalid)


def test_scope_schema_rejects_empty_or_duplicate_resource_selections() -> None:
    with pytest.raises(ValidationError, match="至少选择一个"):
        DatabaseScopeSelection(
            database="business_db",
            schemas=[DatabaseObjectSelection(name="public")],
        )
    with pytest.raises(ValidationError, match="不能重复"):
        DatabaseScopeSelection(
            database="business_db",
            schemas=[
                DatabaseObjectSelection(name="public", tables=["items"]),
                DatabaseObjectSelection(name="public", views=["item_report"]),
            ],
        )


def test_database_binding_schema_supports_multiple_independent_bindings() -> None:
    first = DatabaseAgentBinding(
        scope_revision_id=str(uuid4()), tool_prefix="business_db", operations=["select"]
    )
    second = DatabaseAgentBinding(
        scope_revision_id=str(uuid4()), tool_prefix="analytics_db", operations=["list_tables", "explain"]
    )
    assert first.tool_prefix != second.tool_prefix
    assert set(POSTGRES_MCP_TOOLS) == {
        "list_schemas", "list_tables", "describe_table", "preview_table", "select", "explain"
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("resource_type", "connector_type"),
    [("postgresql_database", "postgresql_mcp"), ("database_resource", "database_mcp")],
)
async def test_database_binding_accepts_current_healthy_legacy_and_generic_scope(
    resource_type: str,
    connector_type: str,
) -> None:
    scope_revision_id, scope_id, instance_id, connector_id, connector_revision_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    scope_revision = SimpleNamespace(
        id=scope_revision_id,
        resource_scope_id=scope_id,
        scope_definition={"connector_revision_id": str(connector_revision_id), "database": "business_db"},
    )
    resource_scope = SimpleNamespace(
        id=scope_id,
        resource_type=resource_type,
        owner_type="connector_instance",
        owner_id=str(instance_id),
        current_revision_id=scope_revision_id,
    )
    instance = SimpleNamespace(
        id=instance_id,
        connector_id=connector_id,
        current_revision_id=connector_revision_id,
        enabled=True,
        health_status="healthy",
    )
    connector = SimpleNamespace(id=connector_id, type=connector_type)
    values = {
        (ResourceScope, scope_id): resource_scope,
        (ConnectorInstance, instance_id): instance,
        (Connector, connector_id): connector,
    }

    async def get(model: type, identifier: object) -> object | None:
        return values.get((model, identifier))

    session = SimpleNamespace(get=AsyncMock(side_effect=get))
    definition, revision_id = await _database_scope_context(session, scope_revision)  # type: ignore[arg-type]
    assert definition["database"] == "business_db"
    assert revision_id == connector_revision_id

    resource_scope.current_revision_id = uuid4()
    with pytest.raises(HTTPException, match="已过期"):
        await _database_scope_context(session, scope_revision)  # type: ignore[arg-type]


def test_database_binding_rejects_tools_not_granted_by_scope() -> None:
    definition = {
        "permissions": {"describe": False, "preview": False, "query": False}
    }
    _require_database_operation_permission(definition, "list_tables")
    for operation in ("describe_table", "preview_table", "select", "explain"):
        with pytest.raises(HTTPException, match=operation):
            _require_database_operation_permission(definition, operation)


@pytest.mark.asyncio
async def test_agent_editor_falls_back_to_published_version_for_read_only_bindings() -> None:
    published_id = uuid4()
    published = SimpleNamespace(id=published_id, status="published")
    agent = SimpleNamespace(current_version_id=published_id)
    session = SimpleNamespace(get=AsyncMock(return_value=published))

    selected, source = await _editor_version(session, agent, None)  # type: ignore[arg-type]
    assert selected is published and source == "published"

    draft = SimpleNamespace(id=uuid4(), status="development")
    selected, source = await _editor_version(session, agent, draft)  # type: ignore[arg-type]
    assert selected is draft and source == "draft"
    session.get.assert_awaited_once_with(AgentVersion, published_id)


@pytest.mark.asyncio
async def test_agent_editor_exposes_database_alias_connection_database_and_scope() -> None:
    scope_revision_id, scope_id, implementation_id, connector_revision_id, instance_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    binding = SimpleNamespace(
        resource_scope_revision_id=scope_revision_id,
        implementation_id=implementation_id,
    )
    values = {
        (ResourceScopeRevision, scope_revision_id): SimpleNamespace(
            resource_scope_id=scope_id,
            scope_definition={"database": "business_db"},
        ),
        (ResourceScope, scope_id): SimpleNamespace(name="业务只读范围"),
        (CapabilityImplementation, implementation_id): SimpleNamespace(
            connector_instance_revision_id=connector_revision_id,
        ),
        (ConnectorInstanceRevision, connector_revision_id): SimpleNamespace(
            connector_instance_id=instance_id,
        ),
        (ConnectorInstance, instance_id): SimpleNamespace(name="业务 PostgreSQL"),
    }

    async def get(model: type, identifier: object) -> object | None:
        return values.get((model, identifier))

    session = SimpleNamespace(get=AsyncMock(side_effect=get))
    context = await _capability_binding_display_context(  # type: ignore[arg-type]
        session,
        binding,
    )
    assert context == {
        "connection_name": "业务 PostgreSQL",
        "database": "business_db",
        "scope_name": "业务只读范围",
        "scope_summary": "业务 PostgreSQL · business_db · 业务只读范围",
    }


@pytest.mark.asyncio
async def test_connector_revision_creates_new_scope_revision_without_mutating_history() -> None:
    instance_id, connector_revision_id, scope_id, old_scope_revision_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    instance = SimpleNamespace(id=instance_id)
    connector_revision = SimpleNamespace(id=connector_revision_id)
    resource_scope = SimpleNamespace(
        id=scope_id,
        name="业务库 / business_db",
        current_revision_id=old_scope_revision_id,
    )
    old_definition = scope_definition(instance_id, uuid4(), scope())
    current = SimpleNamespace(
        id=old_scope_revision_id,
        revision=3,
        scope_definition=old_definition,
    )
    added: list[object] = []
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=[resource_scope]),
        get=AsyncMock(return_value=current),
        add=Mock(side_effect=added.append),
    )

    async def flush() -> None:
        for value in added:
            if isinstance(value, ResourceScopeRevision) and value.id is None:
                value.id = uuid4()

    session.flush = AsyncMock(side_effect=flush)
    created = await revise_scopes_for_connector_revision(  # type: ignore[arg-type]
        session,
        instance,
        connector_revision,
        discovery(),
    )
    assert len(created) == 1
    assert created[0].revision == 4
    assert created[0].scope_definition["connector_revision_id"] == str(connector_revision_id)
    assert current.scope_definition == old_definition
    assert resource_scope.current_revision_id == created[0].id


@pytest.mark.asyncio
async def test_credential_rotation_and_disable_can_invalidate_every_revision_pool() -> None:
    instance_id = uuid4()
    revision_ids = [uuid4(), uuid4(), uuid4()]
    session = SimpleNamespace(scalars=AsyncMock(return_value=revision_ids))
    invalidate = AsyncMock()
    with patch("app.database_connections.PostgresMCPClient.invalidate", invalidate):
        await invalidate_connector_pools(session, instance_id)  # type: ignore[arg-type]
    assert {call.args[0] for call in invalidate.await_args_list} == set(revision_ids)


def test_database_console_routes_and_incremental_migration_are_present() -> None:
    paths = {route.path for route in app.routes}
    base = "/api/console/platform/database-connections"
    assert base in paths
    assert f"{base}/test" in paths
    assert f"{base}/{{instance_id}}/discover" in paths
    assert f"{base}/{{instance_id}}/credentials/replace" in paths
    migration = Path("backend/alembic/versions/0017_postgresql_mcp_connector.py").read_text()
    assert 'down_revision: str | None = "0016_capability_binding_and_invocation"' in migration
    assert "postgresql_mcp" in migration
    assert "drop_table" not in migration
    multi_database = Path("backend/alembic/versions/0019_multi_database_connector.py").read_text()
    assert 'down_revision: str | None = "0018_team_conversation_context"' in multi_database
    assert "database_mcp" in multi_database


@pytest.mark.parametrize(
    ("database_type", "port", "maintenance"),
    [
        ("postgresql", 5432, "postgres"),
        ("mysql", 3306, "mysql"),
        ("mariadb", 3306, "mysql"),
        ("doris", 9030, "information_schema"),
        ("starrocks", 9030, "information_schema"),
        ("sqlserver", 1433, "master"),
        ("oracle", 1521, "ORCL"),
        ("dm", 5236, "DM"),
        ("clickhouse", 8123, "default"),
        ("elasticsearch", 9200, "_cluster"),
    ],
)
def test_network_database_types_have_explicit_defaults_and_require_credentials(
    database_type: str,
    port: int,
    maintenance: str,
) -> None:
    value = DatabaseConnectionTestRequest.model_validate({
        "endpoint": {"database_type": database_type, "host": "database.internal"},
        "credential": {"username": "reader", "password": "secret"},
    })
    assert value.endpoint.port == port
    assert value.endpoint.maintenance_database == maintenance
    with pytest.raises(ValidationError, match="用户名和密码"):
        DatabaseConnectionTestRequest.model_validate({
            "endpoint": {"database_type": database_type, "host": "database.internal"},
            "credential": {},
        })


def test_sqlite_requires_a_scoped_file_but_not_network_credentials() -> None:
    value = DatabaseConnectionTestRequest.model_validate({
        "endpoint": {"database_type": "sqlite", "database_file": "reports/read-only.db"},
        "credential": {},
    })
    assert value.endpoint.port is None
    assert value.endpoint.maintenance_database == "main"
    with pytest.raises(ValidationError, match="SQLite"):
        DatabaseConnectionTestRequest.model_validate({
            "endpoint": {"database_type": "sqlite"},
            "credential": {},
        })


def test_offline_configuration_enables_capabilities_and_keeps_recall_upstream_empty() -> None:
    script = Path("scripts/configure-offline-env.sh").read_text()
    environment = Path(".env.example").read_text()
    exporter = Path("scripts/create-offline-bundle.sh").read_text()
    restore = Path("scripts/restore-offline-bundle.sh").read_text()
    compose_compat = Path("scripts/compose-compat.sh").read_text()
    phase9 = Path("tests/phase9_offline_deployment.sh").read_text()

    assert 'set_value CAPABILITY_PLATFORM_ENABLED "true"' in script
    assert 'set_value CAPABILITY_GATEWAY_ENABLED "true"' in script
    assert 'set_value CONSOLE_BFF_ENABLED "true"' in script
    assert 'set_value SOURCE_RECALL_ENABLED "false"' in script
    assert 'set_value SOURCE_RECALL_UPSTREAM_ENDPOINT ""' in script
    assert 'set_value SOURCE_RECALL_UPSTREAM_API_KEY ""' in script
    assert 'set_value SOURCE_RECALL_GATEWAY_API_KEY "$SOURCE_RECALL_GATEWAY_API_KEY"' in script
    assert 'docker_compat_run run --rm --network none --entrypoint python "$GENERATOR_IMAGE" -c' in script
    assert 'print("A" + token_urlsafe(36))' in script
    assert "CAPABILITY_PLATFORM_ENABLED=true" in environment
    assert "CAPABILITY_GATEWAY_ENABLED=true" in environment
    assert "CONSOLE_BFF_ENABLED=true" in environment
    assert "client.xrange(key)" in exporter
    assert "client.xinfo_groups(key)" in exporter
    assert "client.xadd(" in restore
    assert "client.xgroup_create(" in restore
    assert "compose_compat_select_wait_mode" in restore
    assert "compose_compat_up_and_wait" in restore
    assert "--wait --pull never" not in restore
    assert "config --quiet" not in restore
    assert "run --rm --no-deps --pull never" not in restore
    assert "OFFLINE_COMPOSE_WAIT_MODE=manual" in phase9
    assert "ps --status running" not in phase9
    assert 'COMPOSE_COMPAT_WAIT_MODE=${OFFLINE_COMPOSE_WAIT_MODE:-manual}' in compose_compat
    assert "docker_compat_run inspect --format '{{.State.Status}}'" in compose_compat
    assert "docker_compat_run inspect --format '{{if .State.Health}}" in compose_compat
    assert 'TARGET_CONTAINER_PREFIX=${OFFLINE_CONTAINER_PREFIX:-agent}' in restore
    assert 'checksum_mode=${OFFLINE_CHECKSUM_MODE:-warn}' in restore
    assert "compose_compat_init" in compose_compat
    assert "docker-compose" in compose_compat


def test_database_console_routes_follow_the_console_bff_feature_flag() -> None:
    with patch(
        "app.api.database_connections.get_settings",
        return_value=SimpleNamespace(console_bff_enabled=False),
    ):
        with pytest.raises(HTTPException, match="Console BFF"):
            require_database_console_bff()
    with patch(
        "app.api.database_connections.get_settings",
        return_value=SimpleNamespace(console_bff_enabled=True),
    ):
        require_database_console_bff()

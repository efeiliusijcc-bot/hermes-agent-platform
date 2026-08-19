from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    Capability,
    CapabilityImplementation,
    CapabilityResource,
    CapabilityVersion,
    Connector,
    ConnectorCredential,
    ConnectorHealthCheck,
    ConnectorInstance,
    ConnectorInstanceRevision,
    ConnectorOperation,
    ResourceScope,
    ResourceScopeRevision,
)
from app.model_secrets import ModelSecretCipher, ModelSecretError
from app.schemas.database_connection import (
    DatabaseConnectionCreate,
    DatabaseObjectSelection,
    DatabaseScopeSelection,
    PostgreSQLCredentialInput,
    PostgreSQLEndpoint,
)


POSTGRES_CONNECTOR_KEY = "postgresql_mcp"
POSTGRES_MCP_TOOLS: dict[str, dict[str, Any]] = {
    "list_schemas": {
        "capability": "database.list_schemas",
        "tool": "db_list_schemas",
        "label": "列出数据库 Schema",
        "input": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "list_tables": {
        "capability": "database.list_tables",
        "tool": "db_list_tables",
        "label": "列出数据库表和视图",
        "input": {
            "type": "object",
            "properties": {"schema": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    "describe_table": {
        "capability": "database.describe_table",
        "tool": "db_describe_table",
        "label": "查看表结构",
        "input": {
            "type": "object",
            "properties": {
                "schema": {"type": "string"},
                "table": {"type": "string"},
            },
            "required": ["schema", "table"],
            "additionalProperties": False,
        },
    },
    "preview_table": {
        "capability": "database.preview_table",
        "tool": "db_preview_table",
        "label": "预览表数据",
        "input": {
            "type": "object",
            "properties": {
                "schema": {"type": "string"},
                "table": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1},
            },
            "required": ["schema", "table"],
            "additionalProperties": False,
        },
    },
    "select": {
        "capability": "database.select",
        "tool": "db_select",
        "label": "执行只读查询",
        "input": {
            "type": "object",
            "properties": {"sql": {"type": "string", "minLength": 1}},
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
    "explain": {
        "capability": "database.explain",
        "tool": "db_explain",
        "label": "分析查询计划",
        "input": {
            "type": "object",
            "properties": {"sql": {"type": "string", "minLength": 1}},
            "required": ["sql"],
            "additionalProperties": False,
        },
    },
}


def digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def credential_payload(value: PostgreSQLCredentialInput) -> dict[str, str]:
    return {"username": value.username, "password": value.password.get_secret_value()}


def masked_username(username: str) -> str:
    if len(username) <= 3:
        return username[0] + "***"
    return username[:3] + "***"


def cipher() -> ModelSecretCipher:
    configured = get_settings().model_registry_encryption_key
    if configured is None:
        raise HTTPException(status_code=503, detail="数据库凭据加密密钥未配置")
    return ModelSecretCipher(configured.get_secret_value())


def encrypt_credential(value: PostgreSQLCredentialInput) -> str:
    return cipher().encrypt(json.dumps(credential_payload(value), ensure_ascii=False, separators=(",", ":")))


def decrypt_credential(value: ConnectorCredential) -> dict[str, str]:
    try:
        decoded = json.loads(cipher().decrypt(value.encrypted_payload))
    except (ModelSecretError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="数据库凭据无法解密") from exc
    if not isinstance(decoded, dict) or not isinstance(decoded.get("username"), str) or not isinstance(decoded.get("password"), str):
        raise HTTPException(status_code=500, detail="数据库凭据格式无效")
    return {"username": decoded["username"], "password": decoded["password"]}


class PostgresMCPClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.endpoint = settings.postgres_mcp_endpoint.rstrip("/")
        self.timeout = settings.postgres_mcp_timeout_seconds

    async def test_temporary(self, endpoint: PostgreSQLEndpoint, credential: PostgreSQLCredentialInput) -> dict[str, Any]:
        return await self._post(
            "/internal/admin/test",
            {"endpoint": endpoint.model_dump(), "credential": credential_payload(credential)},
        )

    async def test_revision(self, revision_id: UUID) -> dict[str, Any]:
        return await self._post(f"/internal/admin/revisions/{revision_id}/test", {})

    async def discover_revision(self, revision_id: UUID) -> dict[str, Any]:
        return await self._post(f"/internal/admin/revisions/{revision_id}/discover", {})

    async def invalidate(self, revision_id: UUID) -> None:
        await self._post(f"/internal/admin/revisions/{revision_id}/invalidate", {})

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                response = await client.post(f"{self.endpoint}{path}", json=payload)
            data = response.json()
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=502, detail="PostgreSQL MCP 服务不可用") from exc
        if response.status_code >= 400:
            detail = data.get("detail") if isinstance(data, dict) else None
            raise HTTPException(status_code=422 if response.status_code < 500 else 502, detail=detail or "数据库连接测试失败")
        if not isinstance(data, dict):
            raise HTTPException(status_code=502, detail="PostgreSQL MCP 返回格式无效")
        return data


async def invalidate_connector_pools(
    session: AsyncSession,
    instance_id: UUID,
) -> None:
    revision_ids = list(
        await session.scalars(
            select(ConnectorInstanceRevision.id).where(
                ConnectorInstanceRevision.connector_instance_id == instance_id
            )
        )
    )
    client = PostgresMCPClient()
    await asyncio.gather(
        *(client.invalidate(revision_id) for revision_id in revision_ids),
        return_exceptions=True,
    )


async def ensure_postgres_builtins(session: AsyncSession) -> tuple[Connector, dict[str, tuple[CapabilityVersion, ConnectorOperation]]]:
    connector = await session.scalar(select(Connector).where(Connector.key == POSTGRES_CONNECTOR_KEY))
    if connector is None:
        connector = Connector(
            key=POSTGRES_CONNECTOR_KEY,
            display_name="PostgreSQL MCP",
            type="postgresql_mcp",
            description="平台托管的 PostgreSQL 只读能力",
            status="published",
        )
        session.add(connector)
        await session.flush()
    else:
        connector.type = "postgresql_mcp"
        connector.status = "published"

    values: dict[str, tuple[CapabilityVersion, ConnectorOperation]] = {}
    for operation_key, specification in POSTGRES_MCP_TOOLS.items():
        capability = await session.scalar(
            select(Capability).where(
                Capability.namespace == "platform",
                Capability.key == specification["capability"],
            )
        )
        if capability is None:
            capability = Capability(
                namespace="platform",
                key=specification["capability"],
                display_name=specification["label"],
                description="PostgreSQL MCP 只读数据库能力",
                risk_level="LOW",
                status="published",
            )
            session.add(capability)
            await session.flush()
        version = await session.scalar(
            select(CapabilityVersion).where(
                CapabilityVersion.capability_id == capability.id,
                CapabilityVersion.version == "1.0.0",
            )
        )
        if version is None:
            version = CapabilityVersion(
                capability_id=capability.id,
                version="1.0.0",
                input_schema=specification["input"],
                output_schema={"type": "object"},
                ui_schema={},
                error_schema={},
                side_effect="READ_ONLY",
                idempotency="SAFE_RETRY",
                cache_policy={"ttl_seconds": 30 if operation_key in {"list_schemas", "list_tables", "describe_table"} else 0},
                default_timeout_ms=15_000,
                compatibility={"required_features": ["capability_gateway"]},
                status="published",
                published_at=datetime.now(timezone.utc),
            )
            session.add(version)
            await session.flush()
        operation = await session.scalar(
            select(ConnectorOperation).where(
                ConnectorOperation.connector_id == connector.id,
                ConnectorOperation.operation_key == operation_key,
            )
        )
        if operation is None:
            operation = ConnectorOperation(
                connector_id=connector.id,
                operation_key=operation_key,
                display_name=specification["label"],
                protocol="mcp",
                path_or_tool=specification["tool"],
                request_schema=specification["input"],
                response_schema={"type": "object"},
                side_effect="READ_ONLY",
                status="published",
            )
            session.add(operation)
            await session.flush()
        values[operation_key] = (version, operation)
    return connector, values


def validate_scope(discovery: dict[str, Any], scope: DatabaseScopeSelection) -> None:
    databases = discovery.get("databases")
    database = next((item for item in databases or [] if isinstance(item, dict) and item.get("name") == scope.database), None)
    if database is None or database.get("status") != "READY":
        raise HTTPException(status_code=422, detail=f"数据库 {scope.database} 未成功发现")
    discovered_schemas = {item.get("name"): item for item in database.get("schemas") or [] if isinstance(item, dict)}
    for selected_schema in scope.schemas:
        discovered = discovered_schemas.get(selected_schema.name)
        if discovered is None:
            raise HTTPException(status_code=422, detail=f"Schema {scope.database}.{selected_schema.name} 不存在")
        tables = {item.get("name") for item in discovered.get("tables") or [] if isinstance(item, dict)}
        views = {item.get("name") for item in discovered.get("views") or [] if isinstance(item, dict)}
        unknown_tables = sorted(set(selected_schema.tables) - tables)
        unknown_views = sorted(set(selected_schema.views) - views)
        if unknown_tables or unknown_views:
            raise HTTPException(status_code=422, detail=f"Scope 包含未发现的对象：{unknown_tables + unknown_views}")


def scope_definition(instance_id: UUID, revision_id: UUID, scope: DatabaseScopeSelection) -> dict[str, Any]:
    return {
        "connector_instance_id": str(instance_id),
        "connector_revision_id": str(revision_id),
        "database": scope.database,
        "schemas": {
            item.name: {"tables": sorted(set(item.tables)), "views": sorted(set(item.views))}
            for item in scope.schemas
        },
        "permissions": {
            "describe": scope.allow_describe,
            "query": scope.allow_query,
            "preview": scope.allow_preview,
            "aggregate": scope.allow_aggregate,
        },
        "limits": {
            "max_rows": scope.max_rows,
            "statement_timeout_ms": scope.statement_timeout_ms,
            "lock_timeout_ms": scope.lock_timeout_ms,
            "max_response_bytes": scope.max_response_bytes,
            "requests_per_minute": scope.requests_per_minute,
        },
    }


async def add_scope(
    session: AsyncSession,
    instance: ConnectorInstance,
    revision: ConnectorInstanceRevision,
    scope: DatabaseScopeSelection,
) -> ResourceScopeRevision:
    definition = scope_definition(instance.id, revision.id, scope)
    value = ResourceScope(
        name=scope.name or f"{instance.name} / {scope.database}",
        resource_type="postgresql_database",
        owner_type="connector_instance",
        owner_id=str(instance.id),
    )
    session.add(value)
    await session.flush()
    revision_value = ResourceScopeRevision(
        resource_scope_id=value.id,
        revision=1,
        scope_definition=definition,
        scope_digest=digest(definition),
    )
    session.add(revision_value)
    await session.flush()
    value.current_revision_id = revision_value.id
    return revision_value


async def revise_scopes_for_connector_revision(
    session: AsyncSession,
    instance: ConnectorInstance,
    revision: ConnectorInstanceRevision,
    discovery: dict[str, Any],
) -> list[ResourceScopeRevision]:
    """Carry current database scopes forward onto a new connector revision.

    Published Agent bindings keep referencing the old immutable scope revision;
    only the scope's current revision pointer advances for future drafts.
    """
    scopes = list(
        await session.scalars(
            select(ResourceScope)
            .where(
                ResourceScope.owner_type == "connector_instance",
                ResourceScope.owner_id == str(instance.id),
                ResourceScope.resource_type == "postgresql_database",
            )
            .order_by(ResourceScope.created_at)
        )
    )
    created: list[ResourceScopeRevision] = []
    for scope in scopes:
        if scope.current_revision_id is None:
            continue
        current = await session.get(ResourceScopeRevision, scope.current_revision_id)
        if current is None:
            continue
        previous = current.scope_definition or {}
        permissions = previous.get("permissions") if isinstance(previous.get("permissions"), dict) else {}
        limits = previous.get("limits") if isinstance(previous.get("limits"), dict) else {}
        schemas = previous.get("schemas") if isinstance(previous.get("schemas"), dict) else {}
        selection = DatabaseScopeSelection(
            database=str(previous.get("database") or ""),
            name=scope.name,
            schemas=[
                DatabaseObjectSelection(
                    name=str(schema_name),
                    tables=list(value.get("tables") or []) if isinstance(value, dict) else [],
                    views=list(value.get("views") or []) if isinstance(value, dict) else [],
                )
                for schema_name, value in schemas.items()
            ],
            allow_describe=bool(permissions.get("describe", True)),
            allow_query=bool(permissions.get("query", True)),
            allow_preview=bool(permissions.get("preview", True)),
            allow_aggregate=bool(permissions.get("aggregate", True)),
            max_rows=int(limits.get("max_rows") or 200),
            statement_timeout_ms=int(limits.get("statement_timeout_ms") or 5000),
            lock_timeout_ms=int(limits.get("lock_timeout_ms") or 1000),
            max_response_bytes=int(limits.get("max_response_bytes") or 2_097_152),
            requests_per_minute=int(limits.get("requests_per_minute") or 60),
        )
        validate_scope(discovery, selection)
        definition = scope_definition(instance.id, revision.id, selection)
        value = ResourceScopeRevision(
            resource_scope_id=scope.id,
            revision=int(current.revision) + 1,
            scope_definition=definition,
            scope_digest=digest(definition),
        )
        session.add(value)
        await session.flush()
        scope.current_revision_id = value.id
        created.append(value)
    return created


async def store_resources(session: AsyncSession, instance: ConnectorInstance, discovery: dict[str, Any]) -> None:
    await session.execute(
        delete(CapabilityResource).where(CapabilityResource.connector_instance_id == instance.id)
    )
    await session.flush()
    for database in discovery.get("databases") or []:
        if not isinstance(database, dict) or database.get("status") != "READY":
            continue
        database_name = str(database.get("name"))
        session.add(CapabilityResource(
            connector_instance_id=instance.id,
            resource_type="database",
            key=database_name,
            display_name=database_name,
            resource_metadata={"database": database_name},
        ))
        for schema in database.get("schemas") or []:
            if not isinstance(schema, dict):
                continue
            schema_name = str(schema.get("name"))
            session.add(CapabilityResource(
                connector_instance_id=instance.id,
                resource_type="schema",
                key=f"{database_name}.{schema_name}",
                display_name=schema_name,
                resource_metadata={"database": database_name, "schema": schema_name},
            ))
            for resource_type in ("table", "view"):
                for item in schema.get(f"{resource_type}s") or []:
                    if not isinstance(item, dict):
                        continue
                    object_name = str(item.get("name"))
                    session.add(CapabilityResource(
                        connector_instance_id=instance.id,
                        resource_type=resource_type,
                        key=f"{database_name}.{schema_name}.{object_name}",
                        display_name=object_name,
                        resource_metadata={
                            "database": database_name,
                            "schema": schema_name,
                            "columns": item.get("columns") or [],
                        },
                    ))


async def add_implementations(
    session: AsyncSession,
    revision: ConnectorInstanceRevision,
    builtins: dict[str, tuple[CapabilityVersion, ConnectorOperation]],
) -> None:
    for version, operation in builtins.values():
        session.add(CapabilityImplementation(
            capability_version_id=version.id,
            connector_operation_id=operation.id,
            connector_instance_revision_id=revision.id,
            priority=100,
            routing_weight=100,
            status="active",
        ))


async def create_database_connection(
    session: AsyncSession,
    payload: DatabaseConnectionCreate,
    discovery: dict[str, Any],
) -> ConnectorInstance:
    if discovery.get("status") != "READY":
        raise HTTPException(status_code=422, detail="数据库连接测试未通过")
    for selected in payload.scopes:
        validate_scope(discovery, selected)
    connector, builtins = await ensure_postgres_builtins(session)
    duplicate = await session.scalar(
        select(ConnectorInstance).where(
            ConnectorInstance.connector_id == connector.id,
            ConnectorInstance.name == payload.name,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="数据库连接名称已存在")
    credential = ConnectorCredential(
        name=f"postgresql:{payload.name}:{uuid4().hex[:8]}",
        credential_type="postgresql_password",
        encrypted_payload=encrypt_credential(payload.credential),
        masked_label=masked_username(payload.credential.username),
    )
    session.add(credential)
    await session.flush()
    instance = ConnectorInstance(
        connector_id=connector.id,
        name=payload.name,
        environment=payload.environment,
        health_status="healthy",
        enabled=True,
    )
    session.add(instance)
    await session.flush()
    connection_config = payload.endpoint.model_dump()
    revision = ConnectorInstanceRevision(
        connector_instance_id=instance.id,
        revision=1,
        endpoint=f"{get_settings().postgres_mcp_endpoint.rstrip('/')}/mcp",
        auth_type="execution_capability",
        credential_ref=credential.id,
        network_zone="internal",
        connection_config=connection_config,
        timeout_policy={
            "connect_seconds": payload.endpoint.connect_timeout_seconds,
            "read_seconds": max(item.statement_timeout_ms for item in payload.scopes) / 1000 + 5,
        },
        retry_policy={"max_retries": 1},
        health_check_config={"kind": "postgresql"},
        config_digest=digest(connection_config),
    )
    session.add(revision)
    await session.flush()
    instance.current_revision_id = revision.id
    await store_resources(session, instance, discovery)
    for selected in payload.scopes:
        await add_scope(session, instance, revision, selected)
    await add_implementations(session, revision, builtins)
    session.add(ConnectorHealthCheck(
        connector_instance_revision_id=revision.id,
        status="healthy",
        latency_ms=int(discovery.get("latency_ms") or 0),
        details=discovery,
    ))
    await session.commit()
    await session.refresh(instance)
    return instance


async def current_revision(session: AsyncSession, instance: ConnectorInstance) -> ConnectorInstanceRevision:
    if instance.current_revision_id is None:
        raise HTTPException(status_code=409, detail="数据库连接没有当前 Revision")
    value = await session.get(ConnectorInstanceRevision, instance.current_revision_id)
    if value is None:
        raise HTTPException(status_code=409, detail="数据库连接 Revision 不存在")
    return value


async def postgres_instance(session: AsyncSession, instance_id: UUID) -> ConnectorInstance:
    value = await session.scalar(
        select(ConnectorInstance)
        .join(Connector, Connector.id == ConnectorInstance.connector_id)
        .where(ConnectorInstance.id == instance_id, Connector.type == "postgresql_mcp")
    )
    if value is None:
        raise HTTPException(status_code=404, detail="数据库连接不存在")
    return value


async def next_revision_number(session: AsyncSession, instance_id: UUID) -> int:
    maximum = await session.scalar(
        select(func.max(ConnectorInstanceRevision.revision)).where(
            ConnectorInstanceRevision.connector_instance_id == instance_id
        )
    )
    return int(maximum or 0) + 1

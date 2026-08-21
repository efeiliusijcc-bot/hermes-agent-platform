from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_connections import (
    DATABASE_CONNECTOR_TYPES,
    DatabaseMCPClient,
    add_implementations,
    add_scope,
    create_database_connection,
    current_revision,
    decrypt_credential,
    digest,
    encrypt_credential,
    ensure_database_builtins,
    invalidate_connector_pools,
    masked_username,
    next_revision_number,
    database_instance,
    revise_scopes_for_connector_revision,
    store_resources,
    validate_scope,
)
from app.config import get_settings
from app.db.models import (
    CapabilityImplementation,
    CapabilityResource,
    ConnectorCredential,
    ConnectorHealthCheck,
    Connector,
    ConnectorInstance,
    ConnectorInstanceRevision,
    ResourceScope,
    ResourceScopeRevision,
)
from app.db.session import get_session
from app.schemas.database_connection import (
    DatabaseConnectionCreate,
    DatabaseConnectionTestRequest,
    DatabaseConnectionUpdate,
    DatabaseCredentialInput,
    DatabaseCredentialReplace,
    DatabaseEndpoint,
    DatabaseScopeCreate,
)


def require_database_console_bff() -> None:
    if not get_settings().console_bff_enabled:
        raise HTTPException(status_code=404, detail="Console BFF 尚未启用")


router = APIRouter(
    prefix="/api/console/platform/database-connections",
    tags=["database-connections"],
    dependencies=[Depends(require_database_console_bff)],
)


@router.get("")
async def list_database_connections(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    instances = list(
        await session.scalars(
            select(ConnectorInstance)
            .join(Connector, Connector.id == ConnectorInstance.connector_id)
            .where(Connector.type.in_(DATABASE_CONNECTOR_TYPES))
            .order_by(ConnectorInstance.updated_at.desc())
        )
    )
    return [await _summary(session, item) for item in instances]


@router.post("/test")
async def test_database_connection(
    payload: DatabaseConnectionTestRequest,
) -> dict[str, Any]:
    return await DatabaseMCPClient().test_temporary(payload.endpoint, payload.credential)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_connection(
    payload: DatabaseConnectionCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    discovery = await DatabaseMCPClient().test_temporary(payload.endpoint, payload.credential)
    instance = await create_database_connection(session, payload, discovery)
    return await _detail(session, instance)


@router.get("/{instance_id}")
async def get_database_connection(
    instance_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await _detail(session, await database_instance(session, instance_id))


@router.patch("/{instance_id}")
async def update_database_connection(
    instance_id: UUID,
    payload: DatabaseConnectionUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    instance = await database_instance(session, instance_id)
    old_revision = await current_revision(session, instance)
    if payload.name is not None:
        instance.name = payload.name
    if payload.environment is not None:
        instance.environment = payload.environment
    if payload.enabled is not None:
        instance.enabled = payload.enabled
    if payload.endpoint is not None:
        previous_type = str((old_revision.connection_config or {}).get("database_type") or "postgresql")
        if payload.endpoint.database_type != previous_type:
            raise HTTPException(status_code=422, detail="数据库类型不能在原连接上更换，请新建连接")
        if old_revision.credential_ref is None:
            raise HTTPException(status_code=409, detail="数据库连接没有凭据")
        credential = await session.get(ConnectorCredential, old_revision.credential_ref)
        if credential is None:
            raise HTTPException(status_code=409, detail="数据库凭据不存在")
        plain = decrypt_credential(credential)
        input_credential = DatabaseCredentialInput(**plain)
        discovery = await DatabaseMCPClient().test_temporary(payload.endpoint, input_credential)
        if discovery.get("status") != "READY":
            raise HTTPException(status_code=422, detail="新连接配置测试未通过")
        _, builtins = await ensure_database_builtins(session)
        config = payload.endpoint.model_dump()
        revision = ConnectorInstanceRevision(
            connector_instance_id=instance.id,
            revision=await next_revision_number(session, instance.id),
            endpoint=old_revision.endpoint,
            auth_type="execution_capability",
            credential_ref=old_revision.credential_ref,
            network_zone="internal",
            connection_config=config,
            timeout_policy={"connect_seconds": payload.endpoint.connect_timeout_seconds, "read_seconds": 30},
            retry_policy={"max_retries": 1},
            health_check_config={"kind": payload.endpoint.database_type},
            config_digest=digest(config),
        )
        session.add(revision)
        await session.flush()
        instance.current_revision_id = revision.id
        instance.health_status = "healthy"
        await store_resources(session, instance, discovery)
        await revise_scopes_for_connector_revision(session, instance, revision, discovery)
        await add_implementations(session, revision, builtins)
        session.add(ConnectorHealthCheck(
            connector_instance_revision_id=revision.id,
            status="healthy",
            latency_ms=int(discovery.get("latency_ms") or 0),
            details=discovery,
        ))
    await session.commit()
    if payload.endpoint is not None or payload.enabled is False:
        await invalidate_connector_pools(session, instance.id)
    return await _detail(session, instance)


@router.delete("/{instance_id}")
async def disable_database_connection(
    instance_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    instance = await database_instance(session, instance_id)
    await current_revision(session, instance)
    instance.enabled = False
    instance.health_status = "offline"
    await session.commit()
    await invalidate_connector_pools(session, instance.id)
    return {"id": str(instance.id), "status": "disabled"}


@router.post("/{instance_id}/test")
async def test_saved_database_connection(
    instance_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    instance = await database_instance(session, instance_id)
    revision = await current_revision(session, instance)
    result = await DatabaseMCPClient().test_revision(revision.id)
    instance.health_status = "healthy" if result.get("status") == "READY" else "offline"
    session.add(ConnectorHealthCheck(
        connector_instance_revision_id=revision.id,
        status=instance.health_status,
        latency_ms=int(result.get("latency_ms") or 0),
        error_code=None if instance.health_status == "healthy" else "CONNECTION_FAILED",
        details=result,
    ))
    await session.commit()
    return result


@router.post("/{instance_id}/discover")
async def discover_database_connection(
    instance_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    instance = await database_instance(session, instance_id)
    revision = await current_revision(session, instance)
    result = await DatabaseMCPClient().discover_revision(revision.id)
    await store_resources(session, instance, result)
    await session.commit()
    return result


@router.get("/{instance_id}/resources")
async def list_database_resources(
    instance_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await database_instance(session, instance_id)
    resources = list(
        await session.scalars(
            select(CapabilityResource)
            .where(CapabilityResource.connector_instance_id == instance_id)
            .order_by(CapabilityResource.resource_type, CapabilityResource.key)
        )
    )
    return [
        {
            "id": str(item.id),
            "type": item.resource_type,
            "key": item.key,
            "name": item.display_name,
            "metadata": item.resource_metadata,
            "status": item.status,
        }
        for item in resources
    ]


@router.post("/{instance_id}/scopes", status_code=status.HTTP_201_CREATED)
async def create_database_scope(
    instance_id: UUID,
    payload: DatabaseScopeCreate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    instance = await database_instance(session, instance_id)
    revision = await current_revision(session, instance)
    discovery = await DatabaseMCPClient().discover_revision(revision.id)
    validate_scope(discovery, payload.scope)
    value = await add_scope(session, instance, revision, payload.scope)
    await session.commit()
    return _scope_read(value)


@router.post("/{instance_id}/credentials/replace")
async def replace_database_credential(
    instance_id: UUID,
    payload: DatabaseCredentialReplace,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    instance = await database_instance(session, instance_id)
    revision = await current_revision(session, instance)
    if revision.credential_ref is None:
        raise HTTPException(status_code=409, detail="数据库连接没有凭据")
    credential = await session.get(ConnectorCredential, revision.credential_ref)
    if credential is None:
        raise HTTPException(status_code=409, detail="数据库凭据不存在")
    replacement = DatabaseCredentialInput(username=payload.username, password=payload.password)
    endpoint = revision.connection_config or {}
    try:
        endpoint_value = DatabaseEndpoint.model_validate(endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="数据库连接配置无效，不能轮换凭据") from exc
    discovery = await DatabaseMCPClient().test_temporary(endpoint_value, replacement)
    if discovery.get("status") != "READY":
        raise HTTPException(status_code=422, detail="新数据库凭据测试未通过")
    credential.encrypted_payload = encrypt_credential(replacement)
    credential.masked_label = masked_username(payload.username)
    credential.rotation_status = "active"
    credential.last_rotated_at = datetime.now(timezone.utc)
    if instance.enabled:
        instance.health_status = "healthy"
    session.add(ConnectorHealthCheck(
        connector_instance_revision_id=revision.id,
        status="healthy",
        latency_ms=int(discovery.get("latency_ms") or 0),
        details=discovery,
    ))
    await session.commit()
    await invalidate_connector_pools(session, instance.id)
    return {
        "credential_configured": True,
        "masked_username": credential.masked_label,
        "password_updated_at": credential.last_rotated_at,
    }


async def _summary(session: AsyncSession, instance: ConnectorInstance) -> dict[str, Any]:
    scope_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ResourceScope)
            .where(
                ResourceScope.owner_type == "connector_instance",
                ResourceScope.owner_id == str(instance.id),
            )
        )
        or 0
    )
    revision = await current_revision(session, instance)
    config = revision.connection_config or {}
    return {
        "id": str(instance.id),
        "name": instance.name,
        "environment": instance.environment,
        "status": "DISABLED" if not instance.enabled else ("READY" if instance.health_status == "healthy" else instance.health_status.upper()),
        "host": config.get("host"),
        "port": config.get("port"),
        "maintenance_database": config.get("maintenance_database"),
        "database_type": config.get("database_type", "postgresql"),
        "scope_count": scope_count,
        "current_revision_id": str(revision.id),
        "updated_at": instance.updated_at,
    }


async def _detail(session: AsyncSession, instance: ConnectorInstance) -> dict[str, Any]:
    summary = await _summary(session, instance)
    revision = await current_revision(session, instance)
    credential = await session.get(ConnectorCredential, revision.credential_ref) if revision.credential_ref else None
    scopes = list(
        await session.scalars(
            select(ResourceScope)
            .where(
                ResourceScope.owner_type == "connector_instance",
                ResourceScope.owner_id == str(instance.id),
            )
            .order_by(ResourceScope.created_at.desc())
        )
    )
    scope_values: list[dict[str, Any]] = []
    for scope in scopes:
        if scope.current_revision_id is None:
            continue
        scope_revision = await session.get(ResourceScopeRevision, scope.current_revision_id)
        if scope_revision is not None:
            scope_values.append(_scope_read(scope_revision, scope.name))
    return {
        **summary,
        "enabled": instance.enabled,
        "endpoint": revision.connection_config,
        "credential": {
            "credential_configured": credential is not None,
            "masked_username": credential.masked_label if credential else None,
            "password_updated_at": credential.last_rotated_at if credential else None,
        },
        "scopes": scope_values,
    }


def _scope_read(value: ResourceScopeRevision, name: str | None = None) -> dict[str, Any]:
    definition = value.scope_definition or {}
    return {
        "id": str(value.id),
        "scope_id": str(value.resource_scope_id),
        "name": name,
        "revision": value.revision,
        "database": definition.get("database"),
        "definition": definition,
        "digest": value.scope_digest,
        "created_at": value.created_at,
    }

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import (
    Capability,
    CapabilityImplementation,
    CapabilityVersion,
    Connector,
    ConnectorCredential,
    ConnectorInstance,
    ConnectorInstanceRevision,
    ConnectorOperation,
    MCPServer,
)
from app.model_secrets import ModelSecretCipher


async def bootstrap_capability_platform(session: AsyncSession) -> dict[str, Any]:
    imported_mcps: list[str] = []
    for server in await session.scalars(select(MCPServer).order_by(MCPServer.id)):
        kind = str((server.config or {}).get("kind") or "")
        definition = _legacy_definition(kind)
        if definition is None:
            continue
        await _ensure_stack(
            session,
            connector_key=f"legacy-mcp.{server.id}",
            connector_name=f"{server.name}（兼容导入）",
            connector_type="mcp",
            endpoint=server.endpoint,
            operation_key=definition["operation_key"],
            operation_path=definition["operation_key"],
            method=None,
            capability_key=definition["capability_key"],
            capability_name=definition["capability_name"],
            input_schema=definition["input_schema"],
            output_schema=definition["output_schema"],
            request_mapping={},
            response_mapping={},
            credential=None,
            auth_type="execution_capability",
        )
        imported_mcps.append(server.id)

    source_recall = False
    settings = get_settings()
    if (
        settings.source_recall_enabled
        and settings.source_recall_gateway_endpoint
        and settings.source_recall_gateway_api_key is not None
        and settings.model_registry_encryption_key is not None
    ):
        secret = settings.source_recall_gateway_api_key.get_secret_value()
        credential = await _ensure_credential(
            session,
            name="source-recall-gateway",
            credential_type="bearer",
            secret=secret,
            cipher=ModelSecretCipher(settings.model_registry_encryption_key.get_secret_value()),
        )
        await _ensure_stack(
            session,
            connector_key="internal-source-recall",
            connector_name="内部信源召回",
            connector_type="internal_rest",
            endpoint=settings.source_recall_gateway_endpoint,
            operation_key="source-recall",
            operation_path="/v1/recall",
            method="POST",
            capability_key="knowledge.search",
            capability_name="知识搜索",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
                    "filters": {"type": "object"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "items": {"type": "array"},
                    "total": {"type": "integer"},
                    "metadata": {"type": "object"},
                },
                "required": ["items", "total"],
            },
            request_mapping={
                "fields": {"query": "topic", "top_k": "limit"},
                "drop": ["filters"],
                "fixed": {"lookbackDays": settings.source_recall_default_lookback_days},
            },
            response_mapping={
                "fields": {"items": "sources", "total": "totalHits", "metadata": "diagnostics"}
            },
            credential=credential,
            auth_type="bearer",
        )
        source_recall = True
    await session.commit()
    return {"legacy_mcp_ids": imported_mcps, "source_recall_migrated": source_recall}


async def _ensure_stack(
    session: AsyncSession,
    *,
    connector_key: str,
    connector_name: str,
    connector_type: str,
    endpoint: str,
    operation_key: str,
    operation_path: str,
    method: str | None,
    capability_key: str,
    capability_name: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    request_mapping: dict[str, Any],
    response_mapping: dict[str, Any],
    credential: ConnectorCredential | None,
    auth_type: str,
) -> None:
    connector = await session.scalar(select(Connector).where(Connector.key == connector_key))
    if connector is None:
        connector = Connector(
            key=connector_key,
            display_name=connector_name,
            type=connector_type,
            status="published",
            description="由平台兼容迁移自动创建",
        )
        session.add(connector)
        await session.flush()
    instance = await session.scalar(
        select(ConnectorInstance).where(
            ConnectorInstance.connector_id == connector.id,
            ConnectorInstance.name == "production",
        )
    )
    if instance is None:
        instance = ConnectorInstance(connector_id=connector.id, name="production")
        session.add(instance)
        await session.flush()
    revision = await session.scalar(
        select(ConnectorInstanceRevision)
        .where(ConnectorInstanceRevision.connector_instance_id == instance.id)
        .order_by(ConnectorInstanceRevision.revision.desc())
        .limit(1)
    )
    if revision is None:
        config = {"endpoint": endpoint, "auth_type": auth_type, "credential_ref": str(credential.id) if credential else None}
        revision = ConnectorInstanceRevision(
            connector_instance_id=instance.id,
            revision=1,
            endpoint=endpoint,
            auth_type=auth_type,
            credential_ref=credential.id if credential else None,
            network_zone="internal",
            connection_config={},
            timeout_policy={"connect_seconds": 5, "read_seconds": 60},
            retry_policy={"max_retries": 1},
            health_check_config=(
                {"path": "/health", "method": "GET"}
                if connector_key == "internal-source-recall"
                else {}
            ),
            config_digest=_digest(config),
        )
        session.add(revision)
        await session.flush()
        instance.current_revision_id = revision.id
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
            display_name=operation_key,
            protocol=connector_type,
            method=method,
            path_or_tool=operation_path,
            request_schema=input_schema,
            response_schema=output_schema,
            request_mapping=request_mapping,
            response_mapping=response_mapping,
            error_mapping={},
            side_effect="READ_ONLY",
            status="published",
        )
        session.add(operation)
        await session.flush()
    capability = await session.scalar(
        select(Capability).where(Capability.namespace == "platform", Capability.key == capability_key)
    )
    if capability is None:
        capability = Capability(
            namespace="platform",
            key=capability_key,
            display_name=capability_name,
            description=f"通过 {connector_name} 提供",
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
            input_schema=input_schema,
            output_schema=output_schema,
            side_effect="READ_ONLY",
            idempotency="SAFE_RETRY",
            status="published",
        )
        session.add(version)
        await session.flush()
    implementation = await session.scalar(
        select(CapabilityImplementation).where(
            CapabilityImplementation.capability_version_id == version.id,
            CapabilityImplementation.connector_operation_id == operation.id,
            CapabilityImplementation.connector_instance_revision_id == revision.id,
        )
    )
    if implementation is None:
        session.add(
            CapabilityImplementation(
                capability_version_id=version.id,
                connector_operation_id=operation.id,
                connector_instance_revision_id=revision.id,
                status="active",
            )
        )


async def _ensure_credential(
    session: AsyncSession,
    *,
    name: str,
    credential_type: str,
    secret: str,
    cipher: ModelSecretCipher,
) -> ConnectorCredential:
    value = await session.scalar(select(ConnectorCredential).where(ConnectorCredential.name == name))
    if value is None:
        value = ConnectorCredential(
            name=name,
            credential_type=credential_type,
            encrypted_payload=cipher.encrypt(secret),
            masked_label=f"已配置 ····{secret[-4:]}",
        )
        session.add(value)
        await session.flush()
    return value


def _legacy_definition(kind: str) -> dict[str, Any] | None:
    if kind == "filesystem":
        return {
            "operation_key": "filesystem_read",
            "capability_key": "file.read",
            "capability_name": "文件读取",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False},
            "output_schema": {"type": "object"},
        }
    if kind == "database":
        return {
            "operation_key": "database_query",
            "capability_key": "database.query",
            "capability_name": "数据库查询",
            "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"], "additionalProperties": False},
            "output_schema": {"type": "object"},
        }
    return None


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"

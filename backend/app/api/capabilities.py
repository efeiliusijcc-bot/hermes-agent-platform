from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from time import monotonic
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from jsonschema import Draft202012Validator, SchemaError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.resolver import resolve_agent_capabilities
from app.db.models import (
    Agent,
    AgentCapabilityBinding,
    AgentVersion,
    Capability,
    CapabilityImplementation,
    CapabilityInvocation,
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
    SkillVersion,
    agent_skill,
)
from app.db.session import get_session
from app.model_secrets import ModelSecretCipher, ModelSecretError
from app.repositories import production as production_repository
from app.schemas.capability import (
    AgentCapabilityBindingRead,
    AgentCapabilityBindingsUpdate,
    CapabilityCreate,
    CapabilityImplementationCreate,
    CapabilityImplementationRead,
    CapabilityInvocationRead,
    CapabilityRead,
    CapabilityUpdate,
    CapabilityVersionCreate,
    CapabilityVersionRead,
    ConnectorCreate,
    ConnectorInstanceCreate,
    ConnectorInstanceRead,
    ConnectorOperationCreate,
    ConnectorOperationRead,
    ConnectorRead,
    ConnectorRevisionCreate,
    ConnectorRevisionRead,
    CredentialCreate,
    CredentialRead,
    CredentialRotate,
    ResourceCreate,
    ResourceRead,
    ResourceScopeCreate,
    ResourceScopeRead,
    ResourceScopeRevisionCreate,
    ResourceScopeRevisionRead,
)
from app.config import get_settings
from app.capabilities.bootstrap import bootstrap_capability_platform


router = APIRouter(tags=["capability-platform"])


@router.post("/api/capability-platform/migrations/import-legacy")
async def import_legacy_capabilities(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await bootstrap_capability_platform(session)


@router.get("/api/capabilities", response_model=list[CapabilityRead])
async def list_capabilities(
    state: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[CapabilityRead]:
    statement = select(Capability)
    if state:
        statement = statement.where(Capability.status == state)
    values = await session.scalars(statement.order_by(Capability.namespace, Capability.key))
    return [CapabilityRead.model_validate(item) for item in values]


@router.post("/api/capabilities", response_model=CapabilityRead, status_code=status.HTTP_201_CREATED)
async def create_capability(
    payload: CapabilityCreate,
    session: AsyncSession = Depends(get_session),
) -> CapabilityRead:
    value = Capability(**payload.model_dump())
    session.add(value)
    await _commit(session, "Capability Key 已存在")
    await session.refresh(value)
    return CapabilityRead.model_validate(value)


@router.get("/api/capabilities/{capability_id}", response_model=CapabilityRead)
async def get_capability(
    capability_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> CapabilityRead:
    return CapabilityRead.model_validate(await _required(session, Capability, capability_id, "能力不存在"))


@router.patch("/api/capabilities/{capability_id}", response_model=CapabilityRead)
async def update_capability(
    capability_id: UUID,
    payload: CapabilityUpdate,
    session: AsyncSession = Depends(get_session),
) -> CapabilityRead:
    value = await _required(session, Capability, capability_id, "能力不存在")
    for key, item in payload.model_dump(exclude_unset=True).items():
        setattr(value, key, item)
    await session.commit()
    await session.refresh(value)
    return CapabilityRead.model_validate(value)


@router.post(
    "/api/capabilities/{capability_id}/versions",
    response_model=CapabilityVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_capability_version(
    capability_id: UUID,
    payload: CapabilityVersionCreate,
    session: AsyncSession = Depends(get_session),
) -> CapabilityVersionRead:
    await _required(session, Capability, capability_id, "能力不存在")
    _validate_contract(payload.input_schema, payload.output_schema, payload.ui_schema)
    value = CapabilityVersion(capability_id=capability_id, **payload.model_dump())
    session.add(value)
    await _commit(session, "该能力版本已存在")
    await session.refresh(value)
    return CapabilityVersionRead.model_validate(value)


@router.get("/api/capabilities/{capability_id}/versions", response_model=list[CapabilityVersionRead])
async def list_capability_versions(
    capability_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[CapabilityVersionRead]:
    await _required(session, Capability, capability_id, "能力不存在")
    values = await session.scalars(
        select(CapabilityVersion)
        .where(CapabilityVersion.capability_id == capability_id)
        .order_by(CapabilityVersion.created_at.desc())
    )
    return [CapabilityVersionRead.model_validate(item) for item in values]


@router.post("/api/capability-versions/{version_id}/test")
async def test_capability_version(
    version_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    value = await _required(session, CapabilityVersion, version_id, "能力版本不存在")
    _validate_contract(value.input_schema, value.output_schema, value.ui_schema)
    if value.status == "draft":
        value.status = "testing"
        await session.commit()
    return {"status": "valid", "version_id": str(value.id), "errors": []}


@router.post("/api/capability-versions/{version_id}/publish", response_model=CapabilityVersionRead)
async def publish_capability_version(
    version_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> CapabilityVersionRead:
    value = await _required(session, CapabilityVersion, version_id, "能力版本不存在")
    if value.status not in {"draft", "testing"}:
        raise HTTPException(status_code=409, detail="只有 Draft 或 Testing 版本可以发布")
    _validate_contract(value.input_schema, value.output_schema, value.ui_schema)
    value.status = "published"
    value.published_at = datetime.now(timezone.utc)
    capability = await session.get(Capability, value.capability_id)
    if capability is not None:
        capability.status = "published"
    await session.commit()
    await session.refresh(value)
    return CapabilityVersionRead.model_validate(value)


@router.post("/api/capability-versions/{version_id}/deprecate", response_model=CapabilityVersionRead)
async def deprecate_capability_version(
    version_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> CapabilityVersionRead:
    value = await _required(session, CapabilityVersion, version_id, "能力版本不存在")
    if value.status != "published":
        raise HTTPException(status_code=409, detail="只有 Published 版本可以废弃")
    value.status = "deprecated"
    await session.commit()
    await session.refresh(value)
    return CapabilityVersionRead.model_validate(value)


@router.get("/api/credentials", response_model=list[CredentialRead])
async def list_credentials(session: AsyncSession = Depends(get_session)) -> list[CredentialRead]:
    values = await session.scalars(select(ConnectorCredential).order_by(ConnectorCredential.name))
    return [CredentialRead.model_validate(item) for item in values]


@router.post("/api/credentials", response_model=CredentialRead, status_code=status.HTTP_201_CREATED)
async def create_credential(
    payload: CredentialCreate,
    session: AsyncSession = Depends(get_session),
) -> CredentialRead:
    secret = payload.secret.get_secret_value()
    value = ConnectorCredential(
        name=payload.name,
        credential_type=payload.credential_type,
        encrypted_payload=_cipher().encrypt(secret),
        masked_label=payload.masked_label or _mask_secret(secret),
    )
    session.add(value)
    await _commit(session, "凭据名称已存在")
    await session.refresh(value)
    return CredentialRead.model_validate(value)


@router.post("/api/credentials/{credential_id}/rotate", response_model=CredentialRead)
async def rotate_credential(
    credential_id: UUID,
    payload: CredentialRotate,
    session: AsyncSession = Depends(get_session),
) -> CredentialRead:
    value = await _required(session, ConnectorCredential, credential_id, "凭据不存在")
    secret = payload.secret.get_secret_value()
    value.encrypted_payload = _cipher().encrypt(secret)
    value.masked_label = payload.masked_label or _mask_secret(secret)
    value.rotation_status = "active"
    value.last_rotated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(value)
    return CredentialRead.model_validate(value)


@router.get("/api/connectors", response_model=list[ConnectorRead])
async def list_connectors(session: AsyncSession = Depends(get_session)) -> list[ConnectorRead]:
    values = await session.scalars(select(Connector).order_by(Connector.display_name))
    return [ConnectorRead.model_validate(item) for item in values]


@router.post("/api/connectors", response_model=ConnectorRead, status_code=status.HTTP_201_CREATED)
async def create_connector(
    payload: ConnectorCreate,
    session: AsyncSession = Depends(get_session),
) -> ConnectorRead:
    value = Connector(**payload.model_dump())
    session.add(value)
    await _commit(session, "Connector Key 已存在")
    await session.refresh(value)
    return ConnectorRead.model_validate(value)


@router.get("/api/connectors/{connector_id}", response_model=ConnectorRead)
async def get_connector(
    connector_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ConnectorRead:
    return ConnectorRead.model_validate(await _required(session, Connector, connector_id, "连接不存在"))


@router.post(
    "/api/connectors/{connector_id}/instances",
    response_model=ConnectorInstanceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_connector_instance(
    connector_id: UUID,
    payload: ConnectorInstanceCreate,
    session: AsyncSession = Depends(get_session),
) -> ConnectorInstanceRead:
    await _required(session, Connector, connector_id, "连接不存在")
    value = ConnectorInstance(connector_id=connector_id, **payload.model_dump())
    session.add(value)
    await _commit(session, "连接实例名称已存在")
    await session.refresh(value)
    return ConnectorInstanceRead.model_validate(value)


@router.post(
    "/api/connector-instances/{instance_id}/revisions",
    response_model=ConnectorRevisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_connector_revision(
    instance_id: UUID,
    payload: ConnectorRevisionCreate,
    session: AsyncSession = Depends(get_session),
) -> ConnectorRevisionRead:
    instance = await _required(session, ConnectorInstance, instance_id, "连接实例不存在")
    if payload.credential_ref:
        await _required(session, ConnectorCredential, payload.credential_ref, "凭据不存在")
    _validate_endpoint(payload.endpoint)
    revision_number = int(
        await session.scalar(
            select(func.max(ConnectorInstanceRevision.revision)).where(
                ConnectorInstanceRevision.connector_instance_id == instance_id
            )
        )
        or 0
    ) + 1
    dumped = payload.model_dump(mode="json")
    value = ConnectorInstanceRevision(
        connector_instance_id=instance_id,
        revision=revision_number,
        config_digest=_digest(dumped),
        **payload.model_dump(),
    )
    session.add(value)
    await session.flush()
    instance.current_revision_id = value.id
    instance.health_status = "unknown"
    await session.commit()
    await session.refresh(value)
    return ConnectorRevisionRead.model_validate(value)


@router.post("/api/connector-instance-revisions/{revision_id}/test")
async def test_connector_revision(
    revision_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    revision = await _required(session, ConnectorInstanceRevision, revision_id, "连接 Revision 不存在")
    instance = await _required(session, ConnectorInstance, revision.connector_instance_id, "连接实例不存在")
    started = monotonic()
    online = False
    error_code: str | None = None
    try:
        _validate_endpoint(revision.endpoint)
        timeout = float((revision.timeout_policy or {}).get("connect_seconds") or 5)
        health_path = str((revision.health_check_config or {}).get("path") or "")
        method = str((revision.health_check_config or {}).get("method") or "GET").upper()
        url = revision.endpoint.rstrip("/") + (health_path if health_path.startswith("/") else f"/{health_path}" if health_path else "")
        headers = _credential_headers(revision, await session.get(ConnectorCredential, revision.credential_ref) if revision.credential_ref else None)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url, headers=headers)
        online = response.is_success
        if not online:
            error_code = f"HTTP_{response.status_code}"
    except (httpx.HTTPError, ValueError, ModelSecretError) as exc:
        error_code = type(exc).__name__.upper()
    latency = max(0, round((monotonic() - started) * 1000))
    instance.health_status = "healthy" if online else "offline"
    session.add(
        ConnectorHealthCheck(
            connector_instance_revision_id=revision.id,
            status="healthy" if online else "offline",
            latency_ms=latency,
            error_code=error_code,
        )
    )
    await session.commit()
    return {"status": instance.health_status, "latency_ms": latency, "error_code": error_code}


@router.get("/api/connectors/{connector_id}/operations", response_model=list[ConnectorOperationRead])
async def list_connector_operations(
    connector_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[ConnectorOperationRead]:
    values = await session.scalars(
        select(ConnectorOperation)
        .where(ConnectorOperation.connector_id == connector_id)
        .order_by(ConnectorOperation.operation_key)
    )
    return [ConnectorOperationRead.model_validate(item) for item in values]


@router.post(
    "/api/connectors/{connector_id}/operations",
    response_model=ConnectorOperationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_connector_operation(
    connector_id: UUID,
    payload: ConnectorOperationCreate,
    session: AsyncSession = Depends(get_session),
) -> ConnectorOperationRead:
    connector = await _required(session, Connector, connector_id, "连接不存在")
    if connector.type != payload.protocol:
        raise HTTPException(status_code=422, detail="Operation Protocol 必须与 Connector Type 一致")
    _validate_contract(payload.request_schema, payload.response_schema, {})
    value = ConnectorOperation(connector_id=connector_id, **payload.model_dump())
    session.add(value)
    await _commit(session, "Operation Key 已存在")
    await session.refresh(value)
    return ConnectorOperationRead.model_validate(value)


@router.post(
    "/api/capability-implementations",
    response_model=CapabilityImplementationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_capability_implementation(
    payload: CapabilityImplementationCreate,
    session: AsyncSession = Depends(get_session),
) -> CapabilityImplementationRead:
    version = await _required(session, CapabilityVersion, payload.capability_version_id, "能力版本不存在")
    if version.status not in {"published", "deprecated"}:
        raise HTTPException(status_code=409, detail="Capability Implementation 只能绑定已发布版本")
    await _required(session, ConnectorOperation, payload.connector_operation_id, "Operation 不存在")
    await _required(session, ConnectorInstanceRevision, payload.connector_instance_revision_id, "连接 Revision 不存在")
    value = CapabilityImplementation(**payload.model_dump())
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return CapabilityImplementationRead.model_validate(value)


@router.get("/api/resources", response_model=list[ResourceRead])
async def list_resources(session: AsyncSession = Depends(get_session)) -> list[ResourceRead]:
    values = await session.scalars(select(CapabilityResource).order_by(CapabilityResource.display_name))
    return [ResourceRead.model_validate(item) for item in values]


@router.post("/api/resources", response_model=ResourceRead, status_code=status.HTTP_201_CREATED)
async def create_resource(
    payload: ResourceCreate,
    session: AsyncSession = Depends(get_session),
) -> ResourceRead:
    await _required(session, ConnectorInstance, payload.connector_instance_id, "连接实例不存在")
    dumped = payload.model_dump()
    metadata = dumped.pop("metadata")
    value = CapabilityResource(resource_metadata=metadata, **dumped)
    session.add(value)
    await _commit(session, "资源 Key 已存在")
    await session.refresh(value)
    return ResourceRead.model_validate(value)


@router.get("/api/resource-scopes", response_model=list[ResourceScopeRead])
async def list_resource_scopes(session: AsyncSession = Depends(get_session)) -> list[ResourceScopeRead]:
    values = await session.scalars(select(ResourceScope).order_by(ResourceScope.name))
    return [ResourceScopeRead.model_validate(item) for item in values]


@router.post("/api/resource-scopes", response_model=ResourceScopeRead, status_code=status.HTTP_201_CREATED)
async def create_resource_scope(
    payload: ResourceScopeCreate,
    session: AsyncSession = Depends(get_session),
) -> ResourceScopeRead:
    value = ResourceScope(name=payload.name, resource_type=payload.resource_type)
    session.add(value)
    await session.flush()
    revision = ResourceScopeRevision(
        resource_scope_id=value.id,
        revision=1,
        scope_definition=payload.scope_definition,
        scope_digest=_digest(payload.scope_definition),
    )
    session.add(revision)
    await session.flush()
    value.current_revision_id = revision.id
    await session.commit()
    await session.refresh(value)
    return ResourceScopeRead.model_validate(value)


@router.post(
    "/api/resource-scopes/{scope_id}/revisions",
    response_model=ResourceScopeRevisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_resource_scope_revision(
    scope_id: UUID,
    payload: ResourceScopeRevisionCreate,
    session: AsyncSession = Depends(get_session),
) -> ResourceScopeRevisionRead:
    scope = await _required(session, ResourceScope, scope_id, "资源范围不存在")
    revision_number = int(
        await session.scalar(
            select(func.max(ResourceScopeRevision.revision)).where(
                ResourceScopeRevision.resource_scope_id == scope_id
            )
        )
        or 0
    ) + 1
    value = ResourceScopeRevision(
        resource_scope_id=scope_id,
        revision=revision_number,
        scope_definition=payload.scope_definition,
        scope_digest=_digest(payload.scope_definition),
    )
    session.add(value)
    await session.flush()
    scope.current_revision_id = value.id
    await session.commit()
    await session.refresh(value)
    return ResourceScopeRevisionRead.model_validate(value)


@router.get(
    "/api/agents/{agent_id}/draft/capability-bindings",
    response_model=list[AgentCapabilityBindingRead],
)
async def get_draft_bindings(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[AgentCapabilityBindingRead]:
    version = await _draft_version(session, agent_id, create=False)
    if version is None:
        return []
    values = await session.scalars(
        select(AgentCapabilityBinding)
        .where(AgentCapabilityBinding.agent_version_id == version.id)
        .order_by(AgentCapabilityBinding.tool_alias)
    )
    return [AgentCapabilityBindingRead.model_validate(item) for item in values]


@router.put(
    "/api/agents/{agent_id}/draft/capability-bindings",
    response_model=list[AgentCapabilityBindingRead],
)
async def update_draft_bindings(
    agent_id: str,
    payload: AgentCapabilityBindingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> list[AgentCapabilityBindingRead]:
    version = await _draft_version(session, agent_id, create=True)
    assert version is not None
    if version.status != "development":
        raise HTTPException(status_code=409, detail="只有 Development Draft 可以修改 Capability Binding")
    aliases = [item.tool_alias for item in payload.bindings]
    if len(aliases) != len(set(aliases)):
        raise HTTPException(status_code=422, detail="Tool Alias 不能重复")
    await session.execute(
        delete(AgentCapabilityBinding).where(AgentCapabilityBinding.agent_version_id == version.id)
    )
    values: list[AgentCapabilityBinding] = []
    for item in payload.bindings:
        capability_version = await _required(session, CapabilityVersion, item.capability_version_id, "能力版本不存在")
        if capability_version.status not in {"published", "deprecated"}:
            raise HTTPException(status_code=409, detail="只能绑定已发布的能力版本")
        if item.implementation_id:
            await _required(session, CapabilityImplementation, item.implementation_id, "能力实现不存在")
        if item.resource_scope_revision_id:
            await _required(session, ResourceScopeRevision, item.resource_scope_revision_id, "资源范围 Revision 不存在")
        value = AgentCapabilityBinding(agent_version_id=version.id, **item.model_dump())
        session.add(value)
        values.append(value)
    await session.commit()
    for value in values:
        await session.refresh(value)
    return [AgentCapabilityBindingRead.model_validate(item) for item in values]


@router.get("/api/agents/{agent_id}/available-capabilities")
async def available_capabilities(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    await _required(session, Agent, agent_id, "Agent 不存在")
    rows = (
        await session.execute(
            select(Capability, CapabilityVersion)
            .join(CapabilityVersion, CapabilityVersion.capability_id == Capability.id)
            .where(CapabilityVersion.status == "published")
            .order_by(Capability.display_name, CapabilityVersion.version.desc())
        )
    ).all()
    return [
        {
            "id": str(version.id),
            "key": capability.key,
            "label": capability.display_name,
            "description": capability.description,
            "version": version.version,
            "side_effect": version.side_effect,
            "input_schema": version.input_schema,
            "ui_schema": version.ui_schema,
        }
        for capability, version in rows
    ]


@router.get("/api/capability-catalog")
async def capability_catalog(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Capability, CapabilityVersion)
            .join(CapabilityVersion, CapabilityVersion.capability_id == Capability.id)
            .where(CapabilityVersion.status == "published")
            .order_by(Capability.display_name, CapabilityVersion.version.desc())
        )
    ).all()
    return [
        {
            "id": str(version.id),
            "key": capability.key,
            "label": capability.display_name,
            "description": capability.description,
            "version": version.version,
            "side_effect": version.side_effect,
            "input_schema": version.input_schema,
            "ui_schema": version.ui_schema,
        }
        for capability, version in rows
    ]


@router.post("/api/agents/{agent_id}/preflight")
async def agent_preflight(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    version = await _draft_version(session, agent_id, create=False)
    if version is None:
        return {
            "state": "NEEDS_CONFIGURATION",
            "issues": [{"code": "DRAFT_REQUIRED", "path": "agent", "message": "请先保存 Agent 草稿", "severity": "error"}],
        }
    return (await resolve_agent_capabilities(session, version)).as_dict()


@router.get("/api/capability-invocations", response_model=list[CapabilityInvocationRead])
async def list_capability_invocations(
    agent_id: str | None = None,
    execution_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[CapabilityInvocationRead]:
    statement = select(CapabilityInvocation)
    if agent_id:
        statement = statement.where(CapabilityInvocation.agent_id == agent_id)
    if execution_id:
        statement = statement.where(CapabilityInvocation.execution_id == execution_id)
    values = await session.scalars(statement.order_by(CapabilityInvocation.created_at.desc()).limit(limit))
    return [CapabilityInvocationRead.model_validate(item) for item in values]


@router.get("/api/capability-invocations/{invocation_id}", response_model=CapabilityInvocationRead)
async def get_capability_invocation(
    invocation_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> CapabilityInvocationRead:
    return CapabilityInvocationRead.model_validate(
        await _required(session, CapabilityInvocation, invocation_id, "调用记录不存在")
    )


async def _draft_version(
    session: AsyncSession,
    agent_id: str,
    *,
    create: bool,
) -> AgentVersion | None:
    agent = await _required(session, Agent, agent_id, "Agent 不存在")
    value = await session.scalar(
        select(AgentVersion)
        .where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.status.in_(["development", "testing", "release_candidate"]),
        )
        .order_by(AgentVersion.created_at.desc())
        .limit(1)
    )
    if value is None and create:
        value = await production_repository.create_agent_version(
            session,
            agent=agent,
            version=await production_repository.next_agent_version(session, agent_id),
            description="Console BFF Draft",
            created_by="console-bff",
        )
    if create and value is not None and int(value.snapshot.get("format_version") or 1) == 1:
        value.snapshot = await _snapshot_v2(session, agent, value.snapshot)
        value.snapshot_format_version = 2
        await session.commit()
        await session.refresh(value)
    return value


async def _snapshot_v2(
    session: AsyncSession,
    agent: Agent,
    legacy: dict[str, Any],
) -> dict[str, Any]:
    skill_ids = legacy.get("skill_ids") if isinstance(legacy.get("skill_ids"), list) else []
    skills: list[dict[str, str]] = []
    for skill_id in skill_ids:
        version = await session.scalar(
            select(SkillVersion)
            .where(SkillVersion.skill_id == str(skill_id))
            .order_by(SkillVersion.created_at.desc())
            .limit(1)
        )
        if version is not None:
            skills.append({"skill_id": version.skill_id, "skill_version_id": str(version.id), "version": version.version})
    runtime = dict(legacy.get("runtime") or {})
    runtime["required_features"] = ["tool_call", "structured_output"] if skills else []
    return {
        **legacy,
        "format_version": 2,
        "skills": skills,
        "capability_bindings": [],
        "resource_scope_revisions": [],
        "policy_set_revisions": [],
        "runtime": runtime,
        "resolution_digest": None,
    }


async def _required(session: AsyncSession, model: Any, identifier: Any, detail: str) -> Any:
    value = await session.get(model, identifier)
    if value is None:
        raise HTTPException(status_code=404, detail=detail)
    return value


async def _commit(session: AsyncSession, conflict: str) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=conflict) from exc


def _validate_contract(input_schema: dict[str, Any], output_schema: dict[str, Any], ui_schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(input_schema or {})
        Draft202012Validator.check_schema(output_schema or {})
    except SchemaError as exc:
        raise HTTPException(status_code=422, detail=f"Capability JSON Schema 无效：{exc.message}") from exc
    if _contains_script(ui_schema):
        raise HTTPException(status_code=422, detail="UI Schema 不允许包含脚本或事件处理器")


def _contains_script(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower().startswith("on")
            or str(key).lower() in {"script", "javascript", "html"}
            or _contains_script(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_script(item) for item in value)
    return False


def _cipher() -> ModelSecretCipher:
    configured = get_settings().model_registry_encryption_key
    if configured is None:
        raise HTTPException(status_code=503, detail="Fernet 加密主密钥未配置")
    try:
        return ModelSecretCipher(configured.get_secret_value())
    except ModelSecretError as exc:
        raise HTTPException(status_code=503, detail="Fernet 加密主密钥无效") from exc


def _mask_secret(secret: str) -> str:
    return f"已配置 ····{secret[-4:]}" if len(secret) >= 4 else "已配置"


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def _validate_endpoint(endpoint: str) -> None:
    try:
        parsed = httpx.URL(endpoint)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Connector Endpoint 无效") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.host or parsed.userinfo:
        raise HTTPException(status_code=422, detail="Connector Endpoint 仅允许无内嵌凭据的 HTTP/HTTPS 地址")


def _credential_headers(
    revision: ConnectorInstanceRevision,
    credential: ConnectorCredential | None,
) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if credential is None:
        return headers
    secret = _cipher().decrypt(credential.encrypted_payload)
    if revision.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif revision.auth_type == "header":
        name = str((revision.connection_config or {}).get("auth_header") or "X-API-Key")
        if name.lower() in {"host", "content-length", "connection"}:
            raise ValueError("unsafe credential header")
        headers[name] = secret
    return headers

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from jsonschema import Draft202012Validator, SchemaError

from app.api.capabilities import _draft_version, _snapshot_v2
from app.capabilities.resolver import resolve_agent_capabilities
from app.db.models import (
    Agent,
    AgentCapabilityBinding,
    AgentRuntime,
    AgentVersion,
    Capability,
    CapabilityImplementation,
    CapabilityInvocation,
    CapabilityVersion,
    Connector,
    ConnectorInstance,
    ConnectorInstanceRevision,
    ConnectorOperation,
    ExecutionLog,
    ModelRegistration,
    Skill,
    ResourceScope,
    ResourceScopeRevision,
)
from app.db.session import get_session
from app.repositories import production as production_repository
from app.schemas.agent import AgentRunRequest
from app.config import get_settings
from app.database_connections import POSTGRES_MCP_TOOLS
from app.schemas.database_connection import DatabaseAgentBindingsUpdate


def require_console_bff() -> None:
    if not get_settings().console_bff_enabled:
        raise HTTPException(status_code=404, detail="Console BFF 尚未启用")


router = APIRouter(
    prefix="/api/console",
    tags=["console-bff"],
    dependencies=[Depends(require_console_bff)],
)


async def _database_scope_context(
    session: AsyncSession,
    scope_revision: ResourceScopeRevision,
) -> tuple[dict[str, Any], UUID]:
    scope = await session.get(ResourceScope, scope_revision.resource_scope_id)
    if (
        scope is None
        or scope.resource_type != "postgresql_database"
        or scope.owner_type != "connector_instance"
    ):
        raise HTTPException(status_code=422, detail="数据库 Binding 必须使用 PostgreSQL 数据库 Scope")
    if scope.current_revision_id != scope_revision.id:
        raise HTTPException(status_code=409, detail="数据库 Scope Revision 已过期，请选择当前 Revision")
    try:
        instance_id = UUID(scope.owner_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="数据库 Scope 所属连接无效") from exc
    instance = await session.get(ConnectorInstance, instance_id)
    connector = await session.get(Connector, instance.connector_id) if instance else None
    if instance is None or connector is None or connector.type != "postgresql_mcp":
        raise HTTPException(status_code=422, detail="数据库 Scope 未关联 PostgreSQL MCP 连接")
    if not instance.enabled or instance.health_status != "healthy":
        raise HTTPException(status_code=409, detail="数据库连接未启用或健康检查未通过")
    definition = scope_revision.scope_definition or {}
    revision_id = definition.get("connector_revision_id")
    if (
        not isinstance(revision_id, str)
        or instance.current_revision_id is None
        or revision_id != str(instance.current_revision_id)
    ):
        raise HTTPException(status_code=409, detail="数据库 Scope 与当前 Connector Revision 不匹配")
    return definition, instance.current_revision_id


async def _capability_binding_display_context(
    session: AsyncSession,
    binding: AgentCapabilityBinding,
) -> dict[str, str | None]:
    scope_revision = (
        await session.get(ResourceScopeRevision, binding.resource_scope_revision_id)
        if binding.resource_scope_revision_id
        else None
    )
    scope = (
        await session.get(ResourceScope, scope_revision.resource_scope_id)
        if scope_revision is not None
        else None
    )
    implementation = (
        await session.get(CapabilityImplementation, binding.implementation_id)
        if binding.implementation_id
        else None
    )
    connector_revision = (
        await session.get(
            ConnectorInstanceRevision,
            implementation.connector_instance_revision_id,
        )
        if implementation is not None
        else None
    )
    connector_instance = (
        await session.get(ConnectorInstance, connector_revision.connector_instance_id)
        if connector_revision is not None
        else None
    )
    scope_definition = scope_revision.scope_definition if scope_revision is not None else {}
    database_name = scope_definition.get("database") if isinstance(scope_definition, dict) else None
    values = {
        "connection_name": connector_instance.name if connector_instance is not None else None,
        "database": database_name if isinstance(database_name, str) else None,
        "scope_name": scope.name if scope is not None else None,
    }
    values["scope_summary"] = " · ".join(value for value in values.values() if value) or (
        "已配置资源范围" if binding.resource_scope_revision_id else "未限制资源范围"
    )
    return values


def _require_database_operation_permission(
    definition: dict[str, Any],
    operation: str,
) -> None:
    required_permission = {
        "describe_table": "describe",
        "preview_table": "preview",
        "select": "query",
        "explain": "query",
    }.get(operation)
    permissions = definition.get("permissions")
    if (
        required_permission is not None
        and (
            not isinstance(permissions, dict)
            or not bool(permissions.get(required_permission))
        )
    ):
        raise HTTPException(
            status_code=422,
            detail=f"数据库 Scope 未授权工具 {operation}",
        )


@router.get("/workbench")
async def workbench(session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    agent_count = int(await session.scalar(select(func.count(Agent.id))) or 0)
    execution_count = int(await session.scalar(select(func.count(ExecutionLog.id))) or 0)
    failed_count = int(
        await session.scalar(
            select(func.count(ExecutionLog.id)).where(ExecutionLog.status == "failed")
        )
        or 0
    )
    recent = list(
        await session.scalars(
            select(ExecutionLog).order_by(ExecutionLog.started_at.desc()).limit(8)
        )
    )
    needs_attention = list(
        await session.scalars(
            select(ConnectorInstance)
            .where(ConnectorInstance.health_status.in_(["degraded", "offline"]))
            .order_by(ConnectorInstance.updated_at.desc())
            .limit(8)
        )
    )
    return {
        "summary": {
            "agents": agent_count,
            "executions": execution_count,
            "failed_executions": failed_count,
            "connections_needing_attention": len(needs_attention),
        },
        "recent_runs": [
            {
                "id": str(item.id),
                "agent_id": item.agent_id,
                "status": item.status,
                "runtime_type": item.runtime_type,
                "started_at": item.started_at,
                "finished_at": item.finished_at,
            }
            for item in recent
        ],
        "needs_attention": [
            {
                "type": "connection",
                "id": str(item.id),
                "label": item.name,
                "state": item.health_status,
            }
            for item in needs_attention
        ],
    }


@router.get("/agents")
async def console_agents(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    agents = list(await session.scalars(select(Agent).order_by(Agent.updated_at.desc())))
    values: list[dict[str, Any]] = []
    for agent in agents:
        draft = await _draft_version(session, agent.id, create=False)
        preflight = (
            (await resolve_agent_capabilities(session, draft)).as_dict()
            if draft is not None
            else {"state": "NEEDS_CONFIGURATION", "issues": []}
        )
        values.append(
            {
                "id": agent.id,
                "name": agent.name,
                "description": agent.description,
                "status": agent.status,
                "runtime_type": agent.runtime_type,
                "current_version_id": str(agent.current_version_id) if agent.current_version_id else None,
                "preflight_state": preflight["state"],
                "updated_at": agent.updated_at,
            }
        )
    return values


@router.get("/agents/{agent_id}/editor")
async def agent_editor(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    draft = await _draft_version(session, agent_id, create=False)
    version, version_source = await _editor_version(session, agent, draft)
    resolution = await resolve_agent_capabilities(session, version) if version is not None else None
    bindings = list(
        await session.scalars(
            select(AgentCapabilityBinding)
            .where(AgentCapabilityBinding.agent_version_id == version.id)
            .order_by(AgentCapabilityBinding.tool_alias)
        )
    ) if version is not None else []
    capability_rows: list[dict[str, Any]] = []
    resolved_by_binding = {item.binding_id: item for item in resolution.tools} if resolution else {}
    for binding in bindings:
        capability_version = await session.get(CapabilityVersion, binding.capability_version_id)
        capability = (
            await session.get(Capability, capability_version.capability_id)
            if capability_version
            else None
        )
        resolved = resolved_by_binding.get(str(binding.id))
        display_context = await _capability_binding_display_context(session, binding)
        capability_rows.append(
            {
                "binding_id": str(binding.id),
                "tool_alias": binding.tool_alias,
                "key": capability.key if capability else "unknown",
                "label": capability.display_name if capability else "未知能力",
                "description": capability.description if capability else None,
                "version": capability_version.version if capability_version else None,
                "state": "READY" if resolved else "NEEDS_CONFIGURATION",
                "source_label": _source_label(binding.source_type),
                **display_context,
                "requires_user_action": resolved is None,
                "advanced": {
                    "implementation_id": str(binding.implementation_id) if binding.implementation_id else None,
                    "scope_revision_id": str(binding.resource_scope_revision_id) if binding.resource_scope_revision_id else None,
                },
            }
        )
    preflight = await _console_preflight(session, agent, version, resolution) if resolution else {
        "state": "NEEDS_CONFIGURATION",
        "issues": [{"code": "DRAFT_REQUIRED", "path": "agent", "message": "请先保存草稿", "severity": "error"}],
    }
    return {
        "agent": {
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "status": agent.status,
            "version": version.version if version else None,
            "draft_version_id": str(draft.id) if draft else None,
            "display_version_id": str(version.id) if version else None,
            "version_source": version_source,
        },
        "sections": {
            "identity": {
                "name": agent.name,
                "description": agent.description,
                "role": agent.role,
                "system_prompt": agent.system_prompt,
            },
            "behavior": {
                "runtime_type": agent.runtime_type,
                "runtime_id": str(agent.runtime_id) if agent.runtime_id else None,
                "model": agent.model,
                "model_adapter": agent.model_adapter,
                "response_mode": agent.response_mode,
                "execution_mode": (version.snapshot.get("execution_mode") if version else None) or "autonomous",
            },
            "skills": [
                {"id": item.id, "name": item.name, "version": item.version}
                for item in agent.skills
            ],
            "capabilities": capability_rows,
            "input_output": {
                "input_schema": agent.input_schema,
                "output_schema": agent.output_schema,
            },
        },
        "preflight": preflight,
        "actions": {
            "can_test": preflight["state"] == "READY" and draft is not None,
            "can_publish": preflight["state"] == "READY" and draft is not None,
        },
    }


async def _editor_version(
    session: AsyncSession,
    agent: Agent,
    draft: AgentVersion | None,
) -> tuple[AgentVersion | None, str | None]:
    if draft is not None:
        return draft, "draft"
    if agent.current_version_id is None:
        return None, None
    published = await session.get(AgentVersion, agent.current_version_id)
    return (published, "published") if published is not None else (None, None)


@router.patch("/agents/{agent_id}/editor/{section}")
async def update_agent_editor_section(
    agent_id: str,
    section: str,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    if section == "identity":
        for key in ("name", "description", "role", "system_prompt"):
            if key in payload:
                setattr(agent, key, payload[key])
    elif section == "behavior":
        for key in ("runtime_type", "model", "model_adapter", "response_mode"):
            if key in payload:
                setattr(agent, key, payload[key])
        if "runtime_id" in payload:
            agent.runtime_id = UUID(str(payload["runtime_id"])) if payload["runtime_id"] else None
        if "runtime_config" in payload and isinstance(payload["runtime_config"], dict):
            agent.runtime_config = payload["runtime_config"]
    elif section == "skills":
        skill_ids = payload.get("skill_ids")
        if not isinstance(skill_ids, list) or any(not isinstance(item, str) for item in skill_ids):
            raise HTTPException(status_code=422, detail="skill_ids 必须是字符串数组")
        skills = list(await session.scalars(select(Skill).where(Skill.id.in_(skill_ids)))) if skill_ids else []
        if len(skills) != len(set(skill_ids)):
            raise HTTPException(status_code=422, detail="包含不存在的 Skill")
        agent.skills = skills
    elif section == "input-output":
        if not isinstance(payload.get("input_schema"), dict) or not isinstance(payload.get("output_schema"), dict):
            raise HTTPException(status_code=422, detail="输入输出 Schema 必须是对象")
        agent.input_schema = payload["input_schema"]
        agent.output_schema = payload["output_schema"]
    elif section not in {"capabilities", "advanced"}:
        raise HTTPException(status_code=404, detail="Editor Section 不存在")
    await session.commit()
    draft = await _draft_version(session, agent_id, create=True)
    assert draft is not None
    current = draft.snapshot or {}
    rebuilt = await _snapshot_v2(
        session,
        agent,
        await production_repository.build_agent_snapshot(session, agent),
    )
    draft.snapshot = {
        **rebuilt,
        "capability_bindings": current.get("capability_bindings", []),
        "resource_scope_revisions": current.get("resource_scope_revisions", []),
        "policy_set_revisions": current.get("policy_set_revisions", []),
        "execution_mode": payload.get("execution_mode", current.get("execution_mode", "autonomous")),
        "resolution_digest": None,
    }
    draft.snapshot_format_version = 2
    draft.resolution_digest = None
    await session.commit()
    return await agent_editor(agent_id, session)


@router.get("/agents/{agent_id}/available-components")
async def available_components(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    if await session.get(Agent, agent_id) is None:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    capabilities = (
        await session.execute(
            select(Capability, CapabilityVersion)
            .join(CapabilityVersion, CapabilityVersion.capability_id == Capability.id)
            .where(CapabilityVersion.status == "published")
            .order_by(Capability.display_name)
        )
    ).all()
    database_scopes = (
        await session.execute(
            select(ResourceScope, ResourceScopeRevision)
            .join(ResourceScopeRevision, ResourceScopeRevision.id == ResourceScope.current_revision_id)
            .where(
                ResourceScope.resource_type == "postgresql_database",
                ResourceScope.owner_type == "connector_instance",
            )
            .order_by(ResourceScope.name)
        )
    ).all()
    database_components: list[dict[str, Any]] = []
    for scope, revision in database_scopes:
        try:
            instance_id = UUID(str(scope.owner_id))
        except (ValueError, TypeError):
            continue
        instance = await session.get(ConnectorInstance, instance_id)
        connector = await session.get(Connector, instance.connector_id) if instance else None
        definition = revision.scope_definition or {}
        if (
            instance is None
            or connector is None
            or connector.type != "postgresql_mcp"
            or not instance.enabled
            or definition.get("connector_revision_id")
            != (str(instance.current_revision_id) if instance.current_revision_id else None)
        ):
            continue
        database_components.append(
            {
                "connection_id": str(instance.id),
                "connection_name": instance.name,
                "status": "READY" if instance.health_status == "healthy" else instance.health_status.upper(),
                "scope_revision_id": str(revision.id),
                "scope_name": scope.name,
                "database": definition.get("database"),
                "schemas": definition.get("schemas", {}),
                "permissions": definition.get("permissions", {}),
                "limits": definition.get("limits", {}),
                "tools": [
                    {
                        "operation": operation,
                        "suffix": operation,
                        "label": specification["label"],
                    }
                    for operation, specification in POSTGRES_MCP_TOOLS.items()
                ],
            }
        )
    return {
        "skills": [
            {"id": item.id, "name": item.name, "version": item.version}
            for item in await session.scalars(select(Skill).order_by(Skill.name))
        ],
        "capabilities": [
            {
                "id": str(version.id),
                "key": capability.key,
                "label": capability.display_name,
                "description": capability.description,
                "version": version.version,
                "input_schema": version.input_schema,
                "ui_schema": version.ui_schema,
            }
            for capability, version in capabilities
        ],
        "runtimes": [
            {
                "id": str(item.id),
                "name": item.name,
                "type": item.type,
                "version": item.version,
                "status": item.status,
            }
            for item in await session.scalars(select(AgentRuntime).order_by(AgentRuntime.name))
        ],
        "database_connections": database_components,
    }


@router.put("/agents/{agent_id}/database-bindings")
async def update_database_bindings(
    agent_id: str,
    payload: DatabaseAgentBindingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    version = await _draft_version(session, agent_id, create=True)
    assert version is not None
    if version.status != "development":
        raise HTTPException(status_code=409, detail="只有 Development Draft 可以修改数据库 Binding")
    existing = list(
        await session.scalars(
            select(AgentCapabilityBinding).where(AgentCapabilityBinding.agent_version_id == version.id)
        )
    )
    preserved: list[AgentCapabilityBinding] = []
    for item in existing:
        capability_version = await session.get(CapabilityVersion, item.capability_version_id)
        capability = await session.get(Capability, capability_version.capability_id) if capability_version else None
        if capability is not None and capability.key.startswith("database."):
            await session.delete(item)
        else:
            preserved.append(item)
    aliases = {item.tool_alias for item in preserved}
    created: list[AgentCapabilityBinding] = []
    for database_binding in payload.bindings:
        try:
            scope_revision_id = UUID(database_binding.scope_revision_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="数据库 Scope Revision ID 无效") from exc
        scope = await session.get(ResourceScopeRevision, scope_revision_id)
        if scope is None:
            raise HTTPException(status_code=404, detail="数据库 Scope Revision 不存在")
        definition, connector_revision_id = await _database_scope_context(session, scope)
        for operation_key in database_binding.operations:
            _require_database_operation_permission(definition, operation_key)
            specification = POSTGRES_MCP_TOOLS[operation_key]
            alias = f"{database_binding.tool_prefix}_{operation_key}"
            if alias in aliases or len(alias) > 128:
                raise HTTPException(status_code=422, detail=f"Tool Alias 冲突或过长：{alias}")
            aliases.add(alias)
            row = (
                await session.execute(
                    select(CapabilityVersion, CapabilityImplementation)
                    .join(Capability, Capability.id == CapabilityVersion.capability_id)
                    .join(
                        CapabilityImplementation,
                        CapabilityImplementation.capability_version_id == CapabilityVersion.id,
                    )
                    .join(
                        ConnectorOperation,
                        ConnectorOperation.id == CapabilityImplementation.connector_operation_id,
                    )
                    .where(
                        Capability.key == specification["capability"],
                        CapabilityVersion.version == "1.0.0",
                        CapabilityVersion.status == "published",
                        CapabilityImplementation.connector_instance_revision_id == connector_revision_id,
                        CapabilityImplementation.status == "active",
                        ConnectorOperation.path_or_tool == specification["tool"],
                    )
                    .limit(1)
                )
            ).first()
            if row is None:
                raise HTTPException(status_code=409, detail=f"数据库能力 {operation_key} 没有当前连接实现")
            capability_version, implementation = row
            limits = definition.get("limits") if isinstance(definition.get("limits"), dict) else {}
            value = AgentCapabilityBinding(
                agent_version_id=version.id,
                tool_alias=alias,
                capability_version_id=capability_version.id,
                implementation_mode="PINNED",
                implementation_id=implementation.id,
                resource_scope_revision_id=scope.id,
                parameter_policy={},
                quota_policy={
                    "calls_per_execution": 100,
                    "calls_per_minute": int(limits.get("requests_per_minute") or 60),
                    "max_concurrency": 2,
                },
                approval_policy={},
                enabled=True,
                source_type="direct",
                source_ref_id=str(scope.id),
            )
            session.add(value)
            created.append(value)
    await session.commit()
    for item in created:
        await session.refresh(item)
    return [
        {
            "id": str(item.id),
            "tool_alias": item.tool_alias,
            "capability_version_id": str(item.capability_version_id),
            "implementation_id": str(item.implementation_id),
            "resource_scope_revision_id": str(item.resource_scope_revision_id),
        }
        for item in created
    ]


@router.post("/agents/{agent_id}/auto-configure")
async def auto_configure(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    editor = await agent_editor(agent_id, session)
    return {
        "applied": False,
        "message": "已生成配置建议，资源范围仍需管理员确认",
        "suggestions": [issue for issue in editor["preflight"].get("issues", [])],
        "editor": editor,
    }


@router.post("/agents/{agent_id}/preflight")
async def console_preflight(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    draft = await _draft_version(session, agent_id, create=False)
    if draft is None:
        return {"state": "NEEDS_CONFIGURATION", "issues": [{"code": "DRAFT_REQUIRED", "path": "agent", "message": "请先保存 Agent 草稿", "severity": "error"}]}
    agent = await session.get(Agent, agent_id)
    assert agent is not None
    resolution = await resolve_agent_capabilities(session, draft)
    return await _console_preflight(session, agent, draft, resolution)


@router.post("/agents/{agent_id}/test")
async def console_test_agent(
    agent_id: str,
    payload: AgentRunRequest,
    session: AsyncSession = Depends(get_session),
) -> Any:
    draft = await _draft_version(session, agent_id, create=True)
    if draft is None:
        raise HTTPException(status_code=409, detail="请先保存 Agent 草稿")
    resolution = await resolve_agent_capabilities(session, draft)
    agent = await session.get(Agent, agent_id)
    assert agent is not None
    preflight = await _console_preflight(session, agent, draft, resolution)
    if preflight["state"] != "READY":
        raise HTTPException(status_code=409, detail="Preflight 未通过")
    if draft.status == "development":
        draft = await production_repository.transition_agent_version(session, draft, "testing")
    from app.api.production import run_agent_version

    return await run_agent_version(agent_id, draft.version, payload, session)


@router.post("/agents/{agent_id}/publish")
async def console_publish_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    agent = await session.get(Agent, agent_id)
    draft = await _draft_version(session, agent_id, create=True)
    if agent is None or draft is None:
        raise HTTPException(status_code=404, detail="Agent 或草稿不存在")
    resolution = await resolve_agent_capabilities(session, draft)
    preflight = await _console_preflight(session, agent, draft, resolution)
    if preflight["state"] != "READY":
        raise HTTPException(status_code=409, detail={"message": "Preflight 未通过", "issues": preflight["issues"]})
    draft.snapshot = {
        **draft.snapshot,
        "capability_bindings": [tool.as_dict() for tool in resolution.tools],
        "resource_scope_revisions": sorted(
            {tool.resource_scope_revision_id for tool in resolution.tools if tool.resource_scope_revision_id}
        ),
        "resolution_digest": resolution.resolution_digest,
    }
    draft.snapshot_format_version = 2
    draft.resolution_digest = resolution.resolution_digest
    if draft.status == "development":
        draft.status = "testing"
    if draft.status == "testing":
        draft.status = "release_candidate"
    await session.commit()
    published = await production_repository.publish_agent(session, agent=agent, version=draft)
    return {
        "id": str(published.id),
        "version": published.version,
        "status": published.status,
        "resolution_digest": published.resolution_digest,
    }


@router.get("/executions/{execution_id}")
async def console_execution(
    execution_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    execution = await session.get(ExecutionLog, execution_id)
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution 不存在")
    invocations = list(
        await session.scalars(
            select(CapabilityInvocation)
            .where(CapabilityInvocation.execution_id == execution_id)
            .order_by(CapabilityInvocation.created_at)
        )
    )
    return {
        "execution": {
            "id": str(execution.id),
            "agent_id": execution.agent_id,
            "status": execution.status,
            "input": execution.input,
            "output": execution.output,
            "error": execution.error,
            "runtime_type": execution.runtime_type,
            "started_at": execution.started_at,
            "finished_at": execution.finished_at,
        },
        "timeline": [
            {
                "id": str(item.id),
                "type": "capability",
                "label": item.capability_key,
                "tool_alias": item.tool_alias,
                "status": item.status,
                "latency_ms": item.latency_ms,
                "error_code": item.error_code,
                "technical": {
                    "provider_revision": str(item.connector_instance_revision_id) if item.connector_instance_revision_id else None,
                    "scope_revision": str(item.resource_scope_revision_id) if item.resource_scope_revision_id else None,
                    "cache_hit": item.cache_hit,
                },
            }
            for item in invocations
        ],
    }


@router.get("/platform/connections")
async def console_connections(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    connectors = list(await session.scalars(select(Connector).order_by(Connector.display_name)))
    values: list[dict[str, Any]] = []
    for connector in connectors:
        instances = list(
            await session.scalars(
                select(ConnectorInstance).where(ConnectorInstance.connector_id == connector.id)
            )
        )
        operation_count = int(
            await session.scalar(
                select(func.count()).select_from(CapabilityImplementation)
                .join(ConnectorInstanceRevision, ConnectorInstanceRevision.id == CapabilityImplementation.connector_instance_revision_id)
                .join(ConnectorInstance, ConnectorInstance.id == ConnectorInstanceRevision.connector_instance_id)
                .where(ConnectorInstance.connector_id == connector.id)
            )
            or 0
        )
        values.append(
            {
                "id": str(connector.id),
                "key": connector.key,
                "name": connector.display_name,
                "type": connector.type,
                "status": _connection_status(instances),
                "capability_count": operation_count,
                "instances": len(instances),
                "updated_at": connector.updated_at,
            }
        )
    return values


@router.get("/platform/connections/{connector_id}")
async def console_connection_detail(
    connector_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    connector = await session.get(Connector, connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="连接不存在")
    instances = list(
        await session.scalars(
            select(ConnectorInstance).where(ConnectorInstance.connector_id == connector.id)
        )
    )
    return {
        "id": str(connector.id),
        "key": connector.key,
        "name": connector.display_name,
        "type": connector.type,
        "description": connector.description,
        "status": _connection_status(instances),
        "instances": [
            {
                "id": str(item.id),
                "name": item.name,
                "environment": item.environment,
                "health": item.health_status,
                "enabled": item.enabled,
                "current_revision_id": str(item.current_revision_id) if item.current_revision_id else None,
            }
            for item in instances
        ],
    }


def _source_label(source: str) -> str:
    return {
        "direct": "用户直接添加",
        "skill": "由 Skill 自动需要",
        "workflow": "由 Workflow 自动需要",
        "template": "由模板添加",
        "legacy": "从旧 MCP 迁移",
    }.get(source, source)


def _connection_status(instances: list[ConnectorInstance]) -> str:
    states = {item.health_status for item in instances if item.enabled}
    if "offline" in states:
        return "UNAVAILABLE"
    if "degraded" in states or "unknown" in states or not states:
        return "NEEDS_CONFIGURATION"
    return "READY"


async def _console_preflight(
    session: AsyncSession,
    agent: Agent,
    draft: AgentVersion,
    resolution,
) -> dict[str, Any]:
    result = resolution.as_dict()
    issues = list(result.get("issues") or [])
    model = await session.get(ModelRegistration, agent.model)
    if model is None or not model.is_enabled:
        issues.append({"code": "MODEL_UNAVAILABLE", "path": "behavior.model", "message": "所选模型未注册或已停用", "severity": "error"})
    elif model.adapter != agent.model_adapter:
        issues.append({"code": "MODEL_ADAPTER_MISMATCH", "path": "behavior.model_adapter", "message": "模型 Adapter 与注册配置不一致", "severity": "error"})
    for path, schema in (("input_output.input_schema", agent.input_schema), ("input_output.output_schema", agent.output_schema)):
        try:
            Draft202012Validator.check_schema(schema or {})
        except SchemaError as exc:
            issues.append({"code": "SCHEMA_INVALID", "path": path, "message": f"JSON Schema 无效：{exc.message}", "severity": "error"})
    result["issues"] = issues
    result["state"] = "READY" if not any(item.get("severity") == "error" for item in issues) else "NEEDS_CONFIGURATION"
    return result

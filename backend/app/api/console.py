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
    ExecutionLog,
    ModelRegistration,
    Skill,
)
from app.db.session import get_session
from app.management import management_mode, require_platform_management_key
from app.repositories import production as production_repository
from app.schemas.agent import AgentRunRequest
from app.config import get_settings


def require_console_bff() -> None:
    if not get_settings().console_bff_enabled:
        raise HTTPException(status_code=404, detail="Console BFF 尚未启用")


router = APIRouter(
    prefix="/api/console",
    tags=["console-bff"],
    dependencies=[Depends(require_console_bff)],
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
        "mode": management_mode(),
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
    resolution = await resolve_agent_capabilities(session, draft) if draft is not None else None
    bindings = list(
        await session.scalars(
            select(AgentCapabilityBinding)
            .where(AgentCapabilityBinding.agent_version_id == draft.id)
            .order_by(AgentCapabilityBinding.tool_alias)
        )
    ) if draft is not None else []
    capability_rows: list[dict[str, Any]] = []
    resolved_by_binding = {item.binding_id: item for item in resolution.tools} if resolution else {}
    for binding in bindings:
        version = await session.get(CapabilityVersion, binding.capability_version_id)
        capability = await session.get(Capability, version.capability_id) if version else None
        resolved = resolved_by_binding.get(str(binding.id))
        capability_rows.append(
            {
                "binding_id": str(binding.id),
                "key": capability.key if capability else "unknown",
                "label": capability.display_name if capability else "未知能力",
                "description": capability.description if capability else None,
                "version": version.version if version else None,
                "state": "READY" if resolved else "NEEDS_CONFIGURATION",
                "source_label": _source_label(binding.source_type),
                "scope_summary": "已配置资源范围" if binding.resource_scope_revision_id else "未限制资源范围",
                "requires_user_action": resolved is None,
                "advanced": {
                    "implementation_id": str(binding.implementation_id) if binding.implementation_id else None,
                    "scope_revision_id": str(binding.resource_scope_revision_id) if binding.resource_scope_revision_id else None,
                },
            }
        )
    preflight = await _console_preflight(session, agent, draft, resolution) if resolution else {
        "state": "NEEDS_CONFIGURATION",
        "issues": [{"code": "DRAFT_REQUIRED", "path": "agent", "message": "请先保存草稿", "severity": "error"}],
    }
    return {
        "mode": management_mode(),
        "agent": {
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "status": agent.status,
            "version": draft.version if draft else None,
            "draft_version_id": str(draft.id) if draft else None,
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
                "execution_mode": (draft.snapshot.get("execution_mode") if draft else None) or "autonomous",
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
            "can_test": preflight["state"] == "READY",
            "can_publish": preflight["state"] == "READY" and draft is not None,
        },
    }


@router.patch("/agents/{agent_id}/editor/{section}")
async def update_agent_editor_section(
    agent_id: str,
    section: str,
    payload: dict[str, Any],
    _: None = Depends(require_platform_management_key),
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
    }


@router.post("/agents/{agent_id}/auto-configure")
async def auto_configure(
    agent_id: str,
    _: None = Depends(require_platform_management_key),
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
    _: None = Depends(require_platform_management_key),
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
    _: None = Depends(require_platform_management_key),
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

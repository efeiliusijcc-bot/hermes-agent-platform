from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentCapabilityBinding,
    AgentRuntime,
    AgentVersion,
    Capability,
    CapabilityImplementation,
    CapabilityVersion,
    ConnectorInstance,
    ConnectorInstanceRevision,
    ConnectorOperation,
    Connector,
    ResourceScopeRevision,
    RuntimeFeatureProfile,
    SkillCapabilityRequirement,
    SkillVersion,
)


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    path: str
    message: str
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class ResolvedCapability:
    binding_id: str
    tool_name: str
    capability_key: str
    capability_version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    implementation_id: str
    connector_operation_id: str
    connector_instance_revision_id: str
    resource_scope_revision_id: str | None
    parameter_policy: dict[str, Any]
    quota_policy: dict[str, Any]
    approval_policy: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class CapabilityResolution:
    agent_version_id: str
    format_version: int
    legacy: bool
    tools: tuple[ResolvedCapability, ...] = ()
    issues: tuple[PreflightIssue, ...] = ()
    resolution_digest: str = ""
    runtime_features: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_version_id": self.agent_version_id,
            "format_version": self.format_version,
            "legacy": self.legacy,
            "state": "READY" if self.ready else "NEEDS_CONFIGURATION",
            "tools": [tool.as_dict() for tool in self.tools],
            "issues": [issue.as_dict() for issue in self.issues],
            "resolution_digest": self.resolution_digest,
            "runtime_features": self.runtime_features,
        }


async def resolve_agent_capabilities(
    session: AsyncSession,
    agent_version: AgentVersion,
) -> CapabilityResolution:
    snapshot = agent_version.snapshot or {}
    format_version = int(snapshot.get("format_version") or agent_version.snapshot_format_version or 1)
    if format_version == 1:
        digest = _digest({"format_version": 1, "agent_version_id": str(agent_version.id)})
        return CapabilityResolution(
            agent_version_id=str(agent_version.id),
            format_version=1,
            legacy=True,
            resolution_digest=digest,
        )

    issues: list[PreflightIssue] = []
    runtime_features = await _runtime_features(session, snapshot, issues)
    rows = (
        await session.execute(
            select(
                AgentCapabilityBinding,
                CapabilityVersion,
                Capability,
            )
            .join(CapabilityVersion, CapabilityVersion.id == AgentCapabilityBinding.capability_version_id)
            .join(Capability, Capability.id == CapabilityVersion.capability_id)
            .where(
                AgentCapabilityBinding.agent_version_id == agent_version.id,
                AgentCapabilityBinding.enabled.is_(True),
            )
            .order_by(AgentCapabilityBinding.tool_alias)
        )
    ).all()
    bindings_by_capability = {capability.key: binding for binding, _, capability in rows}
    bindings_by_alias = {binding.tool_alias: binding for binding, _, _ in rows}
    if rows and not runtime_features.get("capability_gateway"):
        runtime_type = str(runtime_features.get("runtime_type") or "当前")
        issues.append(
            PreflightIssue(
                "RUNTIME_FEATURE_MISMATCH",
                "runtime.required_features.capability_gateway",
                f"{runtime_type} Runtime 尚未提供不向模型暴露 Token 的动态 Capability Dispatcher",
            )
        )
    await _validate_skill_requirements(
        session,
        snapshot,
        bindings_by_capability,
        bindings_by_alias,
        issues,
    )

    tools: list[ResolvedCapability] = []
    for binding, version, capability in rows:
        if version.status not in {"published", "deprecated"}:
            issues.append(
                PreflightIssue(
                    code="CONTRACT_VERSION_MISMATCH",
                    path=f"capability_bindings.{binding.tool_alias}",
                    message=f"能力 {capability.key}@{version.version} 尚未发布",
                )
            )
            continue
        implementation = await _implementation(session, binding, version.id)
        if implementation is None:
            issues.append(
                PreflightIssue(
                    code="CAPABILITY_IMPLEMENTATION_MISSING",
                    path=f"capability_bindings.{binding.tool_alias}",
                    message=f"能力 {capability.key} 没有可用实现",
                )
            )
            continue
        operation = await session.get(ConnectorOperation, implementation.connector_operation_id)
        revision = await session.get(ConnectorInstanceRevision, implementation.connector_instance_revision_id)
        if operation is None or revision is None:
            issues.append(
                PreflightIssue(
                    code="CAPABILITY_IMPLEMENTATION_MISSING",
                    path=f"capability_bindings.{binding.tool_alias}",
                    message=f"能力 {capability.key} 的连接实现不完整",
                )
            )
            continue
        instance = await session.get(ConnectorInstance, revision.connector_instance_id)
        if instance is None or not instance.enabled or instance.health_status in {"offline"}:
            issues.append(
                PreflightIssue(
                    code="PROVIDER_UNHEALTHY",
                    path=f"capability_bindings.{binding.tool_alias}",
                    message=f"能力 {capability.key} 的连接当前不可用",
                )
            )
        connector = await session.get(Connector, operation.connector_id)
        scope_revision = (
            await session.get(ResourceScopeRevision, binding.resource_scope_revision_id)
            if binding.resource_scope_revision_id
            else None
        )
        if connector is not None and connector.type == "postgresql_mcp":
            if scope_revision is None:
                issues.append(
                    PreflightIssue(
                        code="RESOURCE_SCOPE_REQUIRED",
                        path=f"capability_bindings.{binding.tool_alias}.resource_scope_revision_id",
                        message=f"数据库能力 {capability.key} 必须绑定单数据库 Scope Revision",
                    )
                )
            elif str((scope_revision.scope_definition or {}).get("connector_revision_id")) != str(revision.id):
                issues.append(
                    PreflightIssue(
                        code="RESOURCE_SCOPE_MISMATCH",
                        path=f"capability_bindings.{binding.tool_alias}.resource_scope_revision_id",
                        message=f"数据库能力 {capability.key} 的 Scope 与 Connector Revision 不匹配",
                    )
                )
        tools.append(
            ResolvedCapability(
                binding_id=str(binding.id),
                tool_name=binding.tool_alias,
                capability_key=capability.key,
                capability_version=version.version,
                description=capability.description or capability.display_name,
                input_schema=version.input_schema or {},
                output_schema=version.output_schema or {},
                implementation_id=str(implementation.id),
                connector_operation_id=str(operation.id),
                connector_instance_revision_id=str(revision.id),
                resource_scope_revision_id=(
                    str(binding.resource_scope_revision_id)
                    if binding.resource_scope_revision_id
                    else None
                ),
                parameter_policy=binding.parameter_policy or {},
                quota_policy=binding.quota_policy or {},
                approval_policy=binding.approval_policy or {},
            )
        )

    digest_payload = {
        "agent_version_id": str(agent_version.id),
        "runtime_features": runtime_features,
        "tools": [tool.as_dict() for tool in tools],
    }
    return CapabilityResolution(
        agent_version_id=str(agent_version.id),
        format_version=2,
        legacy=False,
        tools=tuple(tools),
        issues=tuple(issues),
        resolution_digest=_digest(digest_payload),
        runtime_features=runtime_features,
    )


async def _runtime_features(
    session: AsyncSession,
    snapshot: dict[str, Any],
    issues: list[PreflightIssue],
) -> dict[str, Any]:
    runtime = snapshot.get("runtime") if isinstance(snapshot.get("runtime"), dict) else {}
    raw_runtime_id = runtime.get("runtime_id")
    required = runtime.get("required_features") if isinstance(runtime.get("required_features"), list) else []
    if not raw_runtime_id:
        issues.append(PreflightIssue("RUNTIME_REQUIRED", "runtime", "请选择可用 Runtime"))
        return {}
    try:
        runtime_id = UUID(str(raw_runtime_id))
    except ValueError:
        issues.append(PreflightIssue("RUNTIME_REQUIRED", "runtime.runtime_id", "Runtime ID 无效"))
        return {}
    runtime_record = await session.get(AgentRuntime, runtime_id)
    if runtime_record is None or runtime_record.status in {"offline", "disabled"}:
        issues.append(PreflightIssue("RUNTIME_UNAVAILABLE", "runtime", "当前 Runtime 不可用"))
        return {}
    profile = await session.scalar(
        select(RuntimeFeatureProfile)
        .where(
            RuntimeFeatureProfile.runtime_registry_id == runtime_record.id,
            RuntimeFeatureProfile.runtime_version == runtime_record.version,
        )
        .order_by(RuntimeFeatureProfile.observed_at.desc())
        .limit(1)
    )
    features = profile.features if profile is not None else {}
    for name in required:
        if not features.get(str(name)):
            issues.append(
                PreflightIssue(
                    "RUNTIME_FEATURE_MISMATCH",
                    f"runtime.required_features.{name}",
                    f"当前 Runtime 不支持 {name}",
                )
            )
    return features


async def _validate_skill_requirements(
    session: AsyncSession,
    snapshot: dict[str, Any],
    bindings_by_capability: dict[str, AgentCapabilityBinding],
    bindings_by_alias: dict[str, AgentCapabilityBinding],
    issues: list[PreflightIssue],
) -> None:
    raw_skills = snapshot.get("skills") if isinstance(snapshot.get("skills"), list) else []
    version_ids: list[UUID] = []
    for item in raw_skills:
        raw_id = item.get("skill_version_id") if isinstance(item, dict) else None
        if raw_id:
            try:
                version_ids.append(UUID(str(raw_id)))
            except ValueError:
                issues.append(PreflightIssue("SKILL_VERSION_INVALID", "skills", "Skill Version ID 无效"))
    if not version_ids:
        return
    requirements = list(
        await session.scalars(
            select(SkillCapabilityRequirement).where(
                SkillCapabilityRequirement.skill_version_id.in_(version_ids)
            )
        )
    )
    for requirement in requirements:
        if not requirement.required:
            continue
        binding = bindings_by_alias.get(requirement.alias) or bindings_by_capability.get(requirement.capability_key)
        if binding is None:
            issues.append(
                PreflightIssue(
                    "CAPABILITY_NOT_BOUND",
                    f"skills.capability_requirements.{requirement.alias}",
                    f"缺少所需能力 {requirement.capability_key}",
                )
            )
            continue
        version = await session.get(CapabilityVersion, binding.capability_version_id)
        if version is None or not version_satisfies(version.version, requirement.version_range):
            issues.append(
                PreflightIssue(
                    "CONTRACT_VERSION_MISMATCH",
                    f"skills.capability_requirements.{requirement.alias}",
                    f"能力 {requirement.capability_key} 版本不满足 {requirement.version_range}",
                )
            )


async def _implementation(
    session: AsyncSession,
    binding: AgentCapabilityBinding,
    capability_version_id: UUID,
) -> CapabilityImplementation | None:
    if binding.implementation_id:
        value = await session.get(CapabilityImplementation, binding.implementation_id)
        return value if value is not None and value.status == "active" else None
    return await session.scalar(
        select(CapabilityImplementation)
        .where(
            CapabilityImplementation.capability_version_id == capability_version_id,
            CapabilityImplementation.status == "active",
        )
        .order_by(CapabilityImplementation.priority.asc(), CapabilityImplementation.created_at.asc())
        .limit(1)
    )


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def version_satisfies(version: str, version_range: str) -> bool:
    current = _semver(version)
    expression = version_range.strip()
    if expression in {"", "*"}:
        return True
    for token in expression.split():
        match = re.fullmatch(r"(>=|<=|>|<|=)?(\d+\.\d+\.\d+)", token)
        if match is None:
            return False
        operator = match.group(1) or "="
        target = _semver(match.group(2))
        if operator == ">=" and not current >= target:
            return False
        if operator == "<=" and not current <= target:
            return False
        if operator == ">" and not current > target:
            return False
        if operator == "<" and not current < target:
            return False
        if operator == "=" and current != target:
            return False
    return True


def _semver(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        return (-1, -1, -1)
    return tuple(int(item) for item in match.groups())

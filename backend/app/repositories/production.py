from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    APIClient,
    APIKey,
    Agent,
    AgentAPIClient,
    AgentAPIVersion,
    AgentMetric,
    AgentPublication,
    AgentSchemaVersion,
    AgentVersion,
    AuditLog,
    MCPServer,
    Skill,
    agent_mcp,
    agent_skill,
)
from app.prompting import validate_prompt_template
from app.runtime.capabilities import normalize_capability_profile
from app.schemas.schema_validation import normalize_schema
from app.schemas.agent import validate_runtime_config


@dataclass(frozen=True)
class APIKeyAuthentication:
    client: APIClient
    api_key: APIKey


async def create_api_client(
    session: AsyncSession, *, name: str, owner: str, rate_limit_per_minute: int
) -> APIClient:
    value = APIClient(
        name=name,
        owner=owner,
        rate_limit_per_minute=rate_limit_per_minute,
        status="active",
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return value


async def get_api_client(session: AsyncSession, client_id: UUID) -> APIClient | None:
    return await session.get(APIClient, client_id)


async def list_api_clients(session: AsyncSession) -> list[APIClient]:
    return list(
        await session.scalars(select(APIClient).order_by(APIClient.created_at, APIClient.id))
    )


async def update_api_client(session: AsyncSession, client: APIClient, **values: Any) -> APIClient:
    for key, value in values.items():
        if value is not None:
            setattr(client, key, value)
    await session.commit()
    await session.refresh(client)
    return client


async def delete_api_client(session: AsyncSession, client: APIClient) -> None:
    await session.delete(client)
    await session.commit()


async def api_client_counts(session: AsyncSession, client_id: UUID) -> dict[str, Any]:
    key_count = await session.scalar(select(func.count(APIKey.id)).where(APIKey.client_id == client_id))
    agent_count = await session.scalar(
        select(func.count()).select_from(AgentAPIClient).where(AgentAPIClient.client_id == client_id)
    )
    calls = await session.execute(
        select(func.count(AuditLog.id), func.max(AuditLog.created_at)).where(AuditLog.client_id == client_id)
    )
    call_count, last_called_at = calls.one()
    return {
        "key_count": int(key_count or 0),
        "agent_count": int(agent_count or 0),
        "call_count": int(call_count or 0),
        "last_called_at": last_called_at,
    }


async def create_api_key(
    session: AsyncSession,
    client: APIClient,
    *,
    name: str,
    expires_at: datetime | None,
) -> tuple[APIKey, str]:
    plaintext = f"hap_{secrets.token_urlsafe(32)}"
    value = APIKey(
        client_id=client.id,
        name=name,
        key_hash=hash_api_key(plaintext),
        prefix=plaintext[:12],
        status="active",
        expires_at=expires_at,
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return value, plaintext


async def rotate_legacy_publication_key(
    session: AsyncSession,
    *,
    agent_id: str,
) -> tuple[AgentPublication, APIKey, str]:
    """Issue a compatibility key through the Phase 4 authorization model.

    The Phase 2 endpoint remains available for older operators, but every key
    it returns is now an ordinary API Client key.  This keeps revocation,
    binding checks, rate limiting, audit attribution, and one-time plaintext
    disclosure identical for old and new callers.
    """
    # Serialize compatibility-key rotation per Agent.  Locking the Agent first
    # also covers the first rotation, when neither the publication nor the
    # legacy API Client exists yet.
    await session.execute(select(Agent.id).where(Agent.id == agent_id).with_for_update())
    publication = await session.scalar(
        select(AgentPublication)
        .where(AgentPublication.agent_id == agent_id)
        # AgentPublication eagerly joins Agent for control-plane reads.  Limit
        # the lock target to the publication table so PostgreSQL does not try
        # to lock the nullable side of that LEFT OUTER JOIN.
        .with_for_update(of=AgentPublication)
    )
    if publication is None:
        publication = AgentPublication(agent_id=agent_id, status="draft")
        session.add(publication)

    client_name = f"legacy-{agent_id}"
    client = await session.scalar(
        select(APIClient).where(APIClient.name == client_name).with_for_update()
    )
    if client is None:
        client = APIClient(
            name=client_name,
            owner="legacy-publication",
            status="active",
            rate_limit_per_minute=60,
        )
        session.add(client)
        await session.flush()
    elif client.status != "active":
        raise ValueError("legacy API Client is not active")

    binding = await session.get(AgentAPIClient, (client.id, agent_id))
    if binding is None:
        session.add(AgentAPIClient(client_id=client.id, agent_id=agent_id, permission="invoke"))
    else:
        binding.permission = "invoke"

    now = datetime.now(timezone.utc)
    await session.execute(
        update(APIKey)
        .where(APIKey.client_id == client.id, APIKey.status == "active")
        .values(status="revoked", revoked_at=now)
    )
    plaintext = f"hap_{secrets.token_urlsafe(32)}"
    api_key = APIKey(
        client_id=client.id,
        name="legacy-publication-key",
        key_hash=hash_api_key(plaintext),
        prefix=plaintext[:12],
        status="active",
    )
    session.add(api_key)
    publication.api_key_hash = api_key.key_hash
    publication.api_key_prefix = api_key.prefix
    await session.commit()
    await session.refresh(publication)
    await session.refresh(api_key)
    return publication, api_key, plaintext


async def get_api_key(session: AsyncSession, client_id: UUID, key_id: UUID) -> APIKey | None:
    return await session.scalar(
        select(APIKey).where(APIKey.client_id == client_id, APIKey.id == key_id)
    )


async def list_api_keys(session: AsyncSession, client_id: UUID) -> list[APIKey]:
    return list(
        await session.scalars(
            select(APIKey)
            .where(APIKey.client_id == client_id)
            .order_by(APIKey.created_at, APIKey.id)
        )
    )


async def api_key_call_count(session: AsyncSession, key_id: UUID) -> int:
    value = await session.scalar(
        select(func.count(AuditLog.id)).where(AuditLog.api_key_id == key_id)
    )
    return int(value or 0)


async def revoke_api_key(session: AsyncSession, value: APIKey) -> APIKey:
    value.status = "revoked"
    value.revoked_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(value)
    return value


async def bind_agent(
    session: AsyncSession, *, client_id: UUID, agent_id: str, permission: str = "invoke"
) -> AgentAPIClient:
    value = await session.get(AgentAPIClient, (client_id, agent_id))
    if value is None:
        value = AgentAPIClient(client_id=client_id, agent_id=agent_id, permission=permission)
        session.add(value)
    else:
        value.permission = permission
    await session.commit()
    await session.refresh(value)
    return value


async def list_agent_bindings(session: AsyncSession, client_id: UUID) -> list[AgentAPIClient]:
    return list(
        await session.scalars(
            select(AgentAPIClient)
            .where(AgentAPIClient.client_id == client_id)
            .order_by(AgentAPIClient.created_at, AgentAPIClient.agent_id)
        )
    )


async def unbind_agent(session: AsyncSession, client_id: UUID, agent_id: str) -> bool:
    result = await session.execute(
        delete(AgentAPIClient).where(
            AgentAPIClient.client_id == client_id,
            AgentAPIClient.agent_id == agent_id,
        )
    )
    await session.commit()
    return bool(result.rowcount)


async def authenticate_api_key(
    session: AsyncSession, *, agent_id: str, presented_key: str
) -> APIKeyAuthentication | None:
    """Authenticate without exposing the stored digest to API serializers."""
    now = datetime.now(timezone.utc)
    value = await session.execute(
        select(APIClient, APIKey)
        .join(APIKey, APIKey.client_id == APIClient.id)
        .join(AgentAPIClient, AgentAPIClient.client_id == APIClient.id)
        .join(Agent, Agent.id == AgentAPIClient.agent_id)
        .where(
            APIKey.key_hash == hash_api_key(presented_key),
            APIKey.status == "active",
            APIClient.status == "active",
            AgentAPIClient.agent_id == agent_id,
            AgentAPIClient.permission == "invoke",
            Agent.status == "active",
            Agent.current_version_id.is_not(None),
            Agent.api_enabled.is_(True),
            (APIKey.expires_at.is_(None) | (APIKey.expires_at > now)),
        )
    )
    row = value.first()
    if row is None:
        return None
    client, api_key = row
    api_key.last_used_at = now
    await session.commit()
    return APIKeyAuthentication(client=client, api_key=api_key)


async def authenticate_client_key(
    session: AsyncSession, *, presented_key: str
) -> APIKeyAuthentication | None:
    """Validate key/client state independently from an Agent authorization."""
    now = datetime.now(timezone.utc)
    value = await session.execute(
        select(APIClient, APIKey)
        .join(APIKey, APIKey.client_id == APIClient.id)
        .where(
            APIKey.key_hash == hash_api_key(presented_key),
            APIKey.status == "active",
            APIClient.status == "active",
            (APIKey.expires_at.is_(None) | (APIKey.expires_at > now)),
        )
    )
    row = value.first()
    if row is None:
        return None
    client, api_key = row
    return APIKeyAuthentication(client=client, api_key=api_key)


async def has_invoke_permission(
    session: AsyncSession, *, client_id: UUID, agent_id: str
) -> bool:
    value = await session.scalar(
        select(AgentAPIClient.client_id)
        .join(Agent, Agent.id == AgentAPIClient.agent_id)
        .where(
            AgentAPIClient.client_id == client_id,
            AgentAPIClient.agent_id == agent_id,
            AgentAPIClient.permission == "invoke",
            Agent.status == "active",
            Agent.current_version_id.is_not(None),
            Agent.api_enabled.is_(True),
        )
    )
    return value is not None


async def record_public_call(
    session: AsyncSession,
    *,
    request_id: str,
    client_id: UUID | None,
    agent_id: str | None,
    status: str,
    latency_ms: int,
    token_usage: int | None,
    mcp_call_count: int,
    api_key_id: UUID | None = None,
    error_code: str | None = None,
    increment_publication: bool = False,
) -> AuditLog:
    """Persist metadata only. No request or response content is accepted."""
    audit = AuditLog(
        request_id=request_id,
        client_id=client_id,
        api_key_id=api_key_id,
        agent_id=agent_id,
        status=status,
        latency_ms=max(0, latency_ms),
        token_usage=token_usage,
        mcp_call_count=max(0, mcp_call_count),
        error_code=error_code,
    )
    session.add(audit)
    if agent_id is not None:
        today = datetime.now(timezone.utc).date()
        success = 1 if status == "succeeded" else 0
        failure = 0 if success else 1
        statement = insert(AgentMetric).values(
            id=uuid4(),
            agent_id=agent_id,
            metric_date=today,
            call_count=1,
            success_count=success,
            failure_count=failure,
            total_latency_ms=max(0, latency_ms),
            total_token_usage=token_usage or 0,
            token_usage_observed_count=1 if token_usage is not None else 0,
            mcp_call_count=max(0, mcp_call_count),
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_agent_metrics_agent_date",
            set_={
                "call_count": AgentMetric.call_count + 1,
                "success_count": AgentMetric.success_count + success,
                "failure_count": AgentMetric.failure_count + failure,
                "total_latency_ms": AgentMetric.total_latency_ms + max(0, latency_ms),
                "total_token_usage": AgentMetric.total_token_usage + (token_usage or 0),
                "token_usage_observed_count": AgentMetric.token_usage_observed_count
                + (1 if token_usage is not None else 0),
                "mcp_call_count": AgentMetric.mcp_call_count + max(0, mcp_call_count),
                "updated_at": func.now(),
            },
        )
        await session.execute(statement)
    if increment_publication:
        if status != "succeeded" or agent_id is None:
            raise ValueError("publication calls can only be incremented for a successful Agent call")
        await session.execute(
            update(AgentPublication)
            .where(AgentPublication.agent_id == agent_id)
            .values(
                call_count=AgentPublication.call_count + 1,
                last_called_at=datetime.now(timezone.utc),
            )
        )
    await session.commit()
    await session.refresh(audit)
    return audit


async def list_audit_logs(
    session: AsyncSession,
    *,
    agent_id: str | None = None,
    client_id: UUID | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    query = select(AuditLog)
    if agent_id is not None:
        query = query.where(AuditLog.agent_id == agent_id)
    if client_id is not None:
        query = query.where(AuditLog.client_id == client_id)
    if status is not None:
        query = query.where(AuditLog.status == status)
    return list(
        await session.scalars(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).offset(offset)
        )
    )


def _metric_read(row: Any) -> dict[str, Any]:
    call_count = int(row.call_count or 0)
    success_count = int(row.success_count or 0)
    failure_count = int(row.failure_count or 0)
    observed = int(row.token_usage_observed_count or 0)
    return {
        "agent_id": str(row.agent_id),
        "agent_name": getattr(row, "agent_name", None),
        "metric_date": getattr(row, "metric_date", None),
        "call_count": call_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "success_rate": round(success_count / call_count, 6) if call_count else None,
        "average_latency_ms": round(int(row.total_latency_ms or 0) / call_count, 2)
        if call_count
        else None,
        # Unknown token totals remain unknown; they are never estimated.
        "token_usage": int(row.total_token_usage or 0) if observed == call_count and call_count else None,
        "mcp_call_count": int(row.mcp_call_count or 0),
    }


async def list_agent_metrics(session: AsyncSession) -> list[dict[str, Any]]:
    query = (
        select(
            Agent.id.label("agent_id"),
            Agent.name.label("agent_name"),
            func.coalesce(func.sum(AgentMetric.call_count), 0).label("call_count"),
            func.coalesce(func.sum(AgentMetric.success_count), 0).label("success_count"),
            func.coalesce(func.sum(AgentMetric.failure_count), 0).label("failure_count"),
            func.coalesce(func.sum(AgentMetric.total_latency_ms), 0).label("total_latency_ms"),
            func.coalesce(func.sum(AgentMetric.total_token_usage), 0).label("total_token_usage"),
            func.coalesce(func.sum(AgentMetric.token_usage_observed_count), 0).label(
                "token_usage_observed_count"
            ),
            func.coalesce(func.sum(AgentMetric.mcp_call_count), 0).label("mcp_call_count"),
        )
        .outerjoin(AgentMetric, AgentMetric.agent_id == Agent.id)
        .group_by(Agent.id, Agent.name)
        .order_by(Agent.name, Agent.id)
    )
    return [_metric_read(row) for row in (await session.execute(query)).all()]


async def get_agent_metrics(session: AsyncSession, agent_id: str) -> dict[str, Any] | None:
    values = await list_agent_metrics(session)
    return next((item for item in values if item["agent_id"] == agent_id), None)


async def latest_agent_metric(session: AsyncSession, agent_id: str) -> AgentMetric | None:
    return await session.scalar(
        select(AgentMetric)
        .where(AgentMetric.agent_id == agent_id)
        .order_by(AgentMetric.metric_date.desc())
        .limit(1)
    )


async def metrics_summary(session: AsyncSession) -> dict[str, Any]:
    metrics = await list_agent_metrics(session)
    agent_count = len(metrics)
    published_agent_count = int(
        await session.scalar(
            select(func.count(Agent.id)).where(
                Agent.status == "active",
                Agent.current_version_id.is_not(None),
                Agent.api_enabled.is_(True),
            )
        ) or 0
    )
    calls = sum(item["call_count"] for item in metrics)
    successes = sum(item["success_count"] for item in metrics)
    failures = sum(item["failure_count"] for item in metrics)
    totals = await session.execute(
        select(
            func.coalesce(func.sum(AgentMetric.total_latency_ms), 0),
            func.coalesce(func.sum(AgentMetric.total_token_usage), 0),
            func.coalesce(func.sum(AgentMetric.token_usage_observed_count), 0),
            func.coalesce(func.sum(AgentMetric.mcp_call_count), 0),
            func.max(AgentMetric.updated_at),
        )
    )
    latency, tokens, token_observed, mcp_calls, updated_at = totals.one()
    return {
        "agent_count": agent_count,
        "published_agent_count": published_agent_count,
        "call_count": calls,
        "success_count": successes,
        "failure_count": failures,
        "success_rate": round(successes / calls, 6) if calls else None,
        "error_rate": round(failures / calls, 6) if calls else None,
        "average_latency_ms": round(int(latency or 0) / calls, 2) if calls else None,
        "token_usage": int(tokens or 0) if int(token_observed or 0) == calls and calls else None,
        "mcp_call_count": int(mcp_calls or 0),
        "updated_at": updated_at or datetime.now(timezone.utc),
    }


async def transition_agent(session: AsyncSession, agent: Agent, target: str) -> Agent:
    transitions = {
        "active": {"inactive", "archived"},
        "inactive": {"active", "archived"},
        "archived": set(),
    }
    if target != agent.status and target not in transitions.get(agent.status, set()):
        raise ValueError(f"invalid Agent lifecycle transition: {agent.status} -> {target}")
    agent.status = target
    agent.api_enabled = target == "active" and agent.current_version_id is not None
    await session.commit()
    await session.refresh(agent)
    return agent


async def build_agent_snapshot(session: AsyncSession, agent: Agent) -> dict[str, Any]:
    skill_ids = list(
        await session.scalars(
            select(agent_skill.c.skill_id)
            .where(agent_skill.c.agent_id == agent.id)
            .order_by(agent_skill.c.skill_id)
        )
    )
    mcp_ids = list(
        await session.scalars(
            select(agent_mcp.c.mcp_id)
            .where(agent_mcp.c.agent_id == agent.id)
            .order_by(agent_mcp.c.mcp_id)
        )
    )
    api_binding = await session.scalar(
        select(AgentAPIVersion).where(
            AgentAPIVersion.agent_id == agent.id,
            AgentAPIVersion.api_version == "v1",
        )
    )
    schema = api_binding.schema_version if api_binding is not None else None
    if schema is None:
        schema = await session.scalar(
            select(AgentSchemaVersion)
            .where(AgentSchemaVersion.agent_id == agent.id)
            .order_by(
                case((AgentSchemaVersion.status == "published", 0), else_=1),
                AgentSchemaVersion.published_at.desc().nullslast(),
                AgentSchemaVersion.created_at.desc(),
            )
            .limit(1)
        )
    return {
        "format_version": 1,
        "prompt": {
            "role": agent.role,
            "system_prompt": agent.system_prompt,
            "prompt_template": agent.prompt_template,
        },
        "model": {
            "name": agent.model,
            "adapter": agent.model_adapter,
            "config": agent.model_settings,
        },
        "skill_ids": [str(value) for value in skill_ids],
        "mcp_ids": [str(value) for value in mcp_ids],
        "schema": {
            "version": schema.version if schema else None,
            "input_schema": schema.input_schema if schema else agent.input_schema,
            "output_schema": schema.output_schema if schema else agent.output_schema,
        },
        "api": {
            "version": api_binding.api_version if api_binding else "v1",
            "status": api_binding.status if api_binding else None,
        },
        "runtime": {
            "response_mode": agent.response_mode,
            "runtime_type": getattr(agent, "runtime_type", "hermes"),
            "runtime_id": (
                str(agent.runtime_id) if getattr(agent, "runtime_id", None) is not None else None
            ),
            "runtime_config": getattr(agent, "runtime_config", {}) or {},
            "capability_profile": getattr(agent, "capability_profile", {}) or {},
        },
    }


async def create_agent_version(
    session: AsyncSession,
    *,
    agent: Agent,
    version: str,
    description: str | None,
    created_by: str = "system",
) -> AgentVersion:
    value = AgentVersion(
        agent_id=agent.id,
        version=version,
        snapshot=await build_agent_snapshot(session, agent),
        status="development",
        description=description,
        created_by=created_by,
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return value


async def next_agent_version(session: AsyncSession, agent_id: str) -> str:
    count = int(
        await session.scalar(select(func.count(AgentVersion.id)).where(AgentVersion.agent_id == agent_id))
        or 0
    )
    candidate = count + 1
    while await get_agent_version(session, agent_id, f"v{candidate}") is not None:
        candidate += 1
    return f"v{candidate}"


async def list_agent_versions(session: AsyncSession, agent_id: str) -> list[AgentVersion]:
    return list(
        await session.scalars(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.created_at.desc(), AgentVersion.version.desc())
        )
    )


async def get_agent_version(
    session: AsyncSession, agent_id: str, version: str
) -> AgentVersion | None:
    return await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.version == version,
        )
    )


async def get_agent_version_by_id(
    session: AsyncSession, agent_id: str, version_id: UUID
) -> AgentVersion | None:
    return await session.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.id == version_id,
        )
    )


async def update_agent_version(
    session: AsyncSession,
    version: AgentVersion,
    *,
    snapshot: dict[str, Any] | None = None,
    description: str | None = None,
    description_set: bool = False,
) -> AgentVersion:
    if version.status not in {"development", "testing", "release_candidate"}:
        raise ValueError("published and deprecated Agent versions are immutable")
    if snapshot is not None:
        validate_agent_snapshot(snapshot)
        version.snapshot = snapshot
        version.snapshot_format_version = int(snapshot.get("format_version") or 1)
        version.resolution_digest = (
            str(snapshot.get("resolution_digest"))
            if snapshot.get("resolution_digest")
            else None
        )
    if description_set:
        version.description = description
    version.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(version)
    return version


async def transition_agent_version(
    session: AsyncSession, version: AgentVersion, target: str
) -> AgentVersion:
    transitions = {
        "development": {"testing"},
        "testing": {"development", "release_candidate"},
        "release_candidate": {"testing"},
        "published": set(),
        "deprecated": set(),
    }
    if target != version.status and target not in transitions.get(version.status, set()):
        raise ValueError(f"invalid Agent Version transition: {version.status} -> {target}")
    version.status = target
    version.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(version)
    return version


def validate_agent_snapshot(snapshot: dict[str, Any]) -> None:
    format_version = int(snapshot.get("format_version") or 0)
    if format_version not in {1, 2}:
        raise ValueError("Agent Version snapshot format_version must be 1 or 2")
    for field in ("prompt", "model", "schema", "runtime"):
        if not isinstance(snapshot.get(field), dict):
            raise ValueError(f"Agent Version snapshot {field} must be an object")
    for field in ("skill_ids", "mcp_ids"):
        values = snapshot.get(field)
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            raise ValueError(f"Agent Version snapshot {field} must be a string array")
    if format_version == 2:
        for field in (
            "skills",
            "capability_bindings",
            "resource_scope_revisions",
            "policy_set_revisions",
        ):
            if not isinstance(snapshot.get(field, []), list):
                raise ValueError(f"Agent Version snapshot {field} must be an array")
        required_features = snapshot["runtime"].get("required_features", [])
        if not isinstance(required_features, list) or any(
            not isinstance(item, str) for item in required_features
        ):
            raise ValueError("Agent Version runtime.required_features must be a string array")
        resolution_digest = snapshot.get("resolution_digest")
        if resolution_digest is not None and (
            not isinstance(resolution_digest, str) or not resolution_digest.startswith("sha256:")
        ):
            raise ValueError("Agent Version resolution_digest is invalid")
    prompt = snapshot["prompt"]
    model = snapshot["model"]
    runtime = snapshot["runtime"]
    if not str(prompt.get("system_prompt") or "").strip():
        raise ValueError("Agent Version system_prompt is required")
    if not str(prompt.get("prompt_template") or "").strip():
        raise ValueError("Agent Version prompt_template is required")
    if not str(model.get("name") or "").strip():
        raise ValueError("Agent Version model name is required")
    if model.get("adapter") not in {"hermes", "qwen", "deepseek", "gpt", "claude"}:
        raise ValueError("Agent Version model adapter is invalid")
    if runtime.get("response_mode") not in {"sync", "stream"}:
        raise ValueError("Agent Version response_mode is invalid")
    if runtime.get("runtime_type", "hermes") not in {"hermes", "pi", "deepseek"}:
        raise ValueError("Agent Version runtime_type is invalid")
    runtime_id = runtime.get("runtime_id")
    if runtime_id is not None:
        try:
            UUID(str(runtime_id))
        except ValueError as exc:
            raise ValueError("Agent Version runtime_id is invalid") from exc
    if not isinstance(runtime.get("runtime_config", {}), dict):
        raise ValueError("Agent Version runtime_config is invalid")
    validate_runtime_config(runtime.get("runtime_config", {}))
    normalize_capability_profile(
        runtime.get("capability_profile", {}),
        runtime_type=runtime.get("runtime_type", "hermes"),
    )
    schema = snapshot["schema"]
    input_schema = schema.get("input_schema") if isinstance(schema.get("input_schema"), dict) else {}
    output_schema = schema.get("output_schema") if isinstance(schema.get("output_schema"), dict) else {}
    normalize_schema(input_schema)
    normalize_schema(output_schema)
    validate_prompt_template(str(prompt["prompt_template"]), input_schema)


async def build_version_runtime_agent(
    session: AsyncSession, agent: Agent, version: AgentVersion
) -> tuple[Any, Any]:
    """Materialize an immutable Version snapshot without changing the live Agent."""
    validate_agent_snapshot(version.snapshot)
    snapshot = version.snapshot
    prompt = snapshot["prompt"]
    model = snapshot["model"]
    schema = snapshot["schema"]
    runtime = snapshot["runtime"]
    skill_ids = [str(item) for item in snapshot["skill_ids"]]
    if int(snapshot.get("format_version") or 1) == 2 and isinstance(snapshot.get("skills"), list):
        skill_ids = [
            str(item.get("skill_id"))
            for item in snapshot["skills"]
            if isinstance(item, dict) and item.get("skill_id")
        ]
    mcp_ids = [str(item) for item in snapshot["mcp_ids"]]
    skills = list(
        await session.scalars(select(Skill).where(Skill.id.in_(skill_ids)).order_by(Skill.id))
    ) if skill_ids else []
    mcp_servers = list(
        await session.scalars(select(MCPServer).where(MCPServer.id.in_(mcp_ids)).order_by(MCPServer.id))
    ) if mcp_ids else []
    missing_skills = sorted(set(skill_ids) - {item.id for item in skills})
    missing_mcps = sorted(set(mcp_ids) - {item.id for item in mcp_servers})
    if missing_skills or missing_mcps:
        missing: list[str] = []
        if missing_skills:
            missing.append(f"Skills: {', '.join(missing_skills)}")
        if missing_mcps:
            missing.append(f"MCP servers: {', '.join(missing_mcps)}")
        raise ValueError(f"Agent Version dependencies are missing ({'; '.join(missing)})")
    input_schema = schema.get("input_schema") if isinstance(schema.get("input_schema"), dict) else {}
    output_schema = schema.get("output_schema") if isinstance(schema.get("output_schema"), dict) else {}
    runtime_agent = SimpleNamespace(
        id=agent.id,
        name=agent.name,
        description=agent.description,
        role=str(prompt.get("role") or agent.role),
        system_prompt=str(prompt.get("system_prompt") or ""),
        prompt_template=str(prompt.get("prompt_template") or "{{input}}"),
        model=str(model.get("name") or agent.model),
        model_adapter=str(model.get("adapter") or agent.model_adapter),
        model_settings=model.get("config") if isinstance(model.get("config"), dict) else {},
        response_mode=(
            runtime.get("response_mode")
            if runtime.get("response_mode") in {"sync", "stream"}
            else "sync"
        ),
        runtime_type=(
            runtime.get("runtime_type")
            if runtime.get("runtime_type") in {"hermes", "pi", "deepseek"}
            else getattr(agent, "runtime_type", "hermes")
        ),
        runtime_id=(
            UUID(str(runtime["runtime_id"]))
            if runtime.get("runtime_id")
            else getattr(agent, "runtime_id", None)
        ),
        runtime_config=(
            runtime.get("runtime_config")
            if isinstance(runtime.get("runtime_config"), dict)
            else getattr(agent, "runtime_config", {})
        ),
        capability_profile=normalize_capability_profile(
            runtime.get("capability_profile", getattr(agent, "capability_profile", {})),
            runtime_type=(
                runtime.get("runtime_type")
                if runtime.get("runtime_type") in {"hermes", "pi", "deepseek"}
                else getattr(agent, "runtime_type", "hermes")
            ),
        ),
        input_schema=input_schema,
        output_schema=output_schema,
        skills=skills,
        mcp_servers=mcp_servers,
        knowledge_sources=list(agent.knowledge_sources),
        status=agent.status,
        current_version_id=agent.current_version_id,
    )
    schema_runtime = SimpleNamespace(
        version=str(schema.get("version")) if schema.get("version") else None,
        input_schema=input_schema,
        output_schema=output_schema,
    )
    return runtime_agent, schema_runtime


async def publish_agent_version(
    session: AsyncSession, *, agent: Agent, version: AgentVersion
) -> AgentVersion:
    await _lock_agent_publication_and_version(session, agent.id, getattr(version, "id", None))
    await session.execute(
        update(AgentVersion)
        .where(AgentVersion.agent_id == agent.id, AgentVersion.id != version.id)
        .where(AgentVersion.status == "published")
        .values(status="deprecated", deprecated_at=datetime.now(timezone.utc))
    )
    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    version.deprecated_at = None
    version.updated_at = datetime.now(timezone.utc)
    agent.current_version_id = version.id
    agent.status = "active"
    agent.api_enabled = True
    await session.commit()
    await session.refresh(version)
    return version


async def publish_agent(
    session: AsyncSession,
    *,
    agent: Agent,
    version: AgentVersion,
) -> AgentVersion:
    if version.status != "release_candidate":
        raise ValueError("only a Release Candidate Agent version can be published")
    await _lock_agent_publication_and_version(session, agent.id, getattr(version, "id", None))
    # Publish the versioned public contract atomically with the Agent state.
    # Phase 4 still exposes the v1 route as the backwards-compatible default.
    snapshot_schema = version.snapshot.get("schema") if isinstance(version.snapshot, dict) else {}
    schema_version = (
        str(snapshot_schema.get("version"))
        if isinstance(snapshot_schema, dict) and snapshot_schema.get("version")
        else "v1"
    )
    snapshot_api = version.snapshot.get("api") if isinstance(version.snapshot, dict) else {}
    api_version_name = (
        str(snapshot_api.get("version"))
        if isinstance(snapshot_api, dict) and snapshot_api.get("version")
        else "v1"
    )
    schema = await session.scalar(
        select(AgentSchemaVersion).where(
            AgentSchemaVersion.agent_id == agent.id,
            AgentSchemaVersion.version == schema_version,
        )
    )
    if schema is None:
        raise ValueError(f"Agent {schema_version} Schema version is missing")
    if schema.status in {"draft", "testing"}:
        schema.status = "published"
        if schema.published_at is None:
            schema.published_at = datetime.now(timezone.utc)
    elif schema.status not in {"published", "deprecated"}:
        raise ValueError("Agent v1 Schema version is unavailable")

    api_version = await session.scalar(
        select(AgentAPIVersion).where(
            AgentAPIVersion.agent_id == agent.id,
            AgentAPIVersion.api_version == api_version_name,
        )
    )
    if api_version is None:
        api_version = AgentAPIVersion(
            agent_id=agent.id,
            api_version=api_version_name,
            schema_version_id=schema.id,
            status="published",
            published_at=datetime.now(timezone.utc),
        )
        session.add(api_version)
    elif api_version.status not in {"draft", "testing", "published", "deprecated"}:
        raise ValueError("Agent v1 API version is unavailable")
    else:
        api_version.schema_version_id = schema.id
        api_version.status = "published"
        if api_version.published_at is None:
            api_version.published_at = datetime.now(timezone.utc)

    publication = await session.get(AgentPublication, agent.id)
    if publication is None:
        publication = AgentPublication(agent_id=agent.id, status="published")
        session.add(publication)
    else:
        publication.status = "published"

    await session.execute(
        update(AgentVersion)
        .where(AgentVersion.agent_id == agent.id, AgentVersion.id != version.id)
        .where(AgentVersion.status == "published")
        .values(status="deprecated", deprecated_at=datetime.now(timezone.utc))
    )
    await restore_agent_version(session, agent=agent, version=version, publish_contract=True)
    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    version.deprecated_at = None
    version.updated_at = datetime.now(timezone.utc)
    agent.current_version_id = version.id
    agent.status = "active"
    agent.api_enabled = True
    await session.commit()
    await session.refresh(version)
    return version


async def rollback_agent_version(
    session: AsyncSession,
    *,
    agent: Agent,
    version: AgentVersion,
) -> Agent:
    if version.status != "deprecated":
        raise ValueError("only a deprecated Agent version can be rolled back")
    await _lock_agent_publication_and_version(session, agent.id, getattr(version, "id", None))
    restored = await restore_agent_version(session, agent=agent, version=version)
    # Rollback changes the live production configuration.  Keep the selected
    # historical snapshot immutable and mark it as the active published one.
    version_id = getattr(version, "id", None)
    if version_id is not None:
        await session.execute(
            update(AgentVersion)
            .where(AgentVersion.agent_id == agent.id, AgentVersion.id != version_id)
            .where(AgentVersion.status == "published")
            .values(status="deprecated", deprecated_at=datetime.now(timezone.utc))
        )
        version.status = "published"
        version.deprecated_at = None
        version.updated_at = datetime.now(timezone.utc)
        if version.published_at is None:
            version.published_at = datetime.now(timezone.utc)
    restored.current_version_id = version.id
    restored.status = "active"
    restored.api_enabled = True
    publication = await session.get(AgentPublication, agent.id)
    if publication is None:
        publication = AgentPublication(agent_id=agent.id, status="published")
        session.add(publication)
    else:
        publication.status = "published"
    await session.commit()
    await session.refresh(restored)
    return restored


async def restore_agent_version(
    session: AsyncSession,
    *,
    agent: Agent,
    version: AgentVersion,
    publish_contract: bool = True,
) -> Agent:
    snapshot = version.snapshot
    prompt = snapshot.get("prompt") or {}
    model = snapshot.get("model") or {}
    schema = snapshot.get("schema") or {}
    runtime = snapshot.get("runtime") or {}
    skill_ids = [str(item) for item in snapshot.get("skill_ids", [])]
    mcp_ids = [str(item) for item in snapshot.get("mcp_ids", [])]
    existing_skill_ids = set(
        await session.scalars(select(Skill.id).where(Skill.id.in_(skill_ids)))
    ) if skill_ids else set()
    existing_mcp_ids = set(
        await session.scalars(select(MCPServer.id).where(MCPServer.id.in_(mcp_ids)))
    ) if mcp_ids else set()
    missing_skill_ids = sorted(set(skill_ids) - existing_skill_ids)
    missing_mcp_ids = sorted(set(mcp_ids) - existing_mcp_ids)
    if missing_skill_ids or missing_mcp_ids:
        missing: list[str] = []
        if missing_skill_ids:
            missing.append(f"Skills: {', '.join(missing_skill_ids)}")
        if missing_mcp_ids:
            missing.append(f"MCP servers: {', '.join(missing_mcp_ids)}")
        raise ValueError(f"Agent rollback dependencies are missing ({'; '.join(missing)})")

    agent.role = str(prompt.get("role") or agent.role)
    agent.system_prompt = str(prompt.get("system_prompt") or agent.system_prompt)
    agent.prompt_template = str(prompt.get("prompt_template") or agent.prompt_template)
    agent.model = str(model.get("name") or agent.model)
    agent.model_adapter = str(model.get("adapter") or agent.model_adapter)
    agent.model_settings = model.get("config") if isinstance(model.get("config"), dict) else {}
    agent.input_schema = schema.get("input_schema") if isinstance(schema.get("input_schema"), dict) else {}
    agent.output_schema = schema.get("output_schema") if isinstance(schema.get("output_schema"), dict) else {}
    if runtime.get("response_mode") in {"sync", "stream"}:
        agent.response_mode = runtime["response_mode"]
    if runtime.get("runtime_type") in {"hermes", "pi", "deepseek"}:
        agent.runtime_type = runtime["runtime_type"]
    if "runtime_id" in runtime:
        agent.runtime_id = UUID(str(runtime["runtime_id"])) if runtime["runtime_id"] else None
    if isinstance(runtime.get("runtime_config"), dict):
        agent.runtime_config = runtime["runtime_config"]
    if isinstance(runtime.get("capability_profile"), dict):
        agent.capability_profile = normalize_capability_profile(
            runtime["capability_profile"], runtime_type=agent.runtime_type
        )

    await session.execute(delete(agent_skill).where(agent_skill.c.agent_id == agent.id))
    await session.execute(delete(agent_mcp).where(agent_mcp.c.agent_id == agent.id))
    for skill_id in skill_ids:
        await session.execute(agent_skill.insert().values(agent_id=agent.id, skill_id=skill_id))
    for mcp_id in mcp_ids:
        await session.execute(
            agent_mcp.insert().values(agent_id=agent.id, mcp_id=mcp_id, permission="read_only")
        )

    schema_version = str(schema.get("version") or "").strip()
    restored_schema: AgentSchemaVersion | None = None
    if schema_version:
        restored_schema = await session.scalar(
            select(AgentSchemaVersion).where(
                AgentSchemaVersion.agent_id == agent.id,
                AgentSchemaVersion.version == schema_version,
            )
        )
        if restored_schema is None:
            restored_schema = AgentSchemaVersion(
                agent_id=agent.id,
                version=schema_version,
                input_schema=agent.input_schema,
                output_schema=agent.output_schema,
                status="published" if publish_contract else "testing",
                published_at=datetime.now(timezone.utc) if publish_contract else None,
            )
            session.add(restored_schema)
            await session.flush()
        else:
            restored_schema.input_schema = agent.input_schema
            restored_schema.output_schema = agent.output_schema
            restored_schema.status = "published" if publish_contract else "testing"
            if publish_contract and restored_schema.published_at is None:
                restored_schema.published_at = datetime.now(timezone.utc)

    snapshot_api = snapshot.get("api") if isinstance(snapshot.get("api"), dict) else {}
    api_version_name = str(snapshot_api.get("version") or "v1")
    if restored_schema is not None and publish_contract:
        api_binding = await session.scalar(
            select(AgentAPIVersion).where(
                AgentAPIVersion.agent_id == agent.id,
                AgentAPIVersion.api_version == api_version_name,
            )
        )
        if api_binding is None:
            session.add(
                AgentAPIVersion(
                    agent_id=agent.id,
                    api_version=api_version_name,
                    schema_version_id=restored_schema.id,
                    status="published",
                    published_at=datetime.now(timezone.utc),
                )
            )
        else:
            api_binding.schema_version_id = restored_schema.id
            api_binding.status = "published"
            if api_binding.published_at is None:
                api_binding.published_at = datetime.now(timezone.utc)
    return agent


async def _lock_agent_publication_and_version(
    session: AsyncSession,
    agent_id: str,
    version_id: UUID | None,
) -> None:
    """Acquire production mutation locks in one stable order."""
    await session.execute(select(Agent.id).where(Agent.id == agent_id).with_for_update())
    await session.execute(
        select(AgentPublication.agent_id)
        .where(AgentPublication.agent_id == agent_id)
        .with_for_update()
    )
    if version_id is not None:
        await session.execute(
            select(AgentVersion.id).where(AgentVersion.id == version_id).with_for_update()
        )


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def enforce_rate_limit(
    redis: Redis,
    *,
    client_id: UUID,
    limit_per_minute: int,
    now: datetime | None = None,
) -> tuple[bool, int, int]:
    """Enforce a shared fixed-window limit across every API process.

    Returns ``(allowed, remaining, retry_after_seconds)``.  The Lua script
    makes INCR and initial expiry atomic, avoiding immortal counters after an
    API process crash.
    """
    current = now or datetime.now(timezone.utc)
    window = int(current.timestamp()) // 60
    key = f"hermes:api-rate-limit:v1:{client_id}:{window}"
    count = int(
        await redis.eval(
            """
            local count = redis.call('INCR', KEYS[1])
            if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
            return count
            """,
            1,
            key,
            60,
        )
    )
    retry_after = max(1, 60 - (int(current.timestamp()) % 60))
    return count <= limit_per_minute, max(0, limit_per_minute - count), retry_after

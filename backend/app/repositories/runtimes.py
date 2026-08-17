from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRuntime
from app.schemas.runtime import RuntimeCreate, RuntimeUpdate


async def create_runtime(session: AsyncSession, payload: RuntimeCreate) -> AgentRuntime:
    value = AgentRuntime(**payload.model_dump())
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return value


async def ensure_runtime(
    session: AsyncSession,
    *,
    name: str,
    runtime_type: str,
    version: str,
    endpoint: str,
    config: dict[str, Any] | None = None,
) -> AgentRuntime:
    value = await session.scalar(select(AgentRuntime).where(AgentRuntime.name == name))
    if value is None:
        value = AgentRuntime(
            name=name,
            type=runtime_type,
            version=version,
            endpoint=endpoint,
            config=config or {},
            status="unknown",
        )
        session.add(value)
    elif value.type != runtime_type:
        raise ValueError(f"Runtime registry name {name} belongs to a different type")
    else:
        value.version = version
        value.endpoint = endpoint
        value.config = config or {}
    await session.commit()
    await session.refresh(value)
    return value


async def get_runtime(session: AsyncSession, runtime_id: UUID) -> AgentRuntime | None:
    return await session.get(AgentRuntime, runtime_id)


async def list_runtimes(
    session: AsyncSession, *, runtime_type: str | None = None
) -> list[AgentRuntime]:
    statement = select(AgentRuntime)
    if runtime_type:
        statement = statement.where(AgentRuntime.type == runtime_type)
    values = await session.scalars(statement.order_by(AgentRuntime.type, AgentRuntime.name))
    return list(values)


async def update_runtime(
    session: AsyncSession, value: AgentRuntime, payload: RuntimeUpdate
) -> AgentRuntime:
    for key, item in payload.model_dump(exclude_unset=True).items():
        setattr(value, key, item)
    await session.commit()
    await session.refresh(value)
    return value


async def record_health(
    session: AsyncSession,
    value: AgentRuntime,
    *,
    online: bool,
    error: str | None = None,
) -> AgentRuntime:
    if value.status != "disabled":
        value.status = "online" if online else "offline"
    value.last_health_at = datetime.now(timezone.utc)
    value.last_error = None if online else (error or "Runtime health check failed")[:2000]
    await session.commit()
    await session.refresh(value)
    return value


async def resolve_runtime(
    session: AsyncSession,
    *,
    runtime_type: str,
    runtime_id: UUID | str | None = None,
    runtime_config: dict[str, Any] | None,
) -> AgentRuntime | None:
    configured_id = runtime_id or (runtime_config or {}).get("runtime_id")
    if configured_id:
        try:
            runtime_id = UUID(str(configured_id))
        except ValueError:
            return None
        value = await get_runtime(session, runtime_id)
        return value if value is not None and value.type == runtime_type else None
    return await session.scalar(
        select(AgentRuntime)
        .where(
            AgentRuntime.type == runtime_type,
            AgentRuntime.status.in_(["online", "unknown"]),
        )
        .order_by(
            (AgentRuntime.status == "online").desc(),
            AgentRuntime.created_at,
        )
        .limit(1)
    )

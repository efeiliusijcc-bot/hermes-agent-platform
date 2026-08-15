from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import AgentAPIVersion, AgentSchemaVersion


async def create_schema_version(
    session: AsyncSession,
    *,
    agent_id: str,
    version: str,
    input_schema: dict,
    output_schema: dict,
) -> AgentSchemaVersion:
    value = AgentSchemaVersion(
        agent_id=agent_id,
        version=version,
        input_schema=input_schema,
        output_schema=output_schema,
        status="draft",
    )
    session.add(value)
    await session.commit()
    await session.refresh(value)
    return value


async def get_schema_version(
    session: AsyncSession, agent_id: str, version: str
) -> AgentSchemaVersion | None:
    return await session.scalar(
        select(AgentSchemaVersion).options(selectinload(AgentSchemaVersion.api_versions)).where(
            AgentSchemaVersion.agent_id == agent_id,
            AgentSchemaVersion.version == version,
        )
    )


async def list_schema_versions(session: AsyncSession, agent_id: str) -> list[AgentSchemaVersion]:
    values = await session.scalars(
        select(AgentSchemaVersion)
        .where(AgentSchemaVersion.agent_id == agent_id)
        .order_by(AgentSchemaVersion.created_at, AgentSchemaVersion.version)
    )
    return list(values)


async def update_schema_version(
    session: AsyncSession,
    value: AgentSchemaVersion,
    *,
    input_schema: dict,
    output_schema: dict,
) -> AgentSchemaVersion:
    value.input_schema = input_schema
    value.output_schema = output_schema
    await session.commit()
    await session.refresh(value)
    return value


async def set_schema_status(
    session: AsyncSession, value: AgentSchemaVersion, status: str
) -> AgentSchemaVersion:
    value.status = status
    if status == "published" and value.published_at is None:
        value.published_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(value)
    return value


async def delete_schema_version(session: AsyncSession, value: AgentSchemaVersion) -> None:
    await session.delete(value)
    await session.commit()


async def create_api_version(
    session: AsyncSession,
    *,
    agent_id: str,
    api_version: str,
    schema_version: AgentSchemaVersion,
) -> AgentAPIVersion:
    value = AgentAPIVersion(
        agent_id=agent_id,
        api_version=api_version,
        schema_version_id=schema_version.id,
        status="draft",
    )
    session.add(value)
    await session.commit()
    return await get_api_version(session, agent_id, api_version)  # type: ignore[return-value]


async def get_api_version(
    session: AsyncSession, agent_id: str, api_version: str
) -> AgentAPIVersion | None:
    return await session.scalar(
        select(AgentAPIVersion)
        .options(selectinload(AgentAPIVersion.schema_version))
        .where(
            AgentAPIVersion.agent_id == agent_id,
            AgentAPIVersion.api_version == api_version,
        )
    )


async def list_api_versions(session: AsyncSession, agent_id: str) -> list[AgentAPIVersion]:
    values = await session.scalars(
        select(AgentAPIVersion)
        .options(selectinload(AgentAPIVersion.schema_version))
        .where(AgentAPIVersion.agent_id == agent_id)
        .order_by(AgentAPIVersion.created_at, AgentAPIVersion.api_version)
    )
    return list(values)


async def update_api_binding(
    session: AsyncSession,
    value: AgentAPIVersion,
    schema_version: AgentSchemaVersion,
) -> AgentAPIVersion:
    value.schema_version_id = schema_version.id
    await session.commit()
    return await get_api_version(session, value.agent_id, value.api_version)  # type: ignore[return-value]


async def set_api_status(
    session: AsyncSession, value: AgentAPIVersion, status: str
) -> AgentAPIVersion:
    value.status = status
    if status == "published" and value.published_at is None:
        value.published_at = datetime.now(timezone.utc)
    await session.commit()
    return await get_api_version(session, value.agent_id, value.api_version)  # type: ignore[return-value]


async def delete_api_version(session: AsyncSession, value: AgentAPIVersion) -> None:
    await session.delete(value)
    await session.commit()

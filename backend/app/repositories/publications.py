from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentPublication


async def get_publication(session: AsyncSession, agent_id: str) -> AgentPublication | None:
    return await session.get(AgentPublication, agent_id)


async def list_publications(session: AsyncSession) -> list[AgentPublication]:
    values = await session.scalars(
        select(AgentPublication).order_by(AgentPublication.created_at, AgentPublication.agent_id)
    )
    return list(values)


async def set_publication(
    session: AsyncSession,
    *,
    agent_id: str,
    status: str,
) -> AgentPublication:
    publication = await get_publication(session, agent_id)
    if publication is None:
        publication = AgentPublication(agent_id=agent_id, status=status)
        session.add(publication)
    else:
        publication.status = status
    await session.commit()
    await session.refresh(publication)
    return publication


async def set_api_key(
    session: AsyncSession,
    publication: AgentPublication,
    *,
    api_key_hash: str,
    api_key_prefix: str,
) -> AgentPublication:
    publication.api_key_hash = api_key_hash
    publication.api_key_prefix = api_key_prefix
    await session.commit()
    await session.refresh(publication)
    return publication


async def record_call(session: AsyncSession, publication: AgentPublication) -> None:
    await session.execute(
        update(AgentPublication)
        .where(AgentPublication.agent_id == publication.agent_id)
        .values(
            call_count=AgentPublication.call_count + 1,
            last_called_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()

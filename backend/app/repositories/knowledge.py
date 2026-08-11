from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeDocument, KnowledgeSource
from app.schemas.knowledge import KnowledgeSourceCreate


async def create_source(session: AsyncSession, payload: KnowledgeSourceCreate) -> KnowledgeSource:
    source = KnowledgeSource(
        id=payload.id,
        name=payload.name,
        description=payload.description,
        config={"embedding_model": "hash-ngram-v1", "dimensions": 384},
        status=payload.status,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


async def list_sources(session: AsyncSession) -> list[KnowledgeSource]:
    result = await session.scalars(select(KnowledgeSource).order_by(KnowledgeSource.created_at, KnowledgeSource.id))
    return list(result.unique())


async def get_source(session: AsyncSession, source_id: str) -> KnowledgeSource | None:
    return await session.get(KnowledgeSource, source_id)


async def list_documents(session: AsyncSession, source_id: str) -> list[KnowledgeDocument]:
    result = await session.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.source_id == source_id)
        .order_by(KnowledgeDocument.created_at, KnowledgeDocument.id)
    )
    return list(result)

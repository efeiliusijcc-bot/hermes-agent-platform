from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.knowledge import KnowledgeServiceClient, KnowledgeServiceError
from app.repositories import knowledge as repository
from app.schemas.knowledge import (
    KnowledgeDocumentRead,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeSourceCreate,
    KnowledgeSourceRead,
)

router = APIRouter(prefix="/api/knowledge-sources", tags=["knowledge"])


@router.post("", response_model=KnowledgeSourceRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_source(
    payload: KnowledgeSourceCreate,
    session: AsyncSession = Depends(get_session),
) -> KnowledgeSourceRead:
    try:
        source = await repository.create_source(session, payload)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Knowledge source id already exists") from exc
    return KnowledgeSourceRead.model_validate(source)


@router.get("", response_model=list[KnowledgeSourceRead])
async def list_knowledge_sources(session: AsyncSession = Depends(get_session)) -> list[KnowledgeSourceRead]:
    return [KnowledgeSourceRead.model_validate(source) for source in await repository.list_sources(session)]


@router.get("/{source_id}", response_model=KnowledgeSourceRead)
async def get_knowledge_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
) -> KnowledgeSourceRead:
    source = await repository.get_source(session, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    return KnowledgeSourceRead.model_validate(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_source(
    source_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    if await repository.get_source(session, source_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    try:
        await KnowledgeServiceClient().delete_source(source_id)
    except KnowledgeServiceError as exc:
        raise _http_error(exc) from exc
    session.expire_all()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{source_id}/documents",
    response_model=KnowledgeDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_knowledge_document(
    source_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> KnowledgeDocumentRead:
    source = await repository.get_source(session, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    if source.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Knowledge source is not active")
    limit = get_settings().knowledge_max_upload_bytes
    content = await file.read(limit + 1)
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Uploaded document is empty")
    if len(content) > limit:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Uploaded document is too large")
    try:
        payload = await KnowledgeServiceClient().upload_document(
            source_id=source_id,
            filename=file.filename or "document",
            content_type=file.content_type or "application/octet-stream",
            content=content,
        )
        return KnowledgeDocumentRead.model_validate(payload)
    except KnowledgeServiceError as exc:
        raise _http_error(exc) from exc


@router.get("/{source_id}/documents", response_model=list[KnowledgeDocumentRead])
async def list_knowledge_documents(
    source_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[KnowledgeDocumentRead]:
    if await repository.get_source(session, source_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    return [
        KnowledgeDocumentRead.model_validate(document)
        for document in await repository.list_documents(session, source_id)
    ]


@router.post("/{source_id}/search", response_model=KnowledgeSearchResponse)
async def search_knowledge_source(
    source_id: str,
    payload: KnowledgeSearchRequest,
    session: AsyncSession = Depends(get_session),
) -> KnowledgeSearchResponse:
    source = await repository.get_source(session, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge source not found")
    if source.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Knowledge source is not active")
    try:
        result = await KnowledgeServiceClient().search(
            query=payload.query,
            source_ids=[source_id],
            top_k=payload.top_k,
        )
        return KnowledgeSearchResponse.model_validate(result)
    except KnowledgeServiceError as exc:
        raise _http_error(exc) from exc


def _http_error(exc: KnowledgeServiceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))

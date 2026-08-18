from __future__ import annotations

import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.management import require_platform_management_key_for_capability_control
from app.repositories import runtimes as repository
from app.runtime import RuntimeAdapterError, get_runtime_adapter
from app.schemas.runtime import RuntimeCreate, RuntimeHealthRead, RuntimeRead, RuntimeType, RuntimeUpdate


router = APIRouter(prefix="/api/runtimes", tags=["runtimes"])


@router.post("", response_model=RuntimeRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_platform_management_key_for_capability_control)])
async def create_runtime(
    payload: RuntimeCreate, session: AsyncSession = Depends(get_session)
) -> RuntimeRead:
    try:
        return RuntimeRead.model_validate(await repository.create_runtime(session, payload))
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Runtime name already exists") from exc


@router.get("", response_model=list[RuntimeRead])
async def list_runtimes(
    runtime_type: RuntimeType | None = Query(default=None, alias="type"),
    session: AsyncSession = Depends(get_session),
) -> list[RuntimeRead]:
    return [
        RuntimeRead.model_validate(item)
        for item in await repository.list_runtimes(session, runtime_type=runtime_type)
    ]


@router.get("/{runtime_id}", response_model=RuntimeRead)
async def get_runtime(
    runtime_id: UUID, session: AsyncSession = Depends(get_session)
) -> RuntimeRead:
    value = await repository.get_runtime(session, runtime_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")
    return RuntimeRead.model_validate(value)


@router.patch("/{runtime_id}", response_model=RuntimeRead, dependencies=[Depends(require_platform_management_key_for_capability_control)])
async def update_runtime(
    runtime_id: UUID,
    payload: RuntimeUpdate,
    session: AsyncSession = Depends(get_session),
) -> RuntimeRead:
    value = await repository.get_runtime(session, runtime_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")
    try:
        return RuntimeRead.model_validate(await repository.update_runtime(session, value, payload))
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Runtime name already exists") from exc


@router.post("/{runtime_id}/health", response_model=RuntimeHealthRead, dependencies=[Depends(require_platform_management_key_for_capability_control)])
async def check_runtime_health(
    runtime_id: UUID, session: AsyncSession = Depends(get_session)
) -> RuntimeHealthRead:
    value = await repository.get_runtime(session, runtime_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found")
    if value.status == "disabled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Runtime is disabled")
    started = time.monotonic()
    try:
        health = await get_runtime_adapter(
            value.type,
            endpoint=value.endpoint,
            version=value.version,
            config=value.config,
        ).health_check()
    except RuntimeAdapterError as exc:
        latency = max(0, int((time.monotonic() - started) * 1000))
        await repository.record_health(session, value, online=False, error=str(exc))
        return RuntimeHealthRead(
            id=value.id,
            status="offline",
            version=None,
            latency_ms=latency,
            detail=str(exc),
        )
    latency = max(0, int((time.monotonic() - started) * 1000))
    await repository.record_health(session, value, online=True)
    return RuntimeHealthRead(
        id=value.id,
        status="online",
        version=health.version or value.version,
        latency_ms=latency,
        detail=health.detail,
    )

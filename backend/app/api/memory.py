from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.memory import AgentMemoryError, AgentMemoryStore, get_memory_store
from app.repositories import agents as agent_repository
from app.schemas.memory import MemoryValueRead, MemoryValueWrite


router = APIRouter(prefix="/api/agents/{agent_id}/memory", tags=["agent-memory"])


@router.get("/{session_id}/{memory_type}/{key}", response_model=MemoryValueRead)
async def get_memory_value(
    agent_id: str,
    session_id: str,
    memory_type: str,
    key: str,
    session: AsyncSession = Depends(get_session),
    memory: AgentMemoryStore = Depends(get_memory_store),
) -> MemoryValueRead:
    await _agent(session, agent_id)
    try:
        namespace = memory.namespace(agent_id, session_id, memory_type)
        value = await memory.get(namespace, key)
    except AgentMemoryError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="memory value not found")
    return MemoryValueRead(namespace=namespace.value, key=key, value=value)


@router.put("/{session_id}/{memory_type}/{key}", response_model=MemoryValueRead)
async def set_memory_value(
    agent_id: str,
    session_id: str,
    memory_type: str,
    key: str,
    payload: MemoryValueWrite,
    session: AsyncSession = Depends(get_session),
    memory: AgentMemoryStore = Depends(get_memory_store),
) -> MemoryValueRead:
    await _agent(session, agent_id)
    try:
        namespace = memory.namespace(agent_id, session_id, memory_type)
        await memory.set(namespace, key, payload.value)
    except AgentMemoryError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return MemoryValueRead(namespace=namespace.value, key=key, value=payload.value)


@router.delete("/{session_id}/{memory_type}/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory_value(
    agent_id: str,
    session_id: str,
    memory_type: str,
    key: str,
    session: AsyncSession = Depends(get_session),
    memory: AgentMemoryStore = Depends(get_memory_store),
) -> Response:
    await _agent(session, agent_id)
    try:
        await memory.delete(memory.namespace(agent_id, session_id, memory_type), key)
    except AgentMemoryError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _agent(session: AsyncSession, agent_id: str):
    value = await agent_repository.get_agent(session, agent_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return value

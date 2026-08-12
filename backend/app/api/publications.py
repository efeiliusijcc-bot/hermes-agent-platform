from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agents import run_agent
from app.db.models import AgentPublication
from app.db.session import get_session
from app.memory import AgentMemoryStore, get_memory_store
from app.repositories import agents as agent_repository
from app.repositories import publications as repository
from app.schemas.agent import AgentRunRequest
from app.schemas.publication import (
    PublicationRead,
    PublicationSecret,
    PublicationUpdate,
    PublicAgentRunResponse,
)
from app.schemas.schema_validation import validate_instance


management_router = APIRouter(tags=["agent-publications"])
public_router = APIRouter(prefix="/api/public/agents", tags=["public-agents"])


@management_router.get("/api/agent-publications", response_model=list[PublicationRead])
async def list_publications(session: AsyncSession = Depends(get_session)) -> list[PublicationRead]:
    return [_read(item) for item in await repository.list_publications(session)]


@management_router.get("/api/agents/{agent_id}/publication", response_model=PublicationRead)
async def get_publication(agent_id: str, session: AsyncSession = Depends(get_session)) -> PublicationRead:
    publication = await repository.get_publication(session, agent_id)
    if publication is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent publication not found")
    return _read(publication)


@management_router.put("/api/agents/{agent_id}/publication", response_model=PublicationRead)
async def update_publication(
    agent_id: str,
    payload: PublicationUpdate,
    session: AsyncSession = Depends(get_session),
) -> PublicationRead:
    agent = await agent_repository.get_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    current = await repository.get_publication(session, agent_id)
    if payload.status == "published":
        if agent.status != "active":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="only active Agents can be published")
        if current is None or current.api_key_hash is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="generate an API Key before publishing")
    return _read(await repository.set_publication(session, agent_id=agent_id, status=payload.status))


@management_router.post("/api/agents/{agent_id}/publication/api-key", response_model=PublicationSecret)
async def rotate_api_key(agent_id: str, session: AsyncSession = Depends(get_session)) -> PublicationSecret:
    if await agent_repository.get_agent(session, agent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    publication = await repository.get_publication(session, agent_id)
    if publication is None:
        publication = await repository.set_publication(session, agent_id=agent_id, status="draft")
    api_key = f"hap_{secrets.token_urlsafe(32)}"
    try:
        publication = await repository.set_api_key(
            session,
            publication,
            api_key_hash=_hash_key(api_key),
            api_key_prefix=api_key[:12],
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="could not generate API Key") from exc
    return PublicationSecret(**_read(publication).model_dump(), api_key=api_key)


@public_router.post("/{agent_id}/run", response_model=PublicAgentRunResponse)
async def run_public_agent(
    agent_id: str,
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: AsyncSession = Depends(get_session),
    memory_store: AgentMemoryStore = Depends(get_memory_store),
) -> PublicAgentRunResponse:
    publication = await repository.get_publication(session, agent_id)
    if publication is None or publication.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="published Agent not found")
    presented_key = x_api_key or _bearer_token(authorization)
    if not presented_key or not publication.api_key_hash or not secrets.compare_digest(
        _hash_key(presented_key), publication.api_key_hash
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API Key")
    agent = await agent_repository.get_agent(session, agent_id)
    if agent is None or agent.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="published Agent is not active")
    try:
        validate_instance(agent.input_schema, payload, label="request")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    run = await run_agent(
        agent_id,
        AgentRunRequest(
            input=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            session_id=f"public-{uuid.uuid4().hex}",
        ),
        session,
        memory_store,
    )
    await repository.record_call(session, publication)
    result: Any = run.output
    if agent.output_schema:
        try:
            result = json.loads(run.output)
            validate_instance(agent.output_schema, result, label="Agent output")
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Agent output schema validation failed: {exc}",
            ) from exc
    return PublicAgentRunResponse(
        agent_id=agent.id,
        execution_id=run.execution_id,
        status="success",
        result=result,
        trace=[
            {"stage": "schema_input", "status": "succeeded"},
            {"stage": "hermes_runtime", "status": "succeeded", "run_id": run.hermes_run_id},
            {"stage": "schema_output", "status": "succeeded"},
        ],
    )


def _read(publication: AgentPublication) -> PublicationRead:
    return PublicationRead(
        agent_id=publication.agent_id,
        agent_name=publication.agent.name if publication.agent else None,
        status=publication.status,
        endpoint=f"/api/public/agents/{publication.agent_id}/run",
        api_key_prefix=publication.api_key_prefix,
        call_count=publication.call_count,
        last_called_at=publication.last_called_at,
        created_at=publication.created_at,
        updated_at=publication.updated_at,
    )


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bearer_token(value: str | None) -> str | None:
    if value and value.startswith("Bearer "):
        return value[7:]
    return None

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from time import monotonic
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.agents import (
    _map_hermes_event,
    _prepare_agent_execution,
    _sse,
    execute_agent_sync,
    stream_prepared_agent,
)
from app.db.models import AgentPublication, ExecutionLog
from app.db.session import SessionFactory, get_session
from app.memory import AgentMemoryError, AgentMemoryStore, get_memory_store
from app.repositories import agents as agent_repository
from app.repositories import publications as repository
from app.repositories import production as production_repository
from app.repositories import schema_versions as schema_repository
from app.runtime.hermes import HermesRuntimeError
from app.schemas.agent import AgentRunRequest, ResponseMode
from app.schemas.publication import (
    PublicationRead,
    PublicationSecret,
    PublicationUpdate,
    PublicAgentRunRequest,
    PublicAgentRunResponse,
)
from app.schemas.schema_validation import parse_and_validate_output, validate_instance
from app.task_queue import get_task_queue
from app.storage import ArtifactStorageError


management_router = APIRouter(tags=["agent-publications"])
public_router = APIRouter(prefix="/api/public/agents", tags=["public-agents"])
versioned_public_router = APIRouter(prefix="/api/{api_version}/agents", tags=["versioned-public-agents"])


@dataclass
class PublicAuditContext:
    request_id: str
    started_at: float
    agent_id: str | None = None
    client_id: UUID | None = None
    api_key_id: UUID | None = None
    recorded: bool = False


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
    if payload.status == "published":
        if agent.status == "active" and agent.current_version_id is not None and agent.api_enabled:
            current = await repository.get_publication(session, agent_id)
            if current is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="published Agent has no publication record",
                )
            return _read(current)
        if agent.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="only active Agents can publish a Version",
            )
        from app.api.production import publish_agent as publish_production_agent

        await publish_production_agent(agent_id, None, session)
    elif payload.status == "disabled" and agent.status == "active":
        await production_repository.transition_agent(session, agent, "inactive")
    publication = await repository.set_publication(
        session,
        agent_id=agent_id,
        status="published" if payload.status == "published" else payload.status,
    )
    return _read(publication)


@management_router.post("/api/agents/{agent_id}/publication/api-key", response_model=PublicationSecret)
async def rotate_api_key(agent_id: str, session: AsyncSession = Depends(get_session)) -> PublicationSecret:
    if await agent_repository.get_agent(session, agent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    try:
        publication, _, api_key = await production_repository.rotate_legacy_publication_key(
            session, agent_id=agent_id
        )
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="could not generate API Key",
        ) from exc
    return PublicationSecret(**_read(publication).model_dump(), api_key=api_key)


@public_router.post("/{agent_id}/run", response_model=None)
async def run_public_agent(
    agent_id: str,
    payload: dict[str, Any],
    response_mode: ResponseMode | None = Query(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: AsyncSession = Depends(get_session),
    memory_store: AgentMemoryStore = Depends(get_memory_store),
) -> PublicAgentRunResponse | StreamingResponse:
    return await _execute_public_agent(
        agent_id=agent_id,
        payload=payload,
        response_mode=response_mode,
        forced_mode=None,
        x_api_key=x_api_key,
        authorization=authorization,
        session=session,
        memory_store=memory_store,
    )


@public_router.post("/{agent_id}/stream", response_model=None)
async def stream_public_agent(
    agent_id: str,
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: AsyncSession = Depends(get_session),
    memory_store: AgentMemoryStore = Depends(get_memory_store),
) -> StreamingResponse:
    response = await _execute_public_agent(
        agent_id=agent_id,
        payload=payload,
        response_mode=None,
        forced_mode="stream",
        x_api_key=x_api_key,
        authorization=authorization,
        session=session,
        memory_store=memory_store,
    )
    if not isinstance(response, StreamingResponse):
        raise RuntimeError("public stream endpoint returned a non-streaming response")
    return response


@versioned_public_router.post("/{agent_id}/run", response_model=None)
async def run_versioned_public_agent(
    api_version: str,
    agent_id: str,
    payload: dict[str, Any],
    response_mode: ResponseMode | None = Query(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: AsyncSession = Depends(get_session),
    memory_store: AgentMemoryStore = Depends(get_memory_store),
) -> PublicAgentRunResponse | StreamingResponse:
    return await _execute_public_agent(
        agent_id=agent_id,
        api_version=api_version,
        payload=payload,
        response_mode=response_mode,
        forced_mode=None,
        x_api_key=x_api_key,
        authorization=authorization,
        session=session,
        memory_store=memory_store,
    )


@versioned_public_router.post("/{agent_id}/stream", response_model=None)
async def stream_versioned_public_agent(
    api_version: str,
    agent_id: str,
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: AsyncSession = Depends(get_session),
    memory_store: AgentMemoryStore = Depends(get_memory_store),
) -> StreamingResponse:
    response = await _execute_public_agent(
        agent_id=agent_id,
        api_version=api_version,
        payload=payload,
        response_mode=None,
        forced_mode="stream",
        x_api_key=x_api_key,
        authorization=authorization,
        session=session,
        memory_store=memory_store,
    )
    if not isinstance(response, StreamingResponse):
        raise RuntimeError("versioned stream endpoint returned a non-streaming response")
    return response


async def _execute_public_agent(
    *,
    agent_id: str,
    api_version: str = "v1",
    payload: dict[str, Any],
    response_mode: ResponseMode | None,
    forced_mode: ResponseMode | None,
    x_api_key: str | None,
    authorization: str | None,
    session: AsyncSession,
    memory_store: AgentMemoryStore,
) -> PublicAgentRunResponse | StreamingResponse:
    audit = PublicAuditContext(
        request_id=f"public-{uuid.uuid4().hex}",
        started_at=monotonic(),
    )
    agent = await agent_repository.get_agent(session, agent_id)
    if agent is None:
        await _reject_public_call(
            audit,
            session,
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published Agent not found",
            error_code="agent_not_found",
        )
    audit.agent_id = agent.id
    if agent.status != "active" or agent.current_version_id is None or not agent.api_enabled:
        await _reject_public_call(
            audit,
            session,
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published Agent not found",
            error_code="agent_not_published",
        )
    publication = await repository.get_publication(session, agent_id)
    if publication is None or publication.status != "published":
        await _reject_public_call(
            audit,
            session,
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published Agent not found",
            error_code="publication_not_published",
        )
    presented_key = x_api_key or _bearer_token(authorization)
    if not presented_key:
        await _reject_public_call(
            audit,
            session,
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API Key",
            error_code="invalid_api_key",
        )

    authentication = await production_repository.authenticate_api_key(
        session,
        agent_id=agent_id,
        presented_key=presented_key,
    )
    if authentication is None:
        client_authentication = await production_repository.authenticate_client_key(
            session,
            presented_key=presented_key,
        )
        if client_authentication is None:
            await _reject_public_call(
                audit,
                session,
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid API Key",
                error_code="invalid_api_key",
            )
        audit.client_id = client_authentication.client.id
        audit.api_key_id = client_authentication.api_key.id
        if not await production_repository.has_invoke_permission(
            session,
            client_id=client_authentication.client.id,
            agent_id=agent_id,
        ):
            await _reject_public_call(
                audit,
                session,
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API Client is not authorized for this Agent",
                error_code="invoke_permission_denied",
            )
        authentication = client_authentication
    audit.client_id = authentication.client.id
    audit.api_key_id = authentication.api_key.id
    try:
        allowed, _, retry_after = await production_repository.enforce_rate_limit(
            get_task_queue().redis,
            client_id=authentication.client.id,
            limit_per_minute=authentication.client.rate_limit_per_minute,
        )
    except RedisError as exc:
        await _record_public_audit(
            audit,
            session,
            call_status="failed",
            error_code="rate_limit_unavailable",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="rate limit service is unavailable",
        ) from exc
    if not allowed:
        await _record_public_audit(
            audit,
            session,
            call_status="rejected",
            error_code="rate_limit_exceeded",
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="API Client rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )

    api_binding = await schema_repository.get_api_version(session, agent_id, api_version)
    if api_binding is None or api_binding.status not in {"published", "deprecated"}:
        await _reject_public_call(
            audit,
            session,
            status_code=status.HTTP_404_NOT_FOUND,
            detail="published API version not found",
            error_code="api_version_not_published",
        )
    schema_version = api_binding.schema_version
    if schema_version.status not in {"published", "deprecated"}:
        await _reject_public_call(
            audit,
            session,
            status_code=status.HTTP_409_CONFLICT,
            detail="API Schema version is unavailable",
            error_code="schema_version_unavailable",
        )
    try:
        input_payload, body_mode, session_id = _public_payload(payload)
    except ValidationError as exc:
        await _record_public_audit(
            audit,
            session,
            call_status="rejected",
            error_code="invalid_request_envelope",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(include_url=False),
        ) from exc
    try:
        validate_instance(schema_version.input_schema, input_payload, label="request")
    except ValueError as exc:
        await _record_public_audit(
            audit,
            session,
            call_status="rejected",
            error_code="input_schema_validation",
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    request = AgentRunRequest(
        input=json.dumps(input_payload, ensure_ascii=False, separators=(",", ":")),
        session_id=session_id or f"public-{uuid.uuid4().hex}",
    )
    selected_mode = forced_mode or response_mode or body_mode or agent.response_mode
    if selected_mode == "stream":
        try:
            context = await _prepare_agent_execution(
                agent,
                request,
                session,
                memory_store,
                schema_version=schema_version,
                response_mode="stream",
                agent_version_id=agent.current_version_id,
            )
        except HTTPException as exc:
            await _record_public_audit(
                audit,
                session,
                call_status="failed",
                error_code=f"execution_prepare_http_{exc.status_code}",
            )
            raise
        except Exception:
            await _record_public_audit(
                audit,
                session,
                call_status="failed",
                error_code="execution_prepare_failed",
            )
            raise
        return StreamingResponse(
            _public_sse_events(
                context,
                request,
                publication,
                memory_store,
                audit,
                schema_version.output_schema,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    try:
        run = await execute_agent_sync(
            agent,
            request,
            session,
            memory_store,
            output_validator=lambda output: parse_and_validate_output(schema_version.output_schema, output),
            schema_version=schema_version,
            agent_version_id=agent.current_version_id,
        )
        result = _validate_public_output(schema_version.output_schema, run.output)
    except HTTPException as exc:
        await _record_public_audit(
            audit,
            session,
            call_status="failed",
            error_code=f"execution_http_{exc.status_code}",
        )
        raise
    except Exception:
        await _record_public_audit(
            audit,
            session,
            call_status="failed",
            error_code="execution_failed",
        )
        raise
    token_usage, mcp_call_count = await _execution_observability(session, run.execution_id)
    await _record_public_audit(
        audit,
        session,
        call_status="succeeded",
        token_usage=token_usage,
        mcp_call_count=mcp_call_count,
    )
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


async def _public_sse_events(
    context: Any,
    request: AgentRunRequest,
    publication: AgentPublication,
    memory_store: AgentMemoryStore,
    audit: PublicAuditContext,
    output_schema: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    yield _sse(
        "start",
        {
            "event": "start",
            "agent_id": context.agent.id,
            "execution_id": str(context.execution.id),
        },
    )
    yield _sse("trace", {"event": "trace", "type": "schema_input", "status": "succeeded"})
    async with SessionFactory() as stream_session:
        execution = await stream_session.get(ExecutionLog, context.execution.id)
        if execution is None:
            await _record_public_audit(
                audit,
                stream_session,
                call_status="failed",
                error_code="execution_log_missing",
            )
            yield _sse("error", {"event": "error", "status": "failed", "message": "execution log not found"})
            return
        context.execution = execution
        try:
            async for event in stream_prepared_agent(
                context,
                request,
                stream_session,
                memory_store,
                output_validator=lambda output: parse_and_validate_output(
                    output_schema or context.agent.output_schema,
                    output,
                ),
            ):
                if str(event.get("event", "")) == "run.completed":
                    result = _validate_public_output(
                        output_schema or context.agent.output_schema,
                        str(event.get("output") or ""),
                    )
                    token_usage, mcp_call_count = await _execution_observability(
                        stream_session,
                        context.execution.id,
                    )
                    await _record_public_audit(
                        audit,
                        stream_session,
                        call_status="succeeded",
                        token_usage=token_usage,
                        mcp_call_count=mcp_call_count,
                    )
                    yield _sse(
                        "trace",
                        {"event": "trace", "type": "schema_output", "status": "succeeded"},
                    )
                    yield _sse(
                        "end",
                        {
                            "event": "end",
                            "status": "success",
                            "agent_id": context.agent.id,
                            "execution_id": str(context.execution.id),
                            "result": result,
                        },
                    )
                    return
                mapped = _map_hermes_event(event)
                if mapped is not None:
                    yield _sse(mapped[0], mapped[1])
            raise HermesRuntimeError("Hermes event stream ended without a completion event")
        except asyncio.CancelledError:
            await _record_public_audit(
                audit,
                stream_session,
                call_status="failed",
                error_code="stream_disconnected",
            )
            raise
        except (HermesRuntimeError, ValueError, json.JSONDecodeError) as exc:
            token_usage, mcp_call_count = await _execution_observability(
                stream_session,
                context.execution.id,
            )
            await _record_public_audit(
                audit,
                stream_session,
                call_status="failed",
                token_usage=token_usage,
                mcp_call_count=mcp_call_count,
                error_code="stream_execution_failed",
            )
            yield _sse(
                "error",
                {"event": "error", "status": "failed", "message": "Agent execution failed"},
            )
        except (AgentMemoryError, ArtifactStorageError):
            await _record_public_audit(
                audit,
                stream_session,
                call_status="failed",
                error_code="stream_dependency_failed",
            )
            yield _sse(
                "error",
                {"event": "error", "status": "failed", "message": "Agent execution failed"},
            )
        except Exception:
            await _record_public_audit(
                audit,
                stream_session,
                call_status="failed",
                error_code="stream_internal_error",
            )
            yield _sse(
                "error",
                {"event": "error", "status": "failed", "message": "Agent execution failed"},
            )


async def _reject_public_call(
    audit: PublicAuditContext,
    session: AsyncSession,
    *,
    status_code: int,
    detail: str,
    error_code: str,
) -> None:
    await _record_public_audit(
        audit,
        session,
        call_status="rejected",
        error_code=error_code,
    )
    raise HTTPException(status_code=status_code, detail=detail)


async def _record_public_audit(
    audit: PublicAuditContext,
    session: AsyncSession,
    *,
    call_status: str,
    token_usage: int | None = None,
    mcp_call_count: int = 0,
    error_code: str | None = None,
) -> None:
    if audit.recorded:
        return
    await production_repository.record_public_call(
        session,
        request_id=audit.request_id,
        client_id=audit.client_id,
        api_key_id=audit.api_key_id,
        agent_id=audit.agent_id,
        status=call_status,
        latency_ms=max(0, round((monotonic() - audit.started_at) * 1000)),
        token_usage=token_usage,
        mcp_call_count=mcp_call_count,
        error_code=error_code,
        increment_publication=call_status == "succeeded",
    )
    audit.recorded = True


async def _execution_observability(
    session: AsyncSession,
    execution_id: UUID,
) -> tuple[int | None, int]:
    execution = await session.get(ExecutionLog, execution_id)
    if execution is None:
        return None, 0
    raw_details = getattr(execution, "details", None)
    details = raw_details if isinstance(raw_details, dict) else {}
    token_usage = _explicit_token_usage(details)
    mcp_calls = details.get("mcp_calls")
    return token_usage, len(mcp_calls) if isinstance(mcp_calls, list) else 0


def _explicit_token_usage(details: dict[str, Any]) -> int | None:
    for key in ("token_usage", "total_tokens"):
        value = details.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    usage = details.get("usage")
    if isinstance(usage, dict):
        value = usage.get("total_tokens")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _validate_public_output(output_schema: dict[str, Any], output: str) -> Any:
    try:
        return parse_and_validate_output(output_schema, output)
    except ValueError as exc:
        raise ValueError(f"Agent output schema validation failed: {exc}") from exc


def _public_payload(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], ResponseMode | None, str | None]:
    is_envelope = (
        "stream" in payload
        or "session_id" in payload
        or (set(payload) == {"input"} and isinstance(payload.get("input"), dict))
    )
    if is_envelope:
        request = PublicAgentRunRequest.model_validate(payload)
        mode: ResponseMode | None = None
        if request.stream is not None:
            mode = "stream" if request.stream else "sync"
        return request.input, mode, request.session_id
    return payload, None, None


def _read(publication: AgentPublication) -> PublicationRead:
    return PublicationRead(
        agent_id=publication.agent_id,
        agent_name=publication.agent.name if publication.agent else None,
        status=publication.status,
        response_mode=publication.agent.response_mode if publication.agent else "sync",
        api_enabled=bool(publication.agent.api_enabled) if publication.agent else False,
        endpoint=f"/api/public/agents/{publication.agent_id}/run",
        api_version="v1",
        schema_version="v1",
        api_key_prefix=publication.api_key_prefix,
        call_count=publication.call_count,
        last_called_at=publication.last_called_at,
        created_at=publication.created_at,
        updated_at=publication.updated_at,
    )


def _bearer_token(value: str | None) -> str | None:
    if value and value.startswith("Bearer "):
        return value[7:]
    return None

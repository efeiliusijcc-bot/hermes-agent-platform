from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentAPIVersion, AgentSchemaVersion
from app.db.session import get_session
from app.repositories import agents as agent_repository
from app.repositories import schema_versions as repository
from app.schemas.schema_versions import (
    APIVersionBindingUpdate,
    APIVersionCreate,
    APIVersionRead,
    LifecycleUpdate,
    SchemaVersionCreate,
    SchemaVersionRead,
    SchemaVersionUpdate,
)
from app.prompting import validate_prompt_template


router = APIRouter(prefix="/api/agents/{agent_id}", tags=["schema-versions"])
TRANSITIONS = {
    "draft": {"testing"},
    "testing": {"published"},
    "published": {"deprecated"},
    "deprecated": {"disabled"},
    "disabled": set(),
}


@router.post("/schema-versions", response_model=SchemaVersionRead, status_code=status.HTTP_201_CREATED)
async def create_schema_version(
    agent_id: str,
    payload: SchemaVersionCreate,
    session: AsyncSession = Depends(get_session),
) -> SchemaVersionRead:
    agent = await _agent(session, agent_id)
    _ensure_agent_editable(agent)
    try:
        validate_prompt_template(agent.prompt_template, payload.input_schema)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    try:
        value = await repository.create_schema_version(
            session,
            agent_id=agent_id,
            version=payload.version,
            input_schema=payload.input_schema,
            output_schema=payload.output_schema,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Schema version already exists") from exc
    return SchemaVersionRead.model_validate(value)


@router.get("/schema-versions", response_model=list[SchemaVersionRead])
async def list_schema_versions(agent_id: str, session: AsyncSession = Depends(get_session)) -> list[SchemaVersionRead]:
    await _agent(session, agent_id)
    return [SchemaVersionRead.model_validate(item) for item in await repository.list_schema_versions(session, agent_id)]


@router.get("/schema-versions/{version}", response_model=SchemaVersionRead)
async def get_schema_version(
    agent_id: str, version: str, session: AsyncSession = Depends(get_session)
) -> SchemaVersionRead:
    return SchemaVersionRead.model_validate(await _schema(session, agent_id, version))


@router.delete(
    "/schema-versions/{version}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_schema_version(
    agent_id: str, version: str, session: AsyncSession = Depends(get_session)
) -> Response:
    _ensure_agent_editable(await _agent(session, agent_id))
    value = await _schema(session, agent_id, version)
    if value.status not in {"draft", "testing"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="published Schema versions cannot be deleted")
    if value.api_versions:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Schema version is bound to an API version")
    await repository.delete_schema_version(session, value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/schema-versions/{version}", response_model=SchemaVersionRead)
async def update_schema_version(
    agent_id: str,
    version: str,
    payload: SchemaVersionUpdate,
    session: AsyncSession = Depends(get_session),
) -> SchemaVersionRead:
    _ensure_agent_editable(await _agent(session, agent_id))
    value = await _schema(session, agent_id, version)
    if value.status not in {"draft", "testing"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="published Schema versions are immutable")
    agent = await _agent(session, agent_id)
    try:
        validate_prompt_template(agent.prompt_template, payload.input_schema)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    value = await repository.update_schema_version(
        session,
        value,
        input_schema=payload.input_schema,
        output_schema=payload.output_schema,
    )
    return SchemaVersionRead.model_validate(value)


@router.put("/schema-versions/{version}/status", response_model=SchemaVersionRead)
async def update_schema_status(
    agent_id: str,
    version: str,
    payload: LifecycleUpdate,
    session: AsyncSession = Depends(get_session),
) -> SchemaVersionRead:
    value = await _schema(session, agent_id, version)
    _transition(value.status, payload.status)
    agent = await _agent(session, agent_id)
    if payload.status == "published":
        if agent.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="only active Agents can publish Schema versions",
            )
    return SchemaVersionRead.model_validate(await repository.set_schema_status(session, value, payload.status))


@router.post("/api-versions", response_model=APIVersionRead, status_code=status.HTTP_201_CREATED)
async def create_api_version(
    agent_id: str,
    payload: APIVersionCreate,
    session: AsyncSession = Depends(get_session),
) -> APIVersionRead:
    _ensure_agent_editable(await _agent(session, agent_id))
    schema_version = await _schema(session, agent_id, payload.schema_version)
    try:
        value = await repository.create_api_version(
            session,
            agent_id=agent_id,
            api_version=payload.api_version,
            schema_version=schema_version,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="API version already exists") from exc
    return _api_read(value)


@router.get("/api-versions", response_model=list[APIVersionRead])
async def list_api_versions(agent_id: str, session: AsyncSession = Depends(get_session)) -> list[APIVersionRead]:
    await _agent(session, agent_id)
    return [_api_read(item) for item in await repository.list_api_versions(session, agent_id)]


@router.get("/api-versions/{api_version}", response_model=APIVersionRead)
async def get_api_version(
    agent_id: str, api_version: str, session: AsyncSession = Depends(get_session)
) -> APIVersionRead:
    return _api_read(await _api(session, agent_id, api_version))


@router.delete(
    "/api-versions/{api_version}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response
)
async def delete_api_version(
    agent_id: str, api_version: str, session: AsyncSession = Depends(get_session)
) -> Response:
    _ensure_agent_editable(await _agent(session, agent_id))
    value = await _api(session, agent_id, api_version)
    if value.status not in {"draft", "testing"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="published API versions cannot be deleted")
    await repository.delete_api_version(session, value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/api-versions/{api_version}/binding", response_model=APIVersionRead)
async def update_api_binding(
    agent_id: str,
    api_version: str,
    payload: APIVersionBindingUpdate,
    session: AsyncSession = Depends(get_session),
) -> APIVersionRead:
    _ensure_agent_editable(await _agent(session, agent_id))
    value = await _api(session, agent_id, api_version)
    if value.status not in {"draft", "testing"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="published API bindings are immutable")
    schema_version = await _schema(session, agent_id, payload.schema_version)
    return _api_read(await repository.update_api_binding(session, value, schema_version))


@router.put("/api-versions/{api_version}/status", response_model=APIVersionRead)
async def update_api_status(
    agent_id: str,
    api_version: str,
    payload: LifecycleUpdate,
    session: AsyncSession = Depends(get_session),
) -> APIVersionRead:
    value = await _api(session, agent_id, api_version)
    _transition(value.status, payload.status)
    agent = await _agent(session, agent_id)
    if payload.status == "published":
        if value.schema_version.status != "published":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="API requires a published Schema version")
        if agent.status != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="only active Agents can publish APIs",
            )
    return _api_read(await repository.set_api_status(session, value, payload.status))


async def _agent(session: AsyncSession, agent_id: str):
    value = await agent_repository.get_agent(session, agent_id)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return value


def _ensure_agent_editable(agent) -> None:
    if agent.status == "archived" or agent.current_version_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent live configuration is immutable; edit an Agent Version instead",
        )


async def _schema(session: AsyncSession, agent_id: str, version: str) -> AgentSchemaVersion:
    value = await repository.get_schema_version(session, agent_id, version)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema version not found")
    return value


async def _api(session: AsyncSession, agent_id: str, version: str) -> AgentAPIVersion:
    value = await repository.get_api_version(session, agent_id, version)
    if value is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API version not found")
    return value


def _transition(current: str, target: str) -> None:
    if target == current:
        return
    if target not in TRANSITIONS[current]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"invalid lifecycle transition: {current} -> {target}",
        )


def _api_read(value: AgentAPIVersion) -> APIVersionRead:
    return APIVersionRead(
        id=value.id,
        agent_id=value.agent_id,
        api_version=value.api_version,
        schema_version_id=value.schema_version_id,
        schema_version=SchemaVersionRead.model_validate(value.schema_version),
        status=value.status,
        endpoint=f"/api/{value.api_version}/agents/{value.agent_id}/run",
        created_at=value.created_at,
        published_at=value.published_at,
    )

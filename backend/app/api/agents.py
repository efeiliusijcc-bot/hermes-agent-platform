from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.db.models import ExecutionLog
from app.repositories import agents as repository
from app.runtime.hermes import HermesClient, HermesRuntimeError
from app.schemas.agent import AgentCreate, AgentRead, AgentRunRequest, AgentRunResponse, ExecutionLogRead

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: AgentCreate, session: AsyncSession = Depends(get_session)) -> AgentRead:
    try:
        agent = await repository.create_agent(session, payload)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="agent id already exists") from exc
    return AgentRead.model_validate(agent)


@router.get("", response_model=list[AgentRead])
async def list_agents(session: AsyncSession = Depends(get_session)) -> list[AgentRead]:
    return [AgentRead.model_validate(agent) for agent in await repository.list_agents(session)]


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(agent_id: str, session: AsyncSession = Depends(get_session)) -> AgentRead:
    agent = await repository.get_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return AgentRead.model_validate(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    agent = await repository.get_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    await repository.delete_agent(session, agent)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{agent_id}/run", response_model=AgentRunResponse)
async def run_agent(
    agent_id: str,
    payload: AgentRunRequest,
    session: AsyncSession = Depends(get_session),
) -> AgentRunResponse:
    agent = await repository.get_agent(session, agent_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    if agent.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="agent is not active")

    execution = ExecutionLog(
        agent_id=agent.id,
        status="running",
        input=payload.input,
        details={"phase": "hermes_runtime"},
    )
    session.add(execution)
    await session.commit()
    await session.refresh(execution)

    prompt = (
        f"Role:\n{agent.role}\n\n"
        f"System instructions:\n{agent.system_prompt}\n\n"
        f"User input:\n{payload.input}\n\n"
        "Follow the system instructions and return the final answer."
    )
    try:
        result = await HermesClient().run(
            prompt=prompt,
            agent_id=agent.id,
            execution_id=str(execution.id),
        )
    except HermesRuntimeError as exc:
        execution.status = "failed"
        execution.error = str(exc)[:2000]
        execution.finished_at = datetime.now(timezone.utc)
        await session.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Hermes execution failed") from exc

    execution.status = "succeeded"
    execution.output = result.output
    execution.details = {"phase": "hermes_runtime", "hermes_run_id": result.run_id, "hermes_status": result.status}
    execution.finished_at = datetime.now(timezone.utc)
    await session.commit()
    return AgentRunResponse(
        execution_id=execution.id,
        agent_id=agent.id,
        status="succeeded",
        output=result.output,
        hermes_run_id=result.run_id,
    )


@router.get("/{agent_id}/runs", response_model=list[ExecutionLogRead])
async def list_agent_runs(agent_id: str, session: AsyncSession = Depends(get_session)) -> list[ExecutionLogRead]:
    if await repository.get_agent(session, agent_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return [
        ExecutionLogRead.model_validate(item)
        for item in await repository.list_execution_logs(session, agent_id)
    ]

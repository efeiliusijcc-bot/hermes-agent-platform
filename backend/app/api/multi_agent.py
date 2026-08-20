from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExecutionLog
from app.db.session import get_session
from app.message_bus import (
    AgentMessageBus,
    AgentMessageBusError,
    get_agent_message_bus,
)
from app.orchestrator import AgentOrchestrator, OrchestratorError
from app.repositories import agents as agent_repository
from app.repositories import multi_agent as repository
from app.repositories import orchestration as task_repository
from app.schemas.multi_agent import (
    AgentMessageCreate,
    AgentMessageRead,
    HumanApprovalRequest,
    MultiAgentRunRequest,
    TeamConversationList,
    TeamConversationMessageRequest,
    TeamConversationRead,
    TeamCreate,
    TeamMemberRead,
    TeamMemberUpsert,
    TeamRead,
    TeamUpdate,
    WorkflowCreate,
    WorkflowRead,
    WorkflowRunRead,
    WorkflowRunList,
    WorkflowUpdate,
)
from app.schemas.orchestration import TaskRead
from app.task_queue import TaskQueue, TaskQueueError, get_task_queue


router = APIRouter(tags=["multi-agent"])


def _team_read(team: object) -> TeamRead:
    return TeamRead(
        id=team.id,
        name=team.name,
        description=team.description,
        owner_agent_id=team.owner_agent_id,
        status=team.status,
        members=[
            TeamMemberRead(
                agent_id=member.agent_id,
                agent_name=member.agent.name,
                agent_type=member.agent.agent_type,
                runtime_type=member.agent.runtime_type,
                role=member.role,
                priority=member.priority,
            )
            for member in sorted(team.members, key=lambda item: (-item.priority, item.agent_id))
        ],
        created_at=team.created_at,
        updated_at=team.updated_at,
    )


def _workflow_read(workflow: object) -> WorkflowRead:
    return WorkflowRead(
        id=workflow.id,
        team_id=workflow.team_id,
        name=workflow.name,
        description=workflow.description,
        status=workflow.status,
        nodes=workflow.definition.get("nodes", []),
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
    )


async def _active_team(session: AsyncSession, team_id: UUID):
    team = await repository.get_team(session, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Team not found")
    if team.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent Team is not active")
    return team


@router.post("/api/agent-teams", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
async def create_team(payload: TeamCreate, session: AsyncSession = Depends(get_session)) -> TeamRead:
    owner = await agent_repository.get_agent(session, payload.owner_agent_id)
    if owner is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="owner Agent not found")
    if owner.status != "active" or owner.agent_type != "manager":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Team owner must be an active Manager Agent",
        )
    try:
        return _team_read(await repository.create_team(session, payload))
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent Team name already exists") from exc


@router.get("/api/agent-teams", response_model=list[TeamRead])
async def list_teams(session: AsyncSession = Depends(get_session)) -> list[TeamRead]:
    return [_team_read(team) for team in await repository.list_teams(session)]


@router.get("/api/agent-teams/{team_id}", response_model=TeamRead)
async def get_team(team_id: UUID, session: AsyncSession = Depends(get_session)) -> TeamRead:
    team = await repository.get_team(session, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Team not found")
    return _team_read(team)


@router.patch("/api/agent-teams/{team_id}", response_model=TeamRead)
async def update_team(
    team_id: UUID, payload: TeamUpdate, session: AsyncSession = Depends(get_session)
) -> TeamRead:
    team = await repository.get_team(session, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Team not found")
    try:
        return _team_read(await repository.update_team(session, team, payload))
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent Team name already exists") from exc


@router.delete("/api/agent-teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: UUID, session: AsyncSession = Depends(get_session)) -> Response:
    team = await repository.get_team(session, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Team not found")
    if await repository.list_runs(session, team_id=team_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent Team with execution history must be archived instead of deleted",
        )
    await repository.delete_team(session, team)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/api/agent-teams/{team_id}/members/{agent_id}", response_model=TeamRead)
async def upsert_team_member(
    team_id: UUID,
    agent_id: str,
    payload: TeamMemberUpsert,
    session: AsyncSession = Depends(get_session),
) -> TeamRead:
    team = await _active_team(session, team_id)
    agent = await agent_repository.get_agent(session, agent_id)
    if agent is None or agent.status != "active":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="active Agent not found")
    await repository.upsert_member(
        session, team_id=team.id, agent_id=agent.id, role=payload.role, priority=payload.priority
    )
    return _team_read(await repository.get_team(session, team.id))


@router.delete("/api/agent-teams/{team_id}/members/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member(
    team_id: UUID, agent_id: str, session: AsyncSession = Depends(get_session)
) -> Response:
    team = await repository.get_team(session, team_id)
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Team not found")
    if agent_id == team.owner_agent_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team owner cannot be removed")
    if not await repository.remove_member(session, team_id=team_id, agent_id=agent_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/workflows", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreate, session: AsyncSession = Depends(get_session)
) -> WorkflowRead:
    team = await _active_team(session, payload.team_id)
    member_ids = {member.agent_id for member in team.members}
    invalid = sorted(
        {node.agent_id for node in payload.nodes if node.agent_id and node.agent_id not in member_ids}
    )
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"workflow Agents are not Team members: {', '.join(invalid)}",
        )
    try:
        return _workflow_read(await repository.create_workflow(session, payload))
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow name already exists") from exc


@router.get("/api/workflows", response_model=list[WorkflowRead])
async def list_workflows(
    team_id: UUID | None = Query(default=None), session: AsyncSession = Depends(get_session)
) -> list[WorkflowRead]:
    return [_workflow_read(item) for item in await repository.list_workflows(session, team_id=team_id)]


@router.get("/api/workflows/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: UUID, session: AsyncSession = Depends(get_session)
) -> WorkflowRead:
    workflow = await repository.get_workflow(session, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return _workflow_read(workflow)


@router.patch("/api/workflows/{workflow_id}", response_model=WorkflowRead)
async def update_workflow(
    workflow_id: UUID,
    payload: WorkflowUpdate,
    session: AsyncSession = Depends(get_session),
) -> WorkflowRead:
    workflow = await repository.get_workflow(session, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if payload.nodes is not None:
        team = await _active_team(session, workflow.team_id)
        member_ids = {member.agent_id for member in team.members}
        if any(node.agent_id and node.agent_id not in member_ids for node in payload.nodes):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="workflow Agent is not a Team member",
            )
    return _workflow_read(await repository.update_workflow(session, workflow, payload))


@router.delete("/api/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    workflow = await repository.get_workflow(session, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if await repository.list_runs(session, workflow_id=workflow_id, active_only=True):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow has active runs")
    await repository.delete_workflow(session, workflow)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/agent-teams/{team_id}/runs",
    response_model=WorkflowRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_team(
    team_id: UUID,
    payload: MultiAgentRunRequest,
    session: AsyncSession = Depends(get_session),
    queue: TaskQueue = Depends(get_task_queue),
    bus: AgentMessageBus = Depends(get_agent_message_bus),
) -> WorkflowRunRead:
    team = await _active_team(session, team_id)
    try:
        run = await AgentOrchestrator(queue, bus).submit_team_run(
            session, team=team, payload=payload
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent Team conversation already has an active Run",
        ) from exc
    except (TaskQueueError, OrchestratorError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return WorkflowRunRead.model_validate(run)


@router.post(
    "/api/workflows/{workflow_id}/runs",
    response_model=WorkflowRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_workflow(
    workflow_id: UUID,
    payload: MultiAgentRunRequest,
    session: AsyncSession = Depends(get_session),
    queue: TaskQueue = Depends(get_task_queue),
    bus: AgentMessageBus = Depends(get_agent_message_bus),
) -> WorkflowRunRead:
    workflow = await repository.get_workflow(session, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    if workflow.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not active")
    team = await _active_team(session, workflow.team_id)
    try:
        run = await AgentOrchestrator(queue, bus).submit_workflow_run(
            session, team=team, workflow=workflow, payload=payload
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent Team conversation already has an active Run",
        ) from exc
    except (TaskQueueError, OrchestratorError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return WorkflowRunRead.model_validate(run)


@router.get(
    "/api/agent-teams/{team_id}/conversations",
    response_model=TeamConversationList,
)
async def list_team_conversations(
    team_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> TeamConversationList:
    if await repository.get_team(session, team_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Team not found")
    items, total = await repository.list_conversations(
        session,
        team_id=team_id,
        limit=limit,
        offset=offset,
    )
    return TeamConversationList(
        items=[
            TeamConversationRead(
                team_id=item.team_id,
                session_id=item.session_id,
                workflow_id=item.workflow_id,
                workflow_name=item.workflow_name,
                title=item.title,
                latest_run_id=item.latest_run_id,
                latest_status=item.latest_status,
                run_count=item.run_count,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/api/agent-teams/{team_id}/conversations/{session_id}/runs",
    response_model=WorkflowRunList,
)
async def list_team_conversation_runs(
    team_id: UUID,
    session_id: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> WorkflowRunList:
    if await repository.get_team(session, team_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent Team not found")
    items, total = await repository.list_conversation_runs(
        session,
        team_id=team_id,
        session_id=session_id,
        limit=limit,
        offset=offset,
    )
    return WorkflowRunList(
        items=[WorkflowRunRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/api/agent-teams/{team_id}/conversations/{session_id}/messages",
    response_model=WorkflowRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_team_conversation_message(
    team_id: UUID,
    payload: TeamConversationMessageRequest,
    session_id: str = Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
    session: AsyncSession = Depends(get_session),
    queue: TaskQueue = Depends(get_task_queue),
    bus: AgentMessageBus = Depends(get_agent_message_bus),
) -> WorkflowRunRead:
    team = await _active_team(session, team_id)
    exists, locked_workflow_id = await repository.conversation_mode(
        session,
        team_id=team_id,
        session_id=session_id,
    )
    if exists and locked_workflow_id != payload.workflow_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent Team conversation execution mode is locked",
        )
    if await repository.list_runs(
        session,
        team_id=team_id,
        session_id=session_id,
        active_only=True,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent Team conversation already has an active Run",
        )

    workflow = None
    if payload.workflow_id is not None:
        workflow = await repository.get_workflow(session, payload.workflow_id)
        if workflow is None or workflow.team_id != team_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Workflow does not belong to the selected Agent Team",
            )
        if workflow.status != "active":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow is not active")

    run_payload = MultiAgentRunRequest(
        input=payload.input,
        session_id=session_id,
        user_id=payload.user_id,
        priority=payload.priority,
        parameters=payload.parameters,
    )
    orchestrator = AgentOrchestrator(queue, bus)
    try:
        run = (
            await orchestrator.submit_workflow_run(
                session,
                team=team,
                workflow=workflow,
                payload=run_payload,
            )
            if workflow is not None
            else await orchestrator.submit_team_run(
                session,
                team=team,
                payload=run_payload,
            )
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent Team conversation already has an active Run",
        ) from exc
    except (TaskQueueError, OrchestratorError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return WorkflowRunRead.model_validate(run)


@router.get("/api/workflow-runs", response_model=list[WorkflowRunRead])
async def list_workflow_runs(
    team_id: UUID | None = Query(default=None),
    workflow_id: UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[WorkflowRunRead]:
    return [
        WorkflowRunRead.model_validate(item)
        for item in await repository.list_runs(
            session, team_id=team_id, workflow_id=workflow_id
        )
    ]


@router.get("/api/workflow-runs/{run_id}", response_model=WorkflowRunRead)
async def get_workflow_run(
    run_id: UUID, session: AsyncSession = Depends(get_session)
) -> WorkflowRunRead:
    run = await repository.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow Run not found")
    return WorkflowRunRead.model_validate(run)


@router.delete("/api/workflow-runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_workflow_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
    queue: TaskQueue = Depends(get_task_queue),
) -> Response:
    run = await repository.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow Run not found")
    if run.status not in {"pending", "running", "human_review"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workflow Run is already terminal")
    tasks = await task_repository.list_run_tasks(session, run_id)
    if any(task.status == "running" for task in tasks):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="running Runtime tasks must finish before this Run can be cancelled safely",
        )
    now = datetime.now(timezone.utc)
    for task in tasks:
        if task.status in {"pending", "retrying"}:
            await queue.remove(task.id)
        if task.status in {"pending", "retrying", "waiting_child", "human_review"}:
            task.status = "cancelled"
            task.finished_at = now
            task.session.status = "cancelled"
            task.session.finished_at = now
            if task.execution_id:
                execution = await session.get(ExecutionLog, task.execution_id)
                if execution is not None:
                    execution.status = "cancelled"
                    execution.finished_at = now
    run.status = "cancelled"
    run.finished_at = now
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/workflow-runs/{run_id}/tasks", response_model=list[TaskRead])
async def list_workflow_run_tasks(
    run_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[TaskRead]:
    if await repository.get_run(session, run_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow Run not found")
    return [
        TaskRead.model_validate(item) for item in await task_repository.list_run_tasks(session, run_id)
    ]


@router.post("/api/tasks/{task_id}/approval", response_model=TaskRead)
async def review_human_task(
    task_id: UUID,
    payload: HumanApprovalRequest,
    session: AsyncSession = Depends(get_session),
    queue: TaskQueue = Depends(get_task_queue),
    bus: AgentMessageBus = Depends(get_agent_message_bus),
) -> TaskRead:
    task = await task_repository.get_task(session, task_id, lock=True)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
    if task.status != "human_review":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="task is not waiting for human review")
    now = datetime.now(timezone.utc)
    task.status = "succeeded" if payload.approved else "failed"
    task.error = None if payload.approved else (payload.note or "human review rejected")
    task.output_data = {"approved": payload.approved, "note": payload.note}
    task.finished_at = now
    task.session.status = task.status
    task.session.output = payload.note or ("approved" if payload.approved else "rejected")
    task.session.finished_at = now
    if task.execution_id:
        execution = await session.get(ExecutionLog, task.execution_id)
        if execution is not None:
            execution.status = task.status
            execution.output = task.session.output if payload.approved else None
            execution.error = task.error
            execution.finished_at = now
            execution.duration_ms = max(0, int((now - execution.started_at).total_seconds() * 1000))
    await session.commit()
    if task.workflow_run_id:
        run = await repository.get_run(session, task.workflow_run_id)
        if run is not None:
            await AgentOrchestrator(queue, bus).reconcile_run(session, run)
    return TaskRead.model_validate(await task_repository.get_task(session, task.id))


@router.post("/api/agent-messages", response_model=AgentMessageRead, status_code=status.HTTP_201_CREATED)
async def publish_agent_message(
    payload: AgentMessageCreate,
    session: AsyncSession = Depends(get_session),
    bus: AgentMessageBus = Depends(get_agent_message_bus),
) -> AgentMessageRead:
    source = await agent_repository.get_agent(session, payload.from_agent)
    target = await agent_repository.get_agent(session, payload.to_agent)
    if source is None or target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message Agent not found")
    if source.status != "active" or target.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="message Agents must be active")
    if not await repository.agents_share_team(session, source.id, target.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agents do not share a Team")
    try:
        message_id = await bus.publish(
            from_agent=source.id,
            to_agent=target.id,
            message_type=payload.message_type,
            payload=payload.payload,
            task_id=str(payload.task_id) if payload.task_id else None,
        )
    except AgentMessageBusError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    timestamp_ms = int(message_id.split("-", 1)[0])
    return AgentMessageRead(
        **payload.model_dump(),
        id=message_id,
        created_at=datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc),
    )


@router.get("/api/agent-messages", response_model=list[AgentMessageRead])
async def list_agent_messages(
    to_agent: str | None = Query(default=None),
    after_id: str = Query(default="-", pattern=r"^(?:-|\d+-\d+)$"),
    limit: int = Query(default=100, ge=1, le=500),
    bus: AgentMessageBus = Depends(get_agent_message_bus),
) -> list[AgentMessageRead]:
    try:
        values = await bus.list(after_id=after_id, to_agent=to_agent, count=limit)
    except AgentMessageBusError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return [AgentMessageRead.model_validate(item) for item in values]

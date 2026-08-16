from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import AgentSession, AgentTask, Artifact, ExecutionLog


async def create_task(
    session: AsyncSession,
    *,
    agent_id: str,
    input_text: str,
    memory_session_id: str,
    user_id: str | None,
    priority: int,
    max_attempts: int,
    workspace_path: str,
    internal_session_id: UUID,
    input_json: dict[str, object] | None = None,
    retry_of_execution_id: UUID | None = None,
    agent_version_id: UUID | None = None,
    runtime_type: str = "hermes",
    parent_task_id: UUID | None = None,
    workflow_id: UUID | None = None,
    workflow_run_id: UUID | None = None,
    node_key: str | None = None,
    node_type: str = "agent",
    depends_on: list[str] | None = None,
    task_input_data: dict[str, object] | None = None,
    initial_status: str = "pending",
) -> AgentTask:
    agent_session = AgentSession(
        id=internal_session_id,
        agent_id=agent_id,
        user_id=user_id,
        memory_session_id=memory_session_id,
        runtime_type=runtime_type,
        status="queued",
        input=input_text,
        workspace_path=workspace_path,
    )
    execution_id = uuid4()
    execution = ExecutionLog(
        id=execution_id,
        agent_id=agent_id,
        session_id=internal_session_id,
        status="queued",
        input=input_text,
        input_json=input_json or {"task": input_text, "parameters": {}},
        response_mode="async",
        runtime_type=runtime_type,
        priority=priority,
        retry_of_execution_id=retry_of_execution_id,
        agent_version_id=agent_version_id,
        details={"phase": "queued", "queue_priority": priority},
    )
    session.add(agent_session)
    await session.flush()
    session.add(execution)
    await session.flush()
    task = AgentTask(
        parent_task_id=parent_task_id,
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        node_key=node_key,
        node_type=node_type,
        depends_on=depends_on or [],
        input_data=task_input_data or {},
        agent_id=agent_id,
        session=agent_session,
        execution_id=execution_id,
        priority=priority,
        status=initial_status,
        max_attempts=max_attempts,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


async def get_task(session: AsyncSession, task_id: UUID, *, lock: bool = False) -> AgentTask | None:
    statement = select(AgentTask).options(selectinload(AgentTask.session)).where(AgentTask.id == task_id)
    if lock:
        statement = statement.with_for_update(of=AgentTask)
    return (await session.scalars(statement)).first()


async def list_tasks(
    session: AsyncSession,
    *,
    agent_id: str | None = None,
    status: str | None = None,
    workflow_run_id: UUID | None = None,
    parent_task_id: UUID | None = None,
    limit: int = 100,
) -> list[AgentTask]:
    statement = select(AgentTask)
    if agent_id:
        statement = statement.where(AgentTask.agent_id == agent_id)
    if status:
        statement = statement.where(AgentTask.status == status)
    if workflow_run_id is not None:
        statement = statement.where(AgentTask.workflow_run_id == workflow_run_id)
    if parent_task_id is not None:
        statement = statement.where(AgentTask.parent_task_id == parent_task_id)
    values = await session.scalars(statement.order_by(AgentTask.created_at.desc()).limit(limit))
    return list(values.unique())


async def get_agent_session(session: AsyncSession, session_id: UUID) -> AgentSession | None:
    return await session.get(AgentSession, session_id)


async def list_sessions(
    session: AsyncSession,
    *,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[AgentSession]:
    statement = select(AgentSession)
    if agent_id:
        statement = statement.where(AgentSession.agent_id == agent_id)
    if status:
        statement = statement.where(AgentSession.status == status)
    values = await session.scalars(statement.order_by(AgentSession.created_at.desc()).limit(limit))
    return list(values)


async def get_artifact(session: AsyncSession, artifact_id: UUID) -> Artifact | None:
    return await session.get(Artifact, artifact_id)


async def delete_artifact(session: AsyncSession, artifact: Artifact) -> None:
    await session.delete(artifact)
    await session.commit()


async def list_artifacts(
    session: AsyncSession,
    *,
    agent_id: str | None = None,
    session_id: UUID | None = None,
    limit: int = 100,
) -> list[Artifact]:
    statement = select(Artifact)
    if agent_id:
        statement = statement.where(Artifact.agent_id == agent_id)
    if session_id:
        statement = statement.where(Artifact.session_id == session_id)
    values = await session.scalars(statement.order_by(Artifact.created_at.desc()).limit(limit))
    return list(values)


async def workspace_summary(session: AsyncSession, agent_id: str) -> tuple[int, int, int]:
    sessions = await session.scalar(select(func.count()).select_from(AgentSession).where(AgentSession.agent_id == agent_id))
    artifact_row = await session.execute(
        select(func.count(Artifact.id), func.coalesce(func.sum(Artifact.size_bytes), 0)).where(Artifact.agent_id == agent_id)
    )
    artifact_count, size_bytes = artifact_row.one()
    return int(sessions or 0), int(artifact_count or 0), int(size_bytes or 0)


async def pending_tasks(session: AsyncSession, limit: int = 500) -> list[AgentTask]:
    values = await session.scalars(
        select(AgentTask)
        .where(AgentTask.status.in_(["pending", "retrying"]))
        .order_by(AgentTask.priority.desc(), AgentTask.created_at)
        .limit(limit)
    )
    return list(values)


async def stale_running_tasks(session: AsyncSession, stale_seconds: int) -> list[AgentTask]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
    values = await session.scalars(
        select(AgentTask).where(AgentTask.status == "running", AgentTask.started_at < cutoff)
    )
    return list(values)


async def list_run_tasks(session: AsyncSession, workflow_run_id: UUID) -> list[AgentTask]:
    values = await session.scalars(
        select(AgentTask)
        .options(selectinload(AgentTask.session))
        .where(AgentTask.workflow_run_id == workflow_run_id)
        .order_by(AgentTask.created_at, AgentTask.id)
    )
    return list(values.unique())

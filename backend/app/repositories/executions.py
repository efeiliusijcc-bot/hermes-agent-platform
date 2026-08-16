from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Agent, AgentTask, Artifact, ExecutionLog, ExecutionStep, execution_artifact


async def get_execution(
    session: AsyncSession,
    execution_id: UUID,
    *,
    include_details: bool = True,
) -> ExecutionLog | None:
    statement = select(ExecutionLog).where(ExecutionLog.id == execution_id)
    if include_details:
        statement = statement.options(
            selectinload(ExecutionLog.agent),
            selectinload(ExecutionLog.session),
            selectinload(ExecutionLog.steps),
            selectinload(ExecutionLog.artifacts),
            selectinload(ExecutionLog.agent_version),
        )
    return (await session.scalars(statement)).first()


async def list_executions(
    session: AsyncSession,
    *,
    agent_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[ExecutionLog], int]:
    filters = _execution_filters(
        agent_id=agent_id,
        status=status,
        search=search,
        started_from=started_from,
        started_to=started_to,
    )
    base = select(ExecutionLog).join(Agent, Agent.id == ExecutionLog.agent_id).where(*filters)
    total = int(
        await session.scalar(
            select(func.count()).select_from(
                select(ExecutionLog.id)
                .join(Agent, Agent.id == ExecutionLog.agent_id)
                .where(*filters)
                .subquery()
            )
        )
        or 0
    )
    values = await session.scalars(
        base.options(
            selectinload(ExecutionLog.agent),
            selectinload(ExecutionLog.session),
            selectinload(ExecutionLog.steps),
            selectinload(ExecutionLog.artifacts),
            selectinload(ExecutionLog.agent_version),
        )
        .order_by(ExecutionLog.started_at.desc(), ExecutionLog.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(values.unique()), total


async def get_execution_metrics(
    session: AsyncSession,
    *,
    agent_id: str | None = None,
    status: str | None = None,
    search: str | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
) -> dict[str, int]:
    filters = _execution_filters(
        agent_id=agent_id,
        status=status,
        search=search,
        started_from=started_from,
        started_to=started_to,
    )
    row = (
        await session.execute(
            select(
                func.count(ExecutionLog.id).label("total"),
                func.count(ExecutionLog.id)
                .filter(ExecutionLog.status == "running")
                .label("running"),
                func.count(ExecutionLog.id)
                .filter(ExecutionLog.status == "succeeded")
                .label("succeeded"),
                func.count(ExecutionLog.id)
                .filter(ExecutionLog.status == "failed")
                .label("failed"),
                func.count(ExecutionLog.id)
                .filter(ExecutionLog.status == "cancelled")
                .label("cancelled"),
            )
            .select_from(ExecutionLog)
            .join(Agent, Agent.id == ExecutionLog.agent_id)
            .where(*filters)
        )
    ).one()
    return {
        "total": int(row.total or 0),
        "running": int(row.running or 0),
        "succeeded": int(row.succeeded or 0),
        "failed": int(row.failed or 0),
        "cancelled": int(row.cancelled or 0),
    }


def _execution_filters(
    *,
    agent_id: str | None,
    status: str | None,
    search: str | None,
    started_from: datetime | None,
    started_to: datetime | None,
) -> list[Any]:
    filters: list[Any] = []
    if agent_id:
        filters.append(ExecutionLog.agent_id == agent_id)
    if status:
        filters.append(ExecutionLog.status == status)
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                cast(ExecutionLog.id, String).ilike(pattern),
                ExecutionLog.input.ilike(pattern),
                Agent.name.ilike(pattern),
            )
        )
    if started_from:
        filters.append(ExecutionLog.started_at >= started_from)
    if started_to:
        filters.append(ExecutionLog.started_at <= started_to)
    return filters


async def start_step(
    session: AsyncSession,
    execution_id: UUID,
    *,
    step_key: str,
    sequence: int,
    step_type: str,
    step_name: str,
    input_data: dict[str, Any] | None = None,
    preserve_existing: bool = False,
) -> ExecutionStep:
    now = datetime.now(timezone.utc)
    statement = (
        insert(ExecutionStep)
        .values(
            id=uuid4(),
            execution_id=execution_id,
            step_key=step_key,
            sequence=sequence,
            step_type=step_type,
            step_name=step_name,
            status="running",
            input_data=input_data or {},
            output_data={},
            started_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_execution_steps_execution_key",
            set_=(
                {
                    "sequence": ExecutionStep.sequence,
                    "step_type": ExecutionStep.step_type,
                    "step_name": ExecutionStep.step_name,
                    "status": ExecutionStep.status,
                    "input_data": ExecutionStep.input_data,
                    "output_data": ExecutionStep.output_data,
                    "error": ExecutionStep.error,
                    "latency_ms": ExecutionStep.latency_ms,
                    "started_at": ExecutionStep.started_at,
                    "finished_at": ExecutionStep.finished_at,
                }
                if preserve_existing
                else {
                    "sequence": sequence,
                    "step_type": step_type,
                    "step_name": step_name,
                    "status": "running",
                    "input_data": input_data or {},
                    "output_data": {},
                    "error": None,
                    "latency_ms": None,
                    "started_at": now,
                    "finished_at": None,
                }
            ),
        )
        .returning(ExecutionStep)
    )
    step = (await session.scalars(statement)).one()
    await session.commit()
    return step


async def finish_step(
    session: AsyncSession,
    step: ExecutionStep,
    *,
    status: str = "succeeded",
    output_data: dict[str, Any] | None = None,
    error: str | None = None,
    preserve_existing: bool = False,
) -> ExecutionStep:
    finished = datetime.now(timezone.utc)
    step.status = status
    step.output_data = output_data or {}
    step.error = error[:2000] if error else None
    step.finished_at = finished
    if step.started_at:
        step.latency_ms = max(0, int((finished - step.started_at).total_seconds() * 1000))
    await session.commit()
    return step


async def record_step(
    session: AsyncSession,
    execution_id: UUID,
    *,
    step_key: str,
    sequence: int,
    step_type: str,
    step_name: str,
    status: str = "succeeded",
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    error: str | None = None,
    latency_ms: int | None = None,
) -> ExecutionStep:
    step = await start_step(
        session,
        execution_id,
        step_key=step_key,
        sequence=sequence,
        step_type=step_type,
        step_name=step_name,
        input_data=input_data,
    )
    finished = await finish_step(
        session, step, status=status, output_data=output_data, error=error
    )
    if latency_ms is not None:
        finished.latency_ms = max(0, latency_ms)
        await session.commit()
    return finished


async def fail_running_steps(session: AsyncSession, execution_id: UUID, error: str) -> None:
    values = await session.scalars(
        select(ExecutionStep).where(
            ExecutionStep.execution_id == execution_id,
            ExecutionStep.status == "running",
        )
    )
    now = datetime.now(timezone.utc)
    for step in values:
        step.status = "failed"
        step.error = error[:2000]
        step.finished_at = now
        if step.started_at:
            step.latency_ms = max(0, int((now - step.started_at).total_seconds() * 1000))
    await session.commit()


async def link_artifact(session: AsyncSession, execution_id: UUID, artifact_id: UUID) -> None:
    await session.execute(
        insert(execution_artifact)
        .values(execution_id=execution_id, artifact_id=artifact_id)
        .on_conflict_do_nothing()
    )
    await session.commit()


async def get_task_for_execution(session: AsyncSession, execution_id: UUID) -> AgentTask | None:
    return await session.scalar(select(AgentTask).where(AgentTask.execution_id == execution_id))


async def count_retries(session: AsyncSession, execution_id: UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(ExecutionLog).where(
                ExecutionLog.retry_of_execution_id == execution_id
            )
        )
        or 0
    )

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import AgentTeam, TeamMember, Workflow, WorkflowRun
from app.schemas.multi_agent import TeamCreate, TeamUpdate, WorkflowCreate, WorkflowUpdate


@dataclass(frozen=True)
class TeamConversationSummary:
    team_id: UUID
    session_id: str
    workflow_id: UUID | None
    workflow_name: str | None
    title: str
    latest_run_id: UUID
    latest_status: str
    run_count: int
    created_at: datetime
    updated_at: datetime


async def create_team(session: AsyncSession, payload: TeamCreate) -> AgentTeam:
    team = AgentTeam(
        name=payload.name,
        description=payload.description,
        owner_agent_id=payload.owner_agent_id,
        status=payload.status,
    )
    session.add(team)
    await session.flush()
    session.add(
        TeamMember(
            team_id=team.id,
            agent_id=payload.owner_agent_id,
            role="manager",
            priority=100,
        )
    )
    await session.commit()
    return await get_team(session, team.id)  # type: ignore[return-value]


async def get_team(session: AsyncSession, team_id: UUID) -> AgentTeam | None:
    statement = (
        select(AgentTeam)
        .options(
            selectinload(AgentTeam.owner_agent),
            selectinload(AgentTeam.members).selectinload(TeamMember.agent),
        )
        .where(AgentTeam.id == team_id)
    )
    return (await session.scalars(statement)).first()


async def list_teams(session: AsyncSession) -> list[AgentTeam]:
    values = await session.scalars(
        select(AgentTeam)
        .options(
            selectinload(AgentTeam.owner_agent),
            selectinload(AgentTeam.members).selectinload(TeamMember.agent),
        )
        .order_by(AgentTeam.created_at.desc())
    )
    return list(values.unique())


async def update_team(session: AsyncSession, team: AgentTeam, payload: TeamUpdate) -> AgentTeam:
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(team, key, value)
    await session.commit()
    return await get_team(session, team.id)  # type: ignore[return-value]


async def delete_team(session: AsyncSession, team: AgentTeam) -> None:
    await session.delete(team)
    await session.commit()


async def upsert_member(
    session: AsyncSession, *, team_id: UUID, agent_id: str, role: str, priority: int
) -> TeamMember:
    member = await session.get(TeamMember, (team_id, agent_id))
    if member is None:
        member = TeamMember(
            team_id=team_id, agent_id=agent_id, role=role, priority=priority
        )
        session.add(member)
    else:
        member.role = role
        member.priority = priority
    await session.commit()
    await session.refresh(member, attribute_names=["agent"])
    return member


async def remove_member(session: AsyncSession, *, team_id: UUID, agent_id: str) -> bool:
    result = await session.execute(
        delete(TeamMember).where(
            TeamMember.team_id == team_id, TeamMember.agent_id == agent_id
        )
    )
    await session.commit()
    return bool(result.rowcount)


async def agents_share_team(session: AsyncSession, first: str, second: str) -> bool:
    first_teams = select(TeamMember.team_id).where(TeamMember.agent_id == first)
    value = await session.scalar(
        select(TeamMember.team_id).where(
            TeamMember.agent_id == second, TeamMember.team_id.in_(first_teams)
        ).limit(1)
    )
    return value is not None


async def create_workflow(session: AsyncSession, payload: WorkflowCreate) -> Workflow:
    workflow = Workflow(
        team_id=payload.team_id,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        definition={"nodes": [node.model_dump(by_alias=True) for node in payload.nodes]},
    )
    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)
    return workflow


async def get_workflow(session: AsyncSession, workflow_id: UUID) -> Workflow | None:
    return await session.get(Workflow, workflow_id)


async def list_workflows(
    session: AsyncSession, *, team_id: UUID | None = None
) -> list[Workflow]:
    statement = select(Workflow)
    if team_id is not None:
        statement = statement.where(Workflow.team_id == team_id)
    values = await session.scalars(statement.order_by(Workflow.created_at.desc()))
    return list(values)


async def update_workflow(
    session: AsyncSession, workflow: Workflow, payload: WorkflowUpdate
) -> Workflow:
    values = payload.model_dump(exclude_unset=True)
    nodes = values.pop("nodes", None)
    for key, value in values.items():
        setattr(workflow, key, value)
    if nodes is not None:
        workflow.definition = {
            "nodes": [node.model_dump(by_alias=True) for node in payload.nodes or []]
        }
    await session.commit()
    await session.refresh(workflow)
    return workflow


async def delete_workflow(session: AsyncSession, workflow: Workflow) -> None:
    await session.delete(workflow)
    await session.commit()


async def create_run(
    session: AsyncSession,
    *,
    team_id: UUID,
    workflow_id: UUID | None,
    session_id: str,
    input_text: str,
) -> WorkflowRun:
    run = WorkflowRun(
        team_id=team_id,
        workflow_id=workflow_id,
        session_id=session_id,
        input=input_text,
        status="pending",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def get_run(session: AsyncSession, run_id: UUID) -> WorkflowRun | None:
    return await session.get(WorkflowRun, run_id)


async def list_runs(
    session: AsyncSession,
    *,
    team_id: UUID | None = None,
    workflow_id: UUID | None = None,
    session_id: str | None = None,
    active_only: bool = False,
) -> list[WorkflowRun]:
    statement = select(WorkflowRun)
    if team_id is not None:
        statement = statement.where(WorkflowRun.team_id == team_id)
    if workflow_id is not None:
        statement = statement.where(WorkflowRun.workflow_id == workflow_id)
    if session_id is not None:
        statement = statement.where(WorkflowRun.session_id == session_id)
    if active_only:
        statement = statement.where(
            WorkflowRun.status.in_(["pending", "running", "human_review"])
        )
    values = await session.scalars(statement.order_by(WorkflowRun.created_at.desc()))
    return list(values)


async def conversation_mode(
    session: AsyncSession, *, team_id: UUID, session_id: str
) -> tuple[bool, UUID | None]:
    statement = (
        select(WorkflowRun.workflow_id)
        .where(
            WorkflowRun.team_id == team_id,
            WorkflowRun.session_id == session_id,
        )
        .order_by(WorkflowRun.created_at.asc())
        .limit(1)
    )
    row = (await session.execute(statement)).first()
    return (row is not None, row[0] if row is not None else None)


async def list_conversation_runs(
    session: AsyncSession,
    *,
    team_id: UUID,
    session_id: str,
    limit: int,
    offset: int,
) -> tuple[list[WorkflowRun], int]:
    filters = (
        WorkflowRun.team_id == team_id,
        WorkflowRun.session_id == session_id,
    )
    total = int(await session.scalar(select(func.count(WorkflowRun.id)).where(*filters)) or 0)
    values = await session.scalars(
        select(WorkflowRun)
        .where(*filters)
        .order_by(WorkflowRun.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    return list(values), total


async def list_conversations(
    session: AsyncSession,
    *,
    team_id: UUID,
    limit: int,
    offset: int,
) -> tuple[list[TeamConversationSummary], int]:
    grouped = (
        select(
            WorkflowRun.session_id.label("session_id"),
            func.count(WorkflowRun.id).label("run_count"),
            func.min(WorkflowRun.created_at).label("created_at"),
            func.max(WorkflowRun.created_at).label("updated_at"),
        )
        .where(
            WorkflowRun.team_id == team_id,
            WorkflowRun.session_id.is_not(None),
        )
        .group_by(WorkflowRun.session_id)
        .subquery()
    )
    total = int(await session.scalar(select(func.count()).select_from(grouped)) or 0)
    group_rows = list(
        (
            await session.execute(
                select(grouped)
                .order_by(grouped.c.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )
    session_ids = [str(row.session_id) for row in group_rows]
    if not session_ids:
        return [], total
    runs = list(
        await session.scalars(
            select(WorkflowRun)
            .where(
                WorkflowRun.team_id == team_id,
                WorkflowRun.session_id.in_(session_ids),
            )
            .order_by(WorkflowRun.created_at.asc())
        )
    )
    workflows = {
        item.id: item.name
        for item in await session.scalars(
            select(Workflow).where(
                Workflow.id.in_({run.workflow_id for run in runs if run.workflow_id})
            )
        )
    }
    runs_by_session: dict[str, list[WorkflowRun]] = {}
    for run in runs:
        if run.session_id:
            runs_by_session.setdefault(run.session_id, []).append(run)
    groups_by_session = {str(row.session_id): row for row in group_rows}
    summaries: list[TeamConversationSummary] = []
    for session_key in session_ids:
        items = runs_by_session.get(session_key, [])
        if not items:
            continue
        first, latest = items[0], items[-1]
        group = groups_by_session[session_key]
        summaries.append(
            TeamConversationSummary(
                team_id=team_id,
                session_id=session_key,
                workflow_id=first.workflow_id,
                workflow_name=workflows.get(first.workflow_id),
                title=first.input,
                latest_run_id=latest.id,
                latest_status=latest.status,
                run_count=int(group.run_count),
                created_at=group.created_at,
                updated_at=group.updated_at,
            )
        )
    return summaries, total

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import AgentTeam, TeamMember, Workflow, WorkflowRun
from app.schemas.multi_agent import TeamCreate, TeamUpdate, WorkflowCreate, WorkflowUpdate


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
    session: AsyncSession, *, team_id: UUID, workflow_id: UUID | None, input_text: str
) -> WorkflowRun:
    run = WorkflowRun(
        team_id=team_id,
        workflow_id=workflow_id,
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
    active_only: bool = False,
) -> list[WorkflowRun]:
    statement = select(WorkflowRun)
    if team_id is not None:
        statement = statement.where(WorkflowRun.team_id == team_id)
    if workflow_id is not None:
        statement = statement.where(WorkflowRun.workflow_id == workflow_id)
    if active_only:
        statement = statement.where(
            WorkflowRun.status.in_(["pending", "running", "human_review"])
        )
    values = await session.scalars(statement.order_by(WorkflowRun.created_at.desc()))
    return list(values)

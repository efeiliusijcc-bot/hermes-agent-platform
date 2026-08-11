from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Agent, ExecutionLog, Skill
from app.schemas.agent import AgentCreate


async def create_agent(session: AsyncSession, payload: AgentCreate) -> Agent:
    agent = Agent(
        id=payload.id,
        name=payload.name,
        description=payload.description,
        role=payload.role,
        system_prompt=payload.system_prompt,
        model_settings=payload.model_settings,
        status=payload.status,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


async def list_agents(session: AsyncSession) -> list[Agent]:
    result = await session.scalars(select(Agent).order_by(Agent.created_at, Agent.id))
    return list(result.unique())


async def get_agent(session: AsyncSession, agent_id: str) -> Agent | None:
    return await session.get(Agent, agent_id)


async def delete_agent(session: AsyncSession, agent: Agent) -> None:
    await session.delete(agent)
    await session.commit()


async def list_execution_logs(session: AsyncSession, agent_id: str) -> list[ExecutionLog]:
    result = await session.scalars(
        select(ExecutionLog)
        .where(ExecutionLog.agent_id == agent_id)
        .order_by(ExecutionLog.started_at.desc())
    )
    return list(result)


async def bind_skill(session: AsyncSession, agent: Agent, skill: Skill) -> Agent:
    if all(item.id != skill.id for item in agent.skills):
        agent.skills.append(skill)
        await session.commit()
    return agent


async def unbind_skill(session: AsyncSession, agent: Agent, skill_id: str) -> bool:
    skill = next((item for item in agent.skills if item.id == skill_id), None)
    if skill is None:
        return False
    agent.skills.remove(skill)
    await session.commit()
    return True

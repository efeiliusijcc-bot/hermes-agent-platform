from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill
from app.schemas.skill import SkillCreate
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.skills.package import ImportedSkill


async def create_skill(session: AsyncSession, payload: SkillCreate) -> Skill:
    skill = Skill(
        id=payload.id,
        name=payload.name,
        description=payload.description,
        path=payload.path,
    )
    session.add(skill)
    await session.commit()
    await session.refresh(skill)
    return skill


async def register_imported_skill(session: AsyncSession, imported: "ImportedSkill") -> Skill:
    skill = Skill(
        id=imported.id,
        name=imported.name,
        description=imported.description,
        path=imported.path,
        version=imported.version,
        manifest=imported.manifest,
        package_sha256=imported.package_sha256,
    )
    session.add(skill)
    await session.commit()
    await session.refresh(skill)
    return skill


async def list_skills(session: AsyncSession) -> list[Skill]:
    result = await session.scalars(select(Skill).order_by(Skill.created_at, Skill.id))
    return list(result)


async def get_skill(session: AsyncSession, skill_id: str) -> Skill | None:
    return await session.get(Skill, skill_id)


async def delete_skill(session: AsyncSession, skill: Skill) -> None:
    await session.delete(skill)
    await session.commit()

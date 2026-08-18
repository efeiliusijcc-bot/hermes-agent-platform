from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill, SkillCapabilityRequirement, SkillVersion
from app.schemas.skill import SkillCreate
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.skills.package import ImportedSkill
from app.skills.package import skill_contract


async def create_skill(session: AsyncSession, payload: SkillCreate) -> Skill:
    skill = Skill(
        id=payload.id,
        name=payload.name,
        description=payload.description,
        path=payload.path,
        runtime_support=list(dict.fromkeys(payload.runtime_support)),
    )
    session.add(skill)
    await session.flush()
    session.add(
        SkillVersion(
            skill_id=skill.id,
            version="0.0.0",
            manifest={},
            status="published",
        )
    )
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
        runtime_support=list(imported.runtime_support),
        package_sha256=imported.package_sha256,
    )
    session.add(skill)
    await session.flush()
    version = SkillVersion(
        skill_id=skill.id,
        version=imported.version,
        manifest=imported.manifest,
        package_sha256=imported.package_sha256,
        status="published",
    )
    session.add(version)
    await session.flush()
    _, requirements, _ = skill_contract(imported.manifest)
    for requirement in requirements:
        session.add(
            SkillCapabilityRequirement(
                skill_version_id=version.id,
                alias=str(requirement["alias"]),
                capability_key=str(requirement["capability"]),
                version_range=str(requirement.get("version") or "*"),
                required=bool(requirement.get("required", True)),
                minimum_calls=int(requirement.get("minimum_calls") or 0),
                failure_policy=str(requirement.get("failure_policy") or "fail_closed"),
                config=(requirement.get("config") if isinstance(requirement.get("config"), dict) else {}),
            )
        )
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

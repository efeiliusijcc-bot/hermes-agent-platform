from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.repositories import skills as repository
from app.schemas.skill import SkillCreate, SkillRead
from app.skills import SkillLoadError, SkillLoader

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.post("", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def create_skill(payload: SkillCreate, session: AsyncSession = Depends(get_session)) -> SkillRead:
    try:
        SkillLoader().load_definition(skill_id=payload.id, name=payload.name, relative_path=payload.path)
    except SkillLoadError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    try:
        return SkillRead.model_validate(await repository.create_skill(session, payload))
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="skill id or path already exists") from exc


@router.get("", response_model=list[SkillRead])
async def list_skills(session: AsyncSession = Depends(get_session)) -> list[SkillRead]:
    return [SkillRead.model_validate(item) for item in await repository.list_skills(session)]


@router.get("/{skill_id}", response_model=SkillRead)
async def get_skill(skill_id: str, session: AsyncSession = Depends(get_session)) -> SkillRead:
    skill = await repository.get_skill(session, skill_id)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="skill not found")
    return SkillRead.model_validate(skill)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    skill = await repository.get_skill(session, skill_id)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="skill not found")
    await repository.delete_skill(session, skill)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

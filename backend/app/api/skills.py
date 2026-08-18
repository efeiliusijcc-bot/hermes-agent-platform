from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.management import require_platform_management_key_for_capability_control
from app.repositories import skills as repository
from app.schemas.skill import SkillCreate, SkillRead
from app.skills import SkillLoadError, SkillLoader, SkillPackageImporter

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.post("/upload", response_model=SkillRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_platform_management_key_for_capability_control)])
async def upload_skill(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> SkillRead:
    if file.content_type not in {"application/zip", "application/x-zip-compressed", "application/octet-stream"}:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Skill package must be a ZIP file")
    importer = SkillPackageImporter()
    imported = None
    try:
        package = await file.read(importer.max_upload_bytes + 1)
        imported = importer.import_zip(package)
        return SkillRead.model_validate(await repository.register_imported_skill(session, imported))
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        await session.rollback()
        if imported is not None:
            importer.remove(imported.path)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="skill id, path, or package already exists") from exc
    except SkillLoadError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    finally:
        await file.close()


@router.post("", response_model=SkillRead, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_platform_management_key_for_capability_control)])
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


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_platform_management_key_for_capability_control)])
async def delete_skill(skill_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    skill = await repository.get_skill(session, skill_id)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="skill not found")
    managed_path = skill.path if skill.package_sha256 else None
    removed_path = None
    if managed_path:
        importer = SkillPackageImporter()
        source = importer.validate_managed_path(managed_path)
        removed_path = source.with_name(f".{source.name}.deleting")
        if removed_path.exists():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill deletion is already in progress")
        source.rename(removed_path)
    try:
        await repository.delete_skill(session, skill)
    except Exception:
        if removed_path and removed_path.exists():
            removed_path.rename(SkillPackageImporter().root / managed_path)
        raise
    if removed_path:
        SkillPackageImporter().remove_staged(removed_path)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

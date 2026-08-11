from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from app.config import get_settings
from app.db.models import Skill


class SkillLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadedSkill:
    id: str
    name: str
    instructions: str
    config: dict[str, Any]

    def render(self) -> str:
        return f"<skill id=\"{self.id}\" name=\"{self.name}\">\n{self.instructions}\n</skill>"


class SkillLoader:
    def __init__(self) -> None:
        settings = get_settings()
        self.root = Path(settings.skills_root).resolve()
        self.max_document_bytes = settings.skill_max_document_bytes

    def load_many(self, skills: Iterable[Skill]) -> list[LoadedSkill]:
        return [self.load(skill) for skill in sorted(skills, key=lambda item: item.id)]

    def load(self, skill: Skill) -> LoadedSkill:
        return self.load_definition(skill_id=skill.id, name=skill.name, relative_path=skill.path)

    def load_definition(self, *, skill_id: str, name: str, relative_path: str) -> LoadedSkill:
        directory = self._resolve_directory(relative_path)
        instructions_path = directory / "SKILL.md"
        config_path = directory / "config.yaml"
        if not instructions_path.is_file() or not config_path.is_file():
            raise SkillLoadError(f"skill {skill_id} must contain SKILL.md and config.yaml")

        try:
            if instructions_path.stat().st_size > self.max_document_bytes:
                raise SkillLoadError(f"skill {skill_id} SKILL.md exceeds the size limit")
            instructions = instructions_path.read_text(encoding="utf-8").strip()
            config_value = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise SkillLoadError(f"skill {skill_id} could not be read: {exc}") from exc

        if not instructions:
            raise SkillLoadError(f"skill {skill_id} SKILL.md is empty")
        if not isinstance(config_value, dict):
            raise SkillLoadError(f"skill {skill_id} config.yaml must contain an object")
        if config_value.get("id") != skill_id:
            raise SkillLoadError(f"skill {skill_id} config id does not match the registry")
        return LoadedSkill(id=skill_id, name=name, instructions=instructions, config=config_value)

    def _resolve_directory(self, relative_path: str) -> Path:
        path = Path(relative_path)
        if path.is_absolute():
            raise SkillLoadError("skill paths must be relative to SKILLS_ROOT")
        resolved = (self.root / path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise SkillLoadError("skill path escapes SKILLS_ROOT") from exc
        if not resolved.is_dir():
            raise SkillLoadError(f"skill directory does not exist: {relative_path}")
        return resolved

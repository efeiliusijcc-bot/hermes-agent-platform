from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SkillCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    path: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    runtime_support: list[Literal["hermes", "pi", "deepseek"]] = Field(
        default_factory=lambda: ["hermes"], min_length=1
    )


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    path: str
    version: str
    manifest: dict[str, Any]
    runtime_support: list[Literal["hermes", "pi", "deepseek"]]
    package_sha256: str | None
    created_at: datetime
    updated_at: datetime


class AgentSkillBindingRead(BaseModel):
    agent_id: str
    skill_ids: list[str]

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    role: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    model_settings: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    status: Literal["draft", "active", "disabled"] = "draft"


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    description: str | None
    role: str
    system_prompt: str
    model_settings: dict[str, Any] = Field(
        validation_alias="model_settings",
        serialization_alias="model_config",
    )
    status: Literal["draft", "active", "disabled"]
    created_at: datetime
    updated_at: datetime

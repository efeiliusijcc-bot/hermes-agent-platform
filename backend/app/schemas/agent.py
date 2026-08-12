from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.schema_validation import normalize_schema


class AgentCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    role: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    model_settings: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    status: Literal["draft", "active", "disabled"] = "draft"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_schema", "output_schema")
    @classmethod
    def validate_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        return normalize_schema(value)


class AgentSchemaUpdate(BaseModel):
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_schema", "output_schema")
    @classmethod
    def validate_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        return normalize_schema(value)


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
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AgentRunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=100_000)
    session_id: str = Field(default="default", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class AgentRunResponse(BaseModel):
    execution_id: UUID
    agent_id: str
    session_id: str
    status: Literal["succeeded"]
    output: str
    hermes_run_id: str | None = None


class ExecutionLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: str
    status: Literal["running", "succeeded", "failed"]
    input: str
    output: str | None
    error: str | None
    details: dict[str, Any]
    started_at: datetime
    finished_at: datetime | None

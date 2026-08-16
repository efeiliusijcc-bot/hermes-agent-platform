from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.prompting import validate_prompt_template
from app.schemas.runtime import RuntimeType, validate_public_runtime_config
from app.schemas.schema_validation import normalize_schema

ResponseMode = Literal["sync", "stream"]
ModelAdapterName = Literal["hermes", "qwen", "deepseek", "gpt", "claude"]
AgentLifecycle = Literal["active", "inactive", "archived"]
AgentType = Literal["manager", "worker"]


class AgentCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    agent_type: AgentType = "worker"
    parent_agent_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    role: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    model_settings: dict[str, Any] = Field(default_factory=dict, alias="model_config")
    model: str = Field(default="hermes-agent", min_length=1, max_length=255)
    prompt_template: str = Field(default="{{input}}", min_length=1, max_length=100_000)
    model_adapter: ModelAdapterName = "hermes"
    runtime_type: RuntimeType = "hermes"
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    status: AgentLifecycle = "active"
    response_mode: ResponseMode = "sync"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_legacy_status(cls, value: Any) -> Any:
        # Compatibility is intentionally confined to input parsing; persisted
        # rows always use the v1 business lifecycle.
        return {
            "draft": "active",
            "testing": "active",
            "published": "active",
            "suspended": "inactive",
            "disabled": "inactive",
        }.get(value, value)

    @field_validator("input_schema", "output_schema")
    @classmethod
    def validate_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        return normalize_schema(value)

    @model_validator(mode="after")
    def validate_template_contract(self) -> "AgentCreate":
        validate_prompt_template(self.prompt_template, self.input_schema)
        validate_runtime_config(self.runtime_config)
        return self


class AgentSchemaUpdate(BaseModel):
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_schema", "output_schema")
    @classmethod
    def validate_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        return normalize_schema(value)


class AgentResponseModeUpdate(BaseModel):
    response_mode: ResponseMode


class AgentConfigurationUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    system_prompt: str = Field(min_length=1, max_length=100_000)
    model: str = Field(min_length=1, max_length=255)
    prompt_template: str = Field(min_length=1, max_length=100_000)
    model_adapter: ModelAdapterName
    runtime_type: RuntimeType | None = None
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    model_settings: dict[str, Any] = Field(default_factory=dict, alias="model_config")

    @field_validator("runtime_config")
    @classmethod
    def validate_runtime(cls, value: dict[str, Any]) -> dict[str, Any]:
        return validate_runtime_config(value)


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    description: str | None
    agent_type: AgentType
    parent_agent_id: str | None
    role: str
    system_prompt: str
    model_settings: dict[str, Any] = Field(
        validation_alias="model_settings",
        serialization_alias="model_config",
    )
    model: str
    prompt_template: str
    model_adapter: ModelAdapterName
    runtime_type: RuntimeType
    runtime_config: dict[str, Any]
    api_enabled: bool
    status: AgentLifecycle
    response_mode: ResponseMode
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    current_version_id: UUID | None
    created_at: datetime
    updated_at: datetime


class AgentRunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=100_000)
    session_id: str = Field(default="default", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    parameters: dict[str, Any] | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)


class AgentRunResponse(BaseModel):
    execution_id: UUID
    agent_id: str
    session_id: str
    status: Literal["succeeded"]
    output: str
    hermes_run_id: str | None = None
    runtime: RuntimeType
    runtime_run_id: str | None = None


class ExecutionLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: str
    session_id: UUID | None
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    input: str
    input_json: dict[str, Any]
    output: str | None
    output_json: Any | None
    error: str | None
    details: dict[str, Any]
    response_mode: Literal["sync", "stream", "async"]
    priority: int | None
    duration_ms: int | None
    token_usage: int | None
    runtime_type: RuntimeType
    runtime_id: UUID | None
    runtime_version: str | None
    retry_of_execution_id: UUID | None
    agent_version_id: UUID | None
    started_at: datetime
    finished_at: datetime | None


def validate_runtime_config(value: dict[str, Any]) -> dict[str, Any]:
    runtime_id = value.get("runtime_id")
    if runtime_id is not None:
        try:
            UUID(str(runtime_id))
        except ValueError as exc:
            raise ValueError("runtime_config.runtime_id must be a UUID") from exc
    return validate_public_runtime_config(value)

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


AgentLifecycle = Literal["active", "inactive", "archived"]
AgentVersionStatus = Literal[
    "development", "testing", "release_candidate", "published", "deprecated"
]
APIClientStatus = Literal["active", "suspended", "revoked"]


class LifecycleUpdate(BaseModel):
    status: AgentLifecycle


class APIClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    owner: str = Field(min_length=1, max_length=255)
    rate_limit_per_minute: int = Field(default=60, ge=1, le=100_000)


class APIClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    owner: str | None = Field(default=None, min_length=1, max_length=255)
    status: APIClientStatus | None = None
    rate_limit_per_minute: int | None = Field(default=None, ge=1, le=100_000)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "APIClientUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class APIClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    owner: str
    status: APIClientStatus
    rate_limit_per_minute: int
    key_count: int = 0
    agent_count: int = 0
    call_count: int = 0
    last_called_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class APIKeyCreate(BaseModel):
    name: str = Field(default="default", min_length=1, max_length=255)
    expires_at: datetime | None = None


class APIKeyStatusUpdate(BaseModel):
    status: Literal["revoked"]


class APIKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    client_id: UUID
    name: str
    prefix: str
    status: Literal["active", "revoked"]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    call_count: int = 0
    created_at: datetime


class APIKeySecret(APIKeyRead):
    api_key: str


class AgentBindingCreate(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    permission: Literal["invoke"] = "invoke"


class AgentBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    client_id: UUID
    agent_id: str
    permission: Literal["invoke"]
    created_at: datetime


class AgentVersionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    description: str | None = Field(default=None, max_length=2_000, validation_alias="notes")
    created_by: str = Field(default="system", min_length=1, max_length=255)


class AgentVersionUpdate(BaseModel):
    snapshot: dict[str, Any] | None = None
    description: str | None = Field(default=None, max_length=2_000, validation_alias="notes")

    @model_validator(mode="after")
    def at_least_one_field(self) -> "AgentVersionUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class AgentVersionStatusUpdate(BaseModel):
    status: Literal["development", "testing", "release_candidate"]


class AgentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: str
    version: str
    snapshot: dict[str, Any]
    snapshot_format_version: int = 1
    resolution_digest: str | None = None
    status: AgentVersionStatus
    description: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    deprecated_at: datetime | None


class AgentHealthCheck(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    detail: str


class AgentHealthRead(BaseModel):
    agent_id: str
    status: Literal["healthy", "degraded", "unhealthy"]
    checks: dict[str, AgentHealthCheck]
    checked_at: datetime


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: str
    client_id: UUID | None
    api_key_id: UUID | None
    agent_id: str | None
    status: Literal["succeeded", "failed", "rejected"]
    latency_ms: int
    token_usage: int | None
    mcp_call_count: int
    error_code: str | None
    created_at: datetime


class AgentMetricRead(BaseModel):
    agent_id: str
    agent_name: str | None = None
    metric_date: date | None = None
    call_count: int
    success_count: int
    failure_count: int
    success_rate: float | None
    average_latency_ms: float | None
    token_usage: int | None
    mcp_call_count: int


class MetricsSummaryRead(BaseModel):
    agent_count: int
    published_agent_count: int
    call_count: int
    success_count: int
    failure_count: int
    success_rate: float | None
    error_rate: float | None
    average_latency_ms: float | None
    token_usage: int | None
    mcp_call_count: int
    updated_at: datetime

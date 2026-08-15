from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent import ResponseMode


PublicationStatus = Literal["draft", "testing", "published", "disabled"]


class PublicationUpdate(BaseModel):
    status: PublicationStatus


class PublicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_id: str
    agent_name: str | None = None
    status: PublicationStatus
    response_mode: ResponseMode
    api_enabled: bool
    endpoint: str
    api_version: str = "v1"
    schema_version: str = "v1"
    api_key_prefix: str | None
    call_count: int
    last_called_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PublicationSecret(PublicationRead):
    api_key: str


class PublicAgentRunResponse(BaseModel):
    agent_id: str
    execution_id: UUID
    status: Literal["success"]
    result: Any
    trace: list[dict[str, Any]]


class PublicAgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: dict[str, Any]
    stream: bool | None = None
    session_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    )

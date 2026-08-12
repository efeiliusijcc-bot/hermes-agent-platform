from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

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
    endpoint: str
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

from __future__ import annotations

from datetime import datetime
from typing import Any
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


SessionStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TaskStatus = Literal[
    "pending",
    "running",
    "waiting_child",
    "human_review",
    "retrying",
    "succeeded",
    "failed",
    "cancelled",
]


class TaskSubmitRequest(BaseModel):
    input: str = Field(min_length=1, max_length=100_000)
    session_id: str = Field(default="default", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    priority: int = Field(default=5, ge=0, le=9)
    parameters: dict[str, Any] | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: str
    user_id: str | None
    memory_session_id: str
    runtime_type: Literal["hermes", "pi"]
    runtime_session_id: str | None
    status: SessionStatus
    input: str
    output: str | None
    workspace_path: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    parent_task_id: UUID | None
    workflow_id: UUID | None
    workflow_run_id: UUID | None
    node_key: str | None
    node_type: str
    depends_on: list[str]
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    agent_id: str
    session_id: UUID
    execution_id: UUID | None
    priority: int
    status: TaskStatus
    attempt: int
    max_attempts: int
    worker_id: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: str
    session_id: UUID
    filename: str
    storage_type: str
    storage_path: str
    content_type: str
    size_bytes: int
    sha256: str
    created_at: datetime

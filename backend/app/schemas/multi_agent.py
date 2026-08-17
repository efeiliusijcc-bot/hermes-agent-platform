from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


TeamStatus = Literal["active", "inactive", "archived"]
WorkflowStatus = Literal["draft", "active", "inactive", "archived"]
WorkflowRunStatus = Literal[
    "pending", "running", "human_review", "succeeded", "failed", "cancelled"
]
WorkflowNodeType = Literal["agent", "tool", "skill", "condition", "human_approval"]


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    owner_agent_id: str = Field(min_length=3, max_length=64)
    status: TeamStatus = "active"


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: TeamStatus | None = None


class TeamMemberUpsert(BaseModel):
    role: str = Field(min_length=1, max_length=128)
    priority: int = Field(default=50, ge=0, le=100)


class TeamMemberRead(BaseModel):
    agent_id: str
    agent_name: str
    agent_type: Literal["manager", "worker"]
    runtime_type: Literal["hermes", "pi", "deepseek"]
    role: str
    priority: int


class TeamRead(BaseModel):
    id: UUID
    name: str
    description: str | None
    owner_agent_id: str
    status: TeamStatus
    members: list[TeamMemberRead]
    created_at: datetime
    updated_at: datetime


class WorkflowNodeSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    node_type: WorkflowNodeType = Field(alias="type")
    name: str = Field(min_length=1, max_length=255)
    agent_id: str | None = Field(default=None, min_length=3, max_length=64)
    depends_on: list[str] = Field(default_factory=list, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_node_contract(self) -> "WorkflowNodeSpec":
        if self.node_type == "agent" and not self.agent_id:
            raise ValueError("agent workflow nodes require agent_id")
        if self.key in self.depends_on:
            raise ValueError(f"workflow node {self.key} cannot depend on itself")
        return self


class WorkflowCreate(BaseModel):
    team_id: UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: WorkflowStatus = "draft"
    nodes: list[WorkflowNodeSpec] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_dag(self) -> "WorkflowCreate":
        validate_workflow_dag(self.nodes)
        return self


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: WorkflowStatus | None = None
    nodes: list[WorkflowNodeSpec] | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_dag(self) -> "WorkflowUpdate":
        if self.nodes is not None:
            validate_workflow_dag(self.nodes)
        return self


class WorkflowRead(BaseModel):
    id: UUID
    team_id: UUID
    name: str
    description: str | None
    status: WorkflowStatus
    nodes: list[WorkflowNodeSpec]
    created_at: datetime
    updated_at: datetime


class MultiAgentRunRequest(BaseModel):
    input: str = Field(min_length=1, max_length=100_000)
    session_id: str = Field(default="multi-agent", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    user_id: str | None = Field(default=None, min_length=1, max_length=128)
    priority: int = Field(default=5, ge=0, le=9)
    parameters: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_id: UUID | None
    team_id: UUID
    status: WorkflowRunStatus
    input: str
    output: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class HumanApprovalRequest(BaseModel):
    approved: bool
    note: str | None = Field(default=None, max_length=2000)


class AgentMessageCreate(BaseModel):
    from_agent: str = Field(min_length=3, max_length=64)
    to_agent: str = Field(min_length=3, max_length=64)
    message_type: Literal["task", "result", "event", "error"] = "event"
    payload: dict[str, Any] = Field(default_factory=dict)
    task_id: UUID | None = None


class AgentMessageRead(AgentMessageCreate):
    id: str
    created_at: datetime


def validate_workflow_dag(nodes: list[WorkflowNodeSpec]) -> None:
    by_key = {node.key: node for node in nodes}
    if len(by_key) != len(nodes):
        raise ValueError("workflow node keys must be unique")
    for node in nodes:
        missing = [key for key in node.depends_on if key not in by_key]
        if missing:
            raise ValueError(f"workflow node {node.key} has unknown dependencies: {', '.join(missing)}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        if key in visiting:
            raise ValueError("workflow graph contains a cycle")
        visiting.add(key)
        for dependency in by_key[key].depends_on:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in by_key:
        visit(key)

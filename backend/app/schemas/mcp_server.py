from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MCPServerCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    name: str = Field(min_length=1, max_length=255)
    endpoint: str = Field(min_length=1, max_length=2048)
    config: dict[str, Any]
    permission: Literal["read_only"] = "read_only"

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        kind = value.get("kind")
        if kind not in {"filesystem", "database"}:
            raise ValueError("config.kind must be filesystem or database")
        if value.get("read_only") is not True:
            raise ValueError("first-stage MCP servers must be read-only")
        return value


class MCPServerUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    endpoint: str = Field(min_length=1, max_length=2048)
    config: dict[str, Any]
    permission: Literal["read_only"] = "read_only"

    @field_validator("config")
    @classmethod
    def validate_config(cls, value: dict[str, Any]) -> dict[str, Any]:
        return MCPServerCreate.validate_config(value)


class MCPServerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    endpoint: str
    config: dict[str, Any]
    permission: Literal["read_only"]
    status: Literal["unknown", "online", "offline"]
    created_at: datetime
    updated_at: datetime


class MCPServerTestRead(BaseModel):
    id: str
    status: Literal["online", "offline"]
    latency_ms: int
    detail: str


class AgentMCPBindingRead(BaseModel):
    agent_id: str
    mcp_ids: list[str]
    capabilities: list[Literal["filesystem", "database"]]

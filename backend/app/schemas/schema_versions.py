from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.schema_validation import normalize_schema


LifecycleStatus = Literal["draft", "testing", "published", "deprecated", "disabled"]
VERSION_PATTERN = r"^v[1-9][0-9]{0,8}$"


class SchemaVersionCreate(BaseModel):
    version: str = Field(pattern=VERSION_PATTERN)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_schema", "output_schema")
    @classmethod
    def validate_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        return normalize_schema(value)


class SchemaVersionUpdate(BaseModel):
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input_schema", "output_schema")
    @classmethod
    def validate_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        return normalize_schema(value)


class LifecycleUpdate(BaseModel):
    status: LifecycleStatus


class SchemaVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: str
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    status: LifecycleStatus
    created_at: datetime
    published_at: datetime | None


class APIVersionCreate(BaseModel):
    api_version: str = Field(pattern=VERSION_PATTERN)
    schema_version: str = Field(pattern=VERSION_PATTERN)


class APIVersionBindingUpdate(BaseModel):
    schema_version: str = Field(pattern=VERSION_PATTERN)


class APIVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: str
    api_version: str
    schema_version_id: UUID
    schema_version: SchemaVersionRead
    status: LifecycleStatus
    endpoint: str
    created_at: datetime
    published_at: datetime | None

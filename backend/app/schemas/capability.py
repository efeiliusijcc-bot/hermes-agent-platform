from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CapabilityCreate(BaseModel):
    namespace: str = Field(default="platform", min_length=1, max_length=128)
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,254}$")
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] = "LOW"


class CapabilityUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    risk_level: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    status: Literal["draft", "testing", "published", "deprecated", "disabled"] | None = None


class CapabilityRead(ORMModel):
    id: UUID
    namespace: str
    key: str
    display_name: str
    description: str | None
    risk_level: str
    status: str
    created_at: datetime
    updated_at: datetime


class CapabilityVersionCreate(BaseModel):
    version: str = Field(pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    ui_schema: dict[str, Any] = Field(default_factory=dict)
    error_schema: dict[str, Any] = Field(default_factory=dict)
    side_effect: Literal["READ_ONLY", "WRITE", "DESTRUCTIVE", "EXTERNAL_COMMUNICATION", "LONG_RUNNING"] = "READ_ONLY"
    idempotency: Literal["SAFE_RETRY", "IDEMPOTENT", "NON_IDEMPOTENT"] = "SAFE_RETRY"
    cache_policy: dict[str, Any] = Field(default_factory=dict)
    default_timeout_ms: int = Field(default=15000, ge=100, le=300000)
    compatibility: dict[str, Any] = Field(default_factory=dict)


class CapabilityVersionRead(ORMModel):
    id: UUID
    capability_id: UUID
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    ui_schema: dict[str, Any]
    error_schema: dict[str, Any]
    side_effect: str
    idempotency: str
    cache_policy: dict[str, Any]
    default_timeout_ms: int
    compatibility: dict[str, Any]
    status: str
    published_at: datetime | None
    created_at: datetime


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    credential_type: str = Field(min_length=1, max_length=64)
    secret: SecretStr
    masked_label: str | None = Field(default=None, max_length=255)


class CredentialRotate(BaseModel):
    secret: SecretStr
    masked_label: str | None = Field(default=None, max_length=255)


class CredentialRead(ORMModel):
    id: UUID
    name: str
    credential_type: str
    masked_label: str
    key_id: str
    rotation_status: str
    last_rotated_at: datetime
    created_at: datetime
    updated_at: datetime


class ConnectorCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,254}$")
    display_name: str = Field(min_length=1, max_length=255)
    type: Literal["internal_rest", "mcp", "postgresql_mcp"]
    description: str | None = None


class ConnectorUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: Literal["draft", "published", "disabled"] | None = None


class ConnectorRead(ORMModel):
    id: UUID
    key: str
    display_name: str
    type: str
    description: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class ConnectorInstanceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    environment: str = Field(default="production", min_length=1, max_length=64)


class ConnectorInstanceRead(ORMModel):
    id: UUID
    connector_id: UUID
    name: str
    environment: str
    current_revision_id: UUID | None
    health_status: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ConnectorRevisionCreate(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    auth_type: Literal["none", "bearer", "header"] = "none"
    credential_ref: UUID | None = None
    network_zone: Literal["internal", "dmz"] = "internal"
    connection_config: dict[str, Any] = Field(default_factory=dict)
    timeout_policy: dict[str, Any] = Field(default_factory=dict)
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    health_check_config: dict[str, Any] = Field(default_factory=dict)


class ConnectorRevisionRead(ORMModel):
    id: UUID
    connector_instance_id: UUID
    revision: int
    endpoint: str
    auth_type: str
    credential_ref: UUID | None
    network_zone: str
    connection_config: dict[str, Any]
    timeout_policy: dict[str, Any]
    retry_policy: dict[str, Any]
    health_check_config: dict[str, Any]
    config_digest: str
    created_at: datetime


class ConnectorOperationCreate(BaseModel):
    operation_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,254}$")
    display_name: str = Field(min_length=1, max_length=255)
    protocol: Literal["internal_rest", "mcp"]
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] | None = None
    path_or_tool: str = Field(min_length=1, max_length=2048)
    request_schema: dict[str, Any] = Field(default_factory=dict)
    response_schema: dict[str, Any] = Field(default_factory=dict)
    request_mapping: dict[str, Any] = Field(default_factory=dict)
    response_mapping: dict[str, Any] = Field(default_factory=dict)
    error_mapping: dict[str, Any] = Field(default_factory=dict)
    side_effect: Literal["READ_ONLY", "WRITE", "DESTRUCTIVE", "EXTERNAL_COMMUNICATION", "LONG_RUNNING"] = "READ_ONLY"

    @field_validator("method")
    @classmethod
    def require_rest_method(cls, value: str | None, info: Any) -> str | None:
        if info.data.get("protocol") == "internal_rest" and value is None:
            raise ValueError("Internal REST Operation 必须配置 method")
        return value


class ConnectorOperationRead(ORMModel):
    id: UUID
    connector_id: UUID
    operation_key: str
    display_name: str
    protocol: str
    method: str | None
    path_or_tool: str
    request_schema: dict[str, Any]
    response_schema: dict[str, Any]
    request_mapping: dict[str, Any]
    response_mapping: dict[str, Any]
    error_mapping: dict[str, Any]
    side_effect: str
    status: str


class CapabilityImplementationCreate(BaseModel):
    capability_version_id: UUID
    connector_operation_id: UUID
    connector_instance_revision_id: UUID
    mapping_override: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100, ge=0, le=10000)
    routing_weight: int = Field(default=100, ge=0, le=10000)


class CapabilityImplementationRead(ORMModel):
    id: UUID
    capability_version_id: UUID
    connector_operation_id: UUID
    connector_instance_revision_id: UUID
    mapping_override: dict[str, Any]
    priority: int
    routing_weight: int
    status: str


class ResourceCreate(BaseModel):
    resource_type: str = Field(min_length=1, max_length=64)
    key: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    connector_instance_id: UUID
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceRead(ORMModel):
    id: UUID
    resource_type: str
    key: str
    display_name: str
    connector_instance_id: UUID
    metadata: dict[str, Any] = Field(validation_alias="resource_metadata", serialization_alias="metadata")
    status: str


class ResourceScopeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    resource_type: str = Field(min_length=1, max_length=64)
    scope_definition: dict[str, Any] = Field(default_factory=dict)


class ResourceScopeRevisionCreate(BaseModel):
    scope_definition: dict[str, Any] = Field(default_factory=dict)


class ResourceScopeRead(ORMModel):
    id: UUID
    name: str
    resource_type: str
    current_revision_id: UUID | None
    created_at: datetime


class ResourceScopeRevisionRead(ORMModel):
    id: UUID
    resource_scope_id: UUID
    revision: int
    scope_definition: dict[str, Any]
    scope_digest: str
    created_at: datetime


class AgentCapabilityBindingWrite(BaseModel):
    tool_alias: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    capability_version_id: UUID
    implementation_mode: Literal["PINNED", "DEFAULT_PRIORITY"] = "PINNED"
    implementation_id: UUID | None = None
    resource_scope_revision_id: UUID | None = None
    parameter_policy: dict[str, Any] = Field(default_factory=dict)
    quota_policy: dict[str, Any] = Field(default_factory=dict)
    approval_policy: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    source_type: Literal["direct", "skill", "workflow", "template", "legacy"] = "direct"
    source_ref_id: str | None = None


class AgentCapabilityBindingsUpdate(BaseModel):
    bindings: list[AgentCapabilityBindingWrite]


class AgentCapabilityBindingRead(ORMModel):
    id: UUID
    agent_version_id: UUID
    tool_alias: str
    capability_version_id: UUID
    implementation_mode: str
    implementation_id: UUID | None
    resource_scope_revision_id: UUID | None
    parameter_policy: dict[str, Any]
    quota_policy: dict[str, Any]
    approval_policy: dict[str, Any]
    enabled: bool
    source_type: str
    source_ref_id: str | None


class CapabilityInvocationRead(ORMModel):
    id: UUID
    execution_id: UUID
    agent_id: str
    agent_version_id: UUID | None
    binding_id: UUID | None
    capability_key: str
    capability_version: str
    tool_alias: str
    connector_instance_revision_id: UUID | None
    resource_scope_revision_id: UUID | None
    status: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    error_code: str | None
    latency_ms: int | None
    cache_hit: bool
    created_at: datetime
    finished_at: datetime | None

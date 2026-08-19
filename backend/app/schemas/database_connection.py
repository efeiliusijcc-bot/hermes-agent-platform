from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


class PostgreSQLEndpoint(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    maintenance_database: str = Field(default="postgres", min_length=1, max_length=63)
    ssl_mode: Literal["disable", "prefer", "require", "verify-ca", "verify-full"] = "disable"
    connect_timeout_seconds: int = Field(default=5, ge=1, le=60)

    @field_validator("host", "maintenance_database")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(ord(character) < 32 for character in cleaned):
            raise ValueError("连接参数包含非法字符")
        return cleaned


class PostgreSQLCredentialInput(BaseModel):
    username: str = Field(min_length=1, max_length=63)
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(ord(character) < 32 for character in cleaned):
            raise ValueError("数据库用户名包含非法字符")
        return cleaned


class DatabaseObjectSelection(BaseModel):
    name: str = Field(min_length=1, max_length=63)
    tables: list[str] = Field(default_factory=list)
    views: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def normalize_schema_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(ord(character) < 32 for character in cleaned):
            raise ValueError("Schema 名称包含非法字符")
        return cleaned

    @field_validator("tables", "views")
    @classmethod
    def validate_object_names(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 63 or any(ord(character) < 32 for character in value) for value in cleaned):
            raise ValueError("数据库对象名称无效")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("数据库对象不能重复")
        return cleaned


class DatabaseScopeSelection(BaseModel):
    database: str = Field(min_length=1, max_length=63)
    name: str | None = Field(default=None, max_length=255)
    schemas: list[DatabaseObjectSelection] = Field(min_length=1)
    allow_describe: bool = True
    allow_query: bool = True
    allow_preview: bool = True
    allow_aggregate: bool = True
    max_rows: int = Field(default=200, ge=1, le=10_000)
    statement_timeout_ms: int = Field(default=5000, ge=100, le=300_000)
    lock_timeout_ms: int = Field(default=1000, ge=50, le=60_000)
    max_response_bytes: int = Field(default=2_097_152, ge=1024, le=20_971_520)
    requests_per_minute: int = Field(default=60, ge=1, le=10_000)

    @field_validator("database")
    @classmethod
    def normalize_database_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(ord(character) < 32 for character in cleaned):
            raise ValueError("数据库名称包含非法字符")
        return cleaned

    @model_validator(mode="after")
    def validate_selection_shape(self) -> "DatabaseScopeSelection":
        names = [item.name for item in self.schemas]
        if len(set(names)) != len(names):
            raise ValueError("Scope 中的 Schema 不能重复")
        if not any(item.tables or item.views for item in self.schemas):
            raise ValueError("Scope 至少选择一个表或视图")
        for item in self.schemas:
            if set(item.tables) & set(item.views):
                raise ValueError(f"对象不能同时作为表和视图：{item.name}")
        return self


class DatabaseConnectionTestRequest(BaseModel):
    endpoint: PostgreSQLEndpoint
    credential: PostgreSQLCredentialInput


class DatabaseConnectionCreate(DatabaseConnectionTestRequest):
    name: str = Field(min_length=1, max_length=255)
    environment: Literal["development", "test", "production"] = "production"
    scopes: list[DatabaseScopeSelection] = Field(min_length=1)


class DatabaseConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    environment: Literal["development", "test", "production"] | None = None
    enabled: bool | None = None
    endpoint: PostgreSQLEndpoint | None = None


class DatabaseCredentialReplace(BaseModel):
    username: str = Field(min_length=1, max_length=63)
    password: SecretStr = Field(min_length=1, max_length=1024)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return PostgreSQLCredentialInput.normalize_username(value)


class DatabaseScopeCreate(BaseModel):
    scope: DatabaseScopeSelection


class DatabaseAgentBinding(BaseModel):
    scope_revision_id: str
    tool_prefix: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    operations: list[
        Literal["list_schemas", "list_tables", "describe_table", "preview_table", "select", "explain"]
    ] = Field(min_length=1)


class DatabaseAgentBindingsUpdate(BaseModel):
    bindings: list[DatabaseAgentBinding]

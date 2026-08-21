from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


DatabaseType: TypeAlias = Literal[
    "postgresql",
    "mysql",
    "mariadb",
    "doris",
    "starrocks",
    "sqlserver",
    "oracle",
    "dm",
    "clickhouse",
    "elasticsearch",
    "sqlite",
]


DEFAULT_DATABASE_PORTS: dict[str, int] = {
    "postgresql": 5432,
    "mysql": 3306,
    "mariadb": 3306,
    "doris": 9030,
    "starrocks": 9030,
    "sqlserver": 1433,
    "oracle": 1521,
    "dm": 5236,
    "clickhouse": 8123,
    "elasticsearch": 9200,
    "sqlite": 0,
}


class DatabaseEndpoint(BaseModel):
    database_type: DatabaseType = "postgresql"
    host: str = Field(default="", max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    maintenance_database: str = Field(default="", max_length=255)
    ssl_mode: Literal["disable", "prefer", "require", "verify-ca", "verify-full"] = "disable"
    connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    service_name: str | None = Field(default=None, max_length=255)
    database_file: str | None = Field(default=None, max_length=1024)
    url_path_prefix: str = Field(default="", max_length=255)

    @field_validator("host", "maintenance_database", "service_name", "database_file", "url_path_prefix")
    @classmethod
    def reject_control_characters(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if any(ord(character) < 32 for character in cleaned):
            raise ValueError("连接参数包含非法字符")
        return cleaned

    @model_validator(mode="after")
    def validate_endpoint(self) -> "DatabaseEndpoint":
        if self.database_type == "sqlite":
            if not self.database_file:
                raise ValueError("SQLite 需要数据库文件路径")
            self.host = ""
            self.port = None
            self.maintenance_database = self.maintenance_database or "main"
            return self
        if not self.host:
            raise ValueError("数据库主机不能为空")
        self.port = self.port or DEFAULT_DATABASE_PORTS[self.database_type]
        defaults = {
            "postgresql": "postgres",
            "mysql": "mysql",
            "mariadb": "mysql",
            "doris": "information_schema",
            "starrocks": "information_schema",
            "sqlserver": "master",
            "oracle": self.service_name or "ORCL",
            "dm": "DM",
            "clickhouse": "default",
            "elasticsearch": "_cluster",
        }
        self.maintenance_database = self.maintenance_database or str(defaults[self.database_type])
        if self.database_type == "oracle":
            self.service_name = self.service_name or self.maintenance_database
        if self.database_type == "elasticsearch" and self.url_path_prefix and not self.url_path_prefix.startswith("/"):
            raise ValueError("Elasticsearch URL 路径前缀必须以 / 开头")
        return self


class DatabaseCredentialInput(BaseModel):
    username: str = Field(default="", max_length=255)
    password: SecretStr = Field(default="", max_length=4096)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        cleaned = value.strip()
        if any(ord(character) < 32 for character in cleaned):
            raise ValueError("数据库用户名包含非法字符")
        return cleaned


class DatabaseObjectSelection(BaseModel):
    name: str = Field(min_length=1, max_length=255)
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
        if any(not value or len(value) > 255 or any(ord(character) < 32 for character in value) for value in cleaned):
            raise ValueError("数据库对象名称无效")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("数据库对象不能重复")
        return cleaned


class DatabaseScopeSelection(BaseModel):
    database: str = Field(min_length=1, max_length=255)
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
    endpoint: DatabaseEndpoint
    credential: DatabaseCredentialInput

    @model_validator(mode="after")
    def require_network_credentials(self) -> "DatabaseConnectionTestRequest":
        if self.endpoint.database_type != "sqlite":
            if not self.credential.username or not self.credential.password.get_secret_value():
                raise ValueError("请填写数据库用户名和密码")
        return self


class DatabaseConnectionCreate(DatabaseConnectionTestRequest):
    name: str = Field(min_length=1, max_length=255)
    environment: Literal["development", "test", "production"] = "production"
    scopes: list[DatabaseScopeSelection] = Field(min_length=1)


class DatabaseConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    environment: Literal["development", "test", "production"] | None = None
    enabled: bool | None = None
    endpoint: DatabaseEndpoint | None = None


class DatabaseCredentialReplace(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=4096)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return DatabaseCredentialInput.normalize_username(value)


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


# Compatibility aliases for published integrations and older imports.
PostgreSQLEndpoint = DatabaseEndpoint
PostgreSQLCredentialInput = DatabaseCredentialInput

from functools import lru_cache
from urllib.parse import quote_plus

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    app_name: str = "Hermes Agent Platform"
    app_env: str = "production"
    log_level: str = "INFO"

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "hermes_agent"
    postgres_user: str = "hermes_agent"
    postgres_password: SecretStr

    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_pool_timeout: int = Field(default=30, ge=1, le=300)

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = Field(default=0, ge=0, le=15)
    redis_password: SecretStr
    redis_socket_timeout_seconds: int = Field(default=5, ge=1, le=30)

    task_queue_key: str = "hermes:agent-tasks:v1"
    task_queue_poll_seconds: float = Field(default=1.0, ge=0.1, le=30.0)
    task_max_attempts: int = Field(default=3, ge=1, le=10)
    task_retry_delay_seconds: float = Field(default=1.0, ge=0.0, le=300.0)
    task_stale_seconds: int = Field(default=600, ge=30, le=86_400)
    worker_concurrency: int = Field(default=4, ge=1, le=64)
    worker_id: str = "agent-worker"
    orchestrator_poll_seconds: float = Field(default=1.0, ge=0.1, le=30.0)
    agent_message_stream_key: str = "hermes:agent-messages:v1"
    agent_message_max_length: int = Field(default=10_000, ge=100, le=1_000_000)

    workspace_root: str = "/data/workspaces"

    artifact_storage_provider: Literal["local", "minio", "nas"] = "minio"
    artifact_local_root: str = "/data/artifacts"
    artifact_nas_root: str = "/data/artifacts"
    artifact_max_bytes: int = Field(default=104_857_600, ge=1, le=1_073_741_824)
    artifact_minio_bucket: str = "artifacts"
    minio_endpoint: str = "minio:9000"
    minio_root_user: str = "hermes_minio"
    minio_root_password: SecretStr
    minio_secure: bool = False

    agent_memory_max_turns: int = Field(default=8, ge=1, le=50)
    agent_memory_ttl_seconds: int = Field(default=2_592_000, ge=60, le=31_536_000)
    agent_memory_max_message_chars: int = Field(default=20_000, ge=256, le=100_000)
    memory_provider: Literal["redis", "postgres", "vector"] = "redis"
    memory_type: str = Field(default="short-term", pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

    knowledge_service_endpoint: str = "http://knowledge-service:8081"
    knowledge_service_timeout_seconds: int = Field(default=60, ge=5, le=300)
    knowledge_search_top_k: int = Field(default=5, ge=1, le=20)
    knowledge_max_upload_bytes: int = Field(default=10_485_760, ge=1024, le=104_857_600)

    source_recall_enabled: bool = False
    source_recall_gateway_endpoint: str = "http://source-recall-gateway:8082"
    source_recall_gateway_api_key: SecretStr | None = None
    source_recall_timeout_seconds: int = Field(default=60, ge=5, le=300)
    source_recall_default_lookback_days: int = Field(default=3650, ge=1, le=36_500)
    source_recall_default_limit: int = Field(default=20, ge=1, le=20)
    source_recall_summary_max_chars: int = Field(default=1200, ge=100, le=10_000)
    source_recall_excerpt_max_chars: int = Field(default=2000, ge=100, le=20_000)

    model_endpoint: str | None = None
    model_api_key: SecretStr | None = None
    model_name: str | None = None
    model_registry_encryption_key: SecretStr | None = None
    model_management_api_key: SecretStr | None = None

    hermes_endpoint: str = "http://hermes-runtime:8642/v1"
    hermes_api_key: SecretStr
    hermes_model: str = "hermes-agent"
    hermes_timeout_seconds: int = Field(default=180, ge=10, le=1800)
    hermes_poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=30.0)
    hermes_runtime_version: str = "0.20.0"

    pi_runtime_endpoint: str = "http://pi-runtime:8765"
    pi_runtime_api_key: SecretStr | None = None
    pi_runtime_timeout_seconds: int = Field(default=180, ge=10, le=1800)
    pi_runtime_version: str = "0.84.2"
    deepseek_runtime_endpoint: str | None = None
    deepseek_runtime_api_key: SecretStr | None = None
    deepseek_runtime_timeout_seconds: int = Field(default=900, ge=10, le=7200)
    deepseek_runtime_version: str = "0.1.0-rc.6"
    runtime_auto_register: bool = True

    skills_root: str = "/app/skills"
    skill_max_document_bytes: int = Field(default=262_144, ge=1024, le=1_048_576)
    skill_max_upload_bytes: int = Field(default=10_485_760, ge=1024, le=104_857_600)
    skill_max_extracted_bytes: int = Field(default=52_428_800, ge=1024, le=524_288_000)
    skill_max_archive_entries: int = Field(default=512, ge=2, le=10_000)

    mcp_gateway_endpoint: str = "http://mcp-gateway:8090/mcp"
    mcp_gateway_signing_key: SecretStr = Field(min_length=32)

    @property
    def database_url(self) -> str:
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password.get_secret_value())
        return f"postgresql+asyncpg://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache
from urllib.parse import quote_plus

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

    hermes_endpoint: str = "http://hermes-runtime:8642/v1"
    hermes_api_key: SecretStr
    hermes_model: str = "hermes-agent"
    hermes_timeout_seconds: int = Field(default=180, ge=10, le=1800)
    hermes_poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=30.0)

    @property
    def database_url(self) -> str:
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password.get_secret_value())
        return f"postgresql+asyncpg://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


@lru_cache
def get_settings() -> Settings:
    return Settings()

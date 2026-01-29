"""Application configuration using Pydantic Settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "Transportation Validator"
    app_version: str = "0.1.0"
    debug: bool = False

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://transportations:transportations_dev@localhost:5432/transportations_validator"
    database_pool_size: int = 5
    database_max_overflow: int = 10

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_dev_password"

    # API
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]

    # Neo4j Sync
    neo4j_sync_delay: float = 5.0  # Debounce delay in seconds


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

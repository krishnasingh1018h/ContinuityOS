import os
import secrets
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./continuityos.db"
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48), min_length=32)
    session_cookie_secure: bool = Field(default_factory=lambda: os.getenv("VERCEL") == "1")
    max_upload_bytes: int = 2_000_000
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = Field(default="openai/gpt-4o-mini", min_length=1, max_length=200)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @field_validator("database_url")
    @classmethod
    def use_psycopg_driver(cls, database_url: str) -> str:
        if database_url.startswith("postgres://"):
            return database_url.replace("postgres://", "postgresql+psycopg://", 1)
        if database_url.startswith("postgresql://"):
            return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return database_url

    @model_validator(mode="after")
    def require_persistent_vercel_settings(self) -> "Settings":
        if os.getenv("VERCEL") == "1":
            if not os.getenv("SECRET_KEY"):
                raise ValueError("SECRET_KEY must be configured for Vercel deployments")
            if self.database_url.startswith("sqlite"):
                raise ValueError("DATABASE_URL must use persistent PostgreSQL on Vercel")
            if not self.session_cookie_secure:
                raise ValueError("SESSION_COOKIE_SECURE must be true on Vercel")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

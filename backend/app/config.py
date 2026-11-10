import secrets
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./continuityos.db"
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(48), min_length=32)
    session_cookie_secure: bool = False
    max_upload_bytes: int = 2_000_000
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = Field(default="openai/gpt-4o-mini", min_length=1, max_length=200)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()

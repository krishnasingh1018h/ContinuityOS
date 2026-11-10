import pytest
from pydantic import ValidationError

from app.config import Settings
from app.database import create_database_engine


def test_postgresql_urls_use_installed_psycopg_driver() -> None:
    settings = Settings(_env_file=None, database_url="postgresql://user:pass@db.example/app")

    assert settings.database_url == "postgresql+psycopg://user:pass@db.example/app"


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:pass@db.example/app",
        "postgresql+psycopg2://user:pass@db.example/app",
    ],
)
def test_database_engine_uses_psycopg3_for_postgresql(database_url: str) -> None:
    engine = create_database_engine(database_url)
    try:
        assert engine.url.drivername == "postgresql+psycopg"
    finally:
        engine.dispose()


def test_vercel_requires_a_secret_and_persistent_database(monkeypatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example/app")

    with pytest.raises(ValidationError, match="SECRET_KEY must be configured"):
        Settings(_env_file=None)

    monkeypatch.setenv("SECRET_KEY", "s" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./continuityos.db")
    with pytest.raises(ValidationError, match="persistent PostgreSQL"):
        Settings(_env_file=None)


def test_vercel_enables_secure_session_cookies(monkeypatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("SECRET_KEY", "s" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example/app")
    monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.session_cookie_secure is True
    assert settings.database_url.startswith("postgresql+psycopg://")

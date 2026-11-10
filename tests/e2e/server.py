import os
import secrets
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="continuityos-e2e-") as directory:
        database_path = Path(directory) / "continuityos.db"
        os.environ["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
        os.environ["OPENROUTER_API_KEY"] = ""
        os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)

        from alembic import command
        from alembic.config import Config

        command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")

        import uvicorn

        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=8766,
            log_level="warning",
        )


if __name__ == "__main__":
    main()

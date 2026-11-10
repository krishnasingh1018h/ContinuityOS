from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from backend.app import database
from backend.app.main import app


def test_health_check_reports_api_and_database_status() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_frontend_and_assets_are_served() -> None:
    client = TestClient(app)

    page = client.get("/")
    script = client.get("/assets/app.js")
    stylesheet = client.get("/assets/styles.css")

    assert page.status_code == 200
    assert 'id="auth-screen"' in page.text
    assert script.status_code == 200
    assert "async function start()" in script.text
    assert stylesheet.status_code == 200
    assert "--green:" in stylesheet.text


def test_health_check_hides_database_error_details(monkeypatch) -> None:
    def fail_health_check() -> None:
        raise SQLAlchemyError("private connection detail")

    monkeypatch.setattr(database, "check_database", fail_health_check)
    response = TestClient(app).get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "database_unavailable"}}
    assert "private connection detail" not in response.text

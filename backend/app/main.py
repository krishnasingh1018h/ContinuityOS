import logging
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from backend.app import database
from backend.app.routes import router as api_router

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]


app = FastAPI(title="ContinuityOS", version="0.1.0")
app.include_router(api_router, prefix="/api")
app.mount(
    "/assets",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="assets",
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    return response


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    try:
        database.check_database()
    except SQLAlchemyError as error:
        logger.error("Database health check failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail={"code": "database_unavailable"},
        ) from error

    return HealthResponse(status="ok", database="ok")

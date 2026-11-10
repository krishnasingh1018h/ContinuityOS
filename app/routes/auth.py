from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.schemas import UserInput
from app.security import SESSION_SECONDS, create_session_token, get_current_user, hash_password, verify_password

router = APIRouter(tags=["auth"])


@router.post("/auth/signup", status_code=201)
def signup(body: UserInput, response: Response, db: Session = Depends(get_db)) -> dict:
    email = body.email.lower()
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "account_already_exists"}) from None
    db.refresh(user)
    set_session_cookie(response, user.id)
    return {"id": str(user.id), "email": user.email}


@router.post("/auth/login")
def login(body: UserInput, response: Response, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials"})
    set_session_cookie(response, user.id)
    return {"id": str(user.id), "email": user.email}


@router.post("/auth/logout", status_code=204)
def logout(response: Response) -> Response:
    response.delete_cookie(
        "continuityos_session",
        path="/",
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="lax",
    )
    response.status_code = 204
    return response


@router.get("/auth/me")
def current_user(user: User = Depends(get_current_user)) -> dict:
    return {"id": str(user.id), "email": user.email}


def set_session_cookie(response: Response, user_id) -> None:
    settings = get_settings()
    response.set_cookie(
        "continuityos_session",
        create_session_token(user_id),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=SESSION_SECONDS,
        path="/",
    )

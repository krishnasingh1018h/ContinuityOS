import base64
import hashlib
import hmac
import json
import os
import time
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import ProjectMembership, ProjectRole, User

SESSION_SECONDS = 12 * 60 * 60
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    if len(password) < 10 or len(password) > 256:
        raise ValueError("Password must contain 10 to 256 characters.")
    salt = os.urandom(16)
    derived_key = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + _encode_bytes(salt) + "$" + _encode_bytes(derived_key)


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, encoded_salt, encoded_key = stored_hash.split("$", maxsplit=2)
        if scheme != "scrypt":
            return False
        salt = _decode_bytes(encoded_salt)
        expected = _decode_bytes(encoded_key)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def create_session_token(user_id: UUID) -> str:
    header = _encode_segment({"alg": "HS256", "typ": "JWT"})
    payload = _encode_segment({"sub": str(user_id), "exp": int(time.time()) + SESSION_SECONDS})
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(get_settings().secret_key.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_encode_bytes(signature)}"


def _encode_segment(value: dict) -> str:
    return _encode_bytes(json.dumps(value, separators=(",", ":"), sort_keys=True).encode())


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def decode_session_token(token: str) -> UUID:
    try:
        header, payload, signature = token.split(".")
        signing_input = f"{header}.{payload}".encode()
        expected = hmac.new(get_settings().secret_key.encode(), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))):
            raise ValueError("Invalid signature")
        token_header = json.loads(_decode_bytes(header))
        metadata = json.loads(_decode_bytes(payload))
        if token_header.get("alg") != "HS256" or metadata.get("exp", 0) <= time.time():
            raise ValueError("Expired session")
        return UUID(metadata["sub"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail={"code": "invalid_session"}) from None


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials if credentials else request.cookies.get("continuityos_session")
    if not token:
        raise HTTPException(status_code=401, detail={"code": "authentication_required"})
    user_id = decode_session_token(token)
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status_code=401, detail={"code": "invalid_session"})
    return user


def get_project_membership(
    project_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectMembership:
    membership = db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail={"code": "project_not_found"})
    return membership


def require_roles(*roles: ProjectRole):
    def role_dependency(
        membership: ProjectMembership = Depends(get_project_membership),
    ) -> ProjectMembership:
        if membership.role not in roles:
            raise HTTPException(status_code=403, detail={"code": "insufficient_project_role"})
        return membership

    return role_dependency


def visible_sensitivities(role: ProjectRole) -> tuple[str, ...]:
    if role in (ProjectRole.OWNER, ProjectRole.REVIEWER):
        return ("project", "restricted")
    return ("project",)

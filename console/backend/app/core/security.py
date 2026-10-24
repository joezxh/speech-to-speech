from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import auth as auth_settings
from app.core.errors import ApiError

_bearer = HTTPBearer(auto_error=False)


def create_token(subject: str, role: str, kind: str) -> str:
    now = datetime.now(UTC)
    delta = (
        timedelta(minutes=auth_settings.jwt_access_token_expire_minutes)
        if kind == "access"
        else timedelta(days=auth_settings.jwt_refresh_token_expire_days)
    )
    payload = {"sub": subject, "role": role, "typ": kind, "iat": int(now.timestamp()), "exp": now + delta}
    return jwt.encode(payload, auth_settings.jwt_secret_key, algorithm=auth_settings.jwt_algorithm)


def decode_token(token: str, *, kind: str) -> dict:
    try:
        payload = jwt.decode(token, auth_settings.jwt_secret_key, algorithms=[auth_settings.jwt_algorithm])
    except JWTError as exc:
        raise ApiError("unauthorized", "token is invalid or expired", 401) from exc
    if payload.get("typ") != kind:
        # A refresh token must never open an API: same signature, different job.
        raise ApiError("unauthorized", "wrong token type", 401)
    return payload


@dataclass(frozen=True)
class CurrentUser:
    username: str
    role: str


def require_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise ApiError("unauthorized", "missing bearer token", 401)
    payload = decode_token(credentials.credentials, kind="access")
    return CurrentUser(username=str(payload.get("sub", "")), role=str(payload.get("role", "operator")))


def require_admin(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    if user.role != "admin":
        raise ApiError("forbidden", "admin role required", 403)
    return user


def require_operator(user: CurrentUser = Depends(require_user)) -> CurrentUser:
    if user.role not in ("admin", "operator"):
        raise ApiError("forbidden", "operator role required", 403)
    return user

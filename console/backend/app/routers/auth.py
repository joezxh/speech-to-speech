from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.config import auth as auth_settings
from app.core.errors import ApiError
from app.core.security import CurrentUser, create_token, decode_token, require_user
from app.deps import DbSession
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RefreshRequest
from app.schemas.common import ok
from app.services.auth_service import throttle, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _token_bundle(username: str, role: str) -> dict:
    return {
        "accessToken": create_token(username, role, "access"),
        "tokenType": "bearer",
        "expiresIn": auth_settings.jwt_access_token_expire_minutes * 60,
        "refreshToken": create_token(username, role, "refresh"),
        "user": {"username": username, "role": role},
    }


@router.post("/login")
def login(payload: LoginRequest, request: Request, db: DbSession):
    ip = _client_ip(request)
    if throttle.blocked(ip):
        raise ApiError("too_many_attempts", "too many failed logins; retry later", 429)
    user = UserRepository(db).by_username(payload.username)
    # Same rejection for "no such user" and "wrong password": the error must
    # not become a username oracle.
    if user is None or user.disabled or not verify_password(payload.password, user.password_hash):
        throttle.fail(ip)
        raise ApiError("invalid_credentials", "username or password is incorrect", 401)
    throttle.reset(ip)
    UserRepository(db).touch_login(user)
    return ok(_token_bundle(user.username, user.role))


@router.post("/refresh")
def refresh(payload: RefreshRequest):
    claims = decode_token(payload.refreshToken, kind="refresh")
    return ok(_token_bundle(str(claims.get("sub", "")), str(claims.get("role", "operator"))))


@router.get("/me")
def me(user: CurrentUser = Depends(require_user), db: DbSession = None):
    row = UserRepository(db).by_username(user.username)
    if row is None:
        raise ApiError("unauthorized", "unknown account", 401)
    return ok(
        {
            "username": row.username,
            "role": row.role,
            "lastLoginAt": row.last_login_at.isoformat().replace("+00:00", "Z") if row.last_login_at else None,
        }
    )

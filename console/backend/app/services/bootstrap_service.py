"""First-boot administrator.

The console has no registration page (spec §3.8): on an empty volume there is
nobody who can sign in, and every API below `/api/v1` answers 401. The
`DEFAULT_ADMIN_*` pair closes that gap once. `scripts/seed_admin.py` stays the
way to add further accounts, and the way to create the first one on a
deployment that leaves the pair unset.
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from app.config import bootstrap as bootstrap_settings
from app.repositories.user_repository import UserRepository
from app.services.auth_service import hash_password

# `seed_admin.py` refuses shorter passwords; the two paths must agree.
MIN_PASSWORD_LENGTH = 8
ROLES = frozenset({"admin", "operator"})


def ensure_default_admin(session: Session) -> str | None:
    """Create the configured account if its username is still free.

    Returns the username that was created, or None when the bootstrap is off,
    misconfigured, or the account already exists. An existing row is never
    touched: a restart must not undo a password somebody chose.
    """
    username = bootstrap_settings.default_admin_username.strip()
    password = bootstrap_settings.default_admin_password
    role = bootstrap_settings.default_admin_role.strip() or "admin"

    if not username or not password:
        return None
    if len(password) < MIN_PASSWORD_LENGTH:
        logger.warning(
            "default admin bootstrap skipped: DEFAULT_ADMIN_PASSWORD is shorter than {} characters",
            MIN_PASSWORD_LENGTH,
        )
        return None
    if role not in ROLES:
        logger.warning("default admin bootstrap skipped: unknown DEFAULT_ADMIN_ROLE {!r}", role)
        return None

    repo = UserRepository(session)
    if repo.by_username(username) is not None:
        return None

    repo.create(username, hash_password(password), role)
    logger.warning(
        "created the default {} account '{}' from DEFAULT_ADMIN_*; change that password before exposing the console",
        role,
        username,
    )
    return username

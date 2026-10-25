from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BootstrapSettings(BaseSettings):
    """The first-boot administrator (see `services/bootstrap_service.py`).

    The empty password is the default on purpose. An image that ships a working
    account is an image whose password is in the repository, so production
    starts with the bootstrap off and creates the first admin with
    `scripts/seed_admin.py`. Development fills the pair in from `.env.example`.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    default_admin_username: str = "admin"
    default_admin_password: str = ""
    default_admin_role: str = "admin"

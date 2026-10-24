from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_STARTUP_GREETING = (
    "Start the conversation now with a brief, spontaneous greeting in character. "
    "Keep it to one sentence, invite the user in naturally, and vary the wording each time."
)


class DemoSettings(BaseSettings):
    """The demo face's switches (A.13). Every one defaults to "feature off"."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    serper_api_key: str = ""
    load_balancer_url: str = ""
    speech_to_speech_url: str = ""
    space_id: str = ""
    oauth_client_id: str = ""
    rtc_ice_servers: str = ""
    startup_greeting: str = DEFAULT_STARTUP_GREETING
    # Service credential for the HF ingress in front of the LB. Never leaves the
    # server: `/api/me` and `/api/session` use it, `/api/config` never mentions it.
    lb_hf_token: str = ""

    @property
    def pinned_url(self) -> str:
        return self.speech_to_speech_url.strip()

    @property
    def lb_url(self) -> str:
        """A pinned direct URL disables the whole LB face (demo/server.py:80)."""
        return "" if self.pinned_url else self.load_balancer_url.strip()

    @property
    def limiter_enabled(self) -> bool:
        """Budget and queue exist only on a Space behind an LB (demo/server.py:88)."""
        return bool(self.lb_url) and bool(self.space_id.strip())

    @property
    def oauth_configured(self) -> bool:
        return bool(self.oauth_client_id.strip())

    @property
    def auth_enabled(self) -> bool:
        """Sign-in only matters when we are metering (demo/server.py:205)."""
        return self.limiter_enabled and self.oauth_configured

    @property
    def server_search(self) -> bool:
        """A public Space only spends the paid key for signed-in users."""
        return bool(self.serper_api_key.strip()) and (self.auth_enabled or not self.space_id.strip())

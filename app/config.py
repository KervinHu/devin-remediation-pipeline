"""Central configuration loaded from environment / .env.

All settings are read once at import time into a frozen ``Settings`` instance
exposed as ``settings``. The Devin API key is normalized to carry the required
``cog_`` prefix so callers never have to worry about how it was stored.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env sitting next to the project root (one level up from app/).
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required env var '{name}'. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def _normalize_devin_key(raw: str) -> str:
    """Devin API keys must be sent as `cog_<key>`; tolerate either form."""
    raw = raw.strip()
    return raw if raw.startswith("cog_") else f"cog_{raw}"


@dataclass(frozen=True)
class Settings:
    # Devin
    org_id: str
    devin_api_key: str
    devin_base_url: str = "https://api.devin.ai/v3"
    max_acu_limit: int = 10

    # GitHub
    github_token: str = ""
    github_repo: str = ""  # "owner/name"
    github_api_url: str = "https://api.github.com"

    # Automation
    trigger_label: str = "devin-fix"
    webhook_secret: str = ""
    poll_interval_seconds: int = 20
    reconcile_interval_seconds: int = 30

    # Storage
    db_path: str = field(
        default_factory=lambda: os.getenv(
            "dbPath",
            str(Path(__file__).resolve().parent.parent / "data" / "pipeline.sqlite"),
        )
    )

    @property
    def sessions_url(self) -> str:
        return f"{self.devin_base_url}/organizations/{self.org_id}/sessions"

    def session_url(self, session_id: str) -> str:
        return f"{self.sessions_url}/{session_id}"


def _load() -> Settings:
    return Settings(
        org_id=_require("orgId"),
        devin_api_key=_normalize_devin_key(_require("cogKey")),
        max_acu_limit=int(os.getenv("maxAcuLimit", "10")),
        github_token=os.getenv("githubToken", "").strip(),
        github_repo=os.getenv("githubRepo", "").strip(),
        trigger_label=os.getenv("triggerLabel", "devin-fix").strip(),
        webhook_secret=os.getenv("webhookSecret", "").strip(),
        poll_interval_seconds=int(os.getenv("pollIntervalSeconds", "20")),
        reconcile_interval_seconds=int(os.getenv("reconcileIntervalSeconds", "30")),
    )


settings = _load()

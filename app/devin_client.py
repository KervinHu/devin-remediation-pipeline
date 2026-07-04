"""Thin async wrapper around the Devin v3 (org-scoped) REST API.

Endpoints used:
  POST   /v3/organizations/{org}/sessions            -> create a session
  GET    /v3/organizations/{org}/sessions/{id}       -> session detail
  POST   /v3/organizations/{org}/sessions/{id}/messages -> follow-up message

Auth: ``Authorization: Bearer cog_<key>`` (config normalizes the prefix).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx

from .config import settings

# Devin session statuses we treat as terminal (no more polling needed).
TERMINAL_STATUSES = {"finished", "expired", "cancelled", "failed"}
# Statuses that mean "still doing work / waiting".
ACTIVE_STATUSES = {"running", "working", "suspended", "blocked", "resuming"}


@dataclass
class SessionView:
    """Normalized snapshot of a Devin session for the rest of the app."""

    session_id: str
    url: str
    status: str
    status_detail: Optional[str]
    acus_consumed: float
    pr_url: Optional[str]
    pr_state: Optional[str]
    structured_output: Optional[dict[str, Any]]
    raw: dict[str, Any]

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "SessionView":
        prs = data.get("pull_requests") or []
        first_pr = prs[0] if prs else {}
        return cls(
            session_id=data.get("session_id", ""),
            url=data.get("url", ""),
            status=(data.get("status") or "unknown").lower(),
            status_detail=data.get("status_detail"),
            acus_consumed=float(data.get("acus_consumed") or 0.0),
            pr_url=first_pr.get("pr_url"),
            pr_state=first_pr.get("pr_state"),
            structured_output=data.get("structured_output"),
            raw=data,
        )


class DevinClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self._headers = {
            "Authorization": f"Bearer {settings.devin_api_key}",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    async def create_session(
        self,
        prompt: str,
        *,
        title: Optional[str] = None,
        idempotent: bool = True,
        max_acu_limit: Optional[int] = None,
        tags: Optional[list[str]] = None,
    ) -> SessionView:
        payload: dict[str, Any] = {
            "prompt": prompt,
            "idempotent": idempotent,
            "max_acu_limit": max_acu_limit or settings.max_acu_limit,
        }
        if title:
            payload["title"] = title
        if tags:
            payload["tags"] = tags

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                settings.sessions_url, headers=self._headers, json=payload
            )
            resp.raise_for_status()
            return SessionView.from_api(resp.json())

    async def get_session(self, session_id: str) -> SessionView:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                settings.session_url(session_id), headers=self._headers
            )
            resp.raise_for_status()
            return SessionView.from_api(resp.json())

    async def send_message(self, session_id: str, message: str) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{settings.session_url(session_id)}/messages",
                headers=self._headers,
                json={"message": message},
            )
            resp.raise_for_status()

    async def get_org_usage_metrics(self) -> dict[str, Any]:
        """Devin org-level usage counters: sessions / searches / PRs.

        This is Devin's own accounting (includes sessions created outside this
        pipeline, e.g. from the web app), so it's a useful cross-check for the
        "is this working" question independent of our local DB.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{settings.org_base_url}/metrics/usage", headers=self._headers
            )
            resp.raise_for_status()
            return resp.json()

    async def get_org_total_acus(self) -> float:
        """Total ACUs for the org's current billing cycle.

        Consumption is aggregated per day with a PST midnight boundary, so the
        current day's spend may not appear until the cycle rolls over. Real-time
        per-session cost is visible in the Devin "Usage & Limits" UI.
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{settings.org_base_url}/consumption/daily", headers=self._headers
            )
            resp.raise_for_status()
            return float(resp.json().get("total_acus") or 0.0)


devin = DevinClient()

"""Async GitHub REST helpers scoped to the configured repo.

Used to: read issues, list label-filtered issues (reconcile safety net),
and post progress comments back onto issues.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx

from .config import settings


@dataclass
class Issue:
    number: int
    title: str
    body: str
    labels: list[str]
    state: str
    html_url: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Issue":
        return cls(
            number=data["number"],
            title=data.get("title", ""),
            body=data.get("body") or "",
            labels=[lbl["name"] for lbl in data.get("labels", [])],
            state=data.get("state", ""),
            html_url=data.get("html_url", ""),
        )


class GitHubClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self._repo = settings.github_repo
        self._base = f"{settings.github_api_url}/repos/{self._repo}"
        self._headers = {
            "Authorization": f"Bearer {settings.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._timeout = timeout

    async def get_issue(self, number: int) -> Issue:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/issues/{number}", headers=self._headers
            )
            resp.raise_for_status()
            return Issue.from_api(resp.json())

    async def list_labeled_issues(self, label: Optional[str] = None) -> list[Issue]:
        label = label or settings.trigger_label
        params = {"labels": label, "state": "open", "per_page": 100}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/issues", headers=self._headers, params=params
            )
            resp.raise_for_status()
            # /issues can include PRs; filter them out.
            return [
                Issue.from_api(item)
                for item in resp.json()
                if "pull_request" not in item
            ]

    async def comment(self, number: int, body: str) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/issues/{number}/comments",
                headers=self._headers,
                json={"body": body},
            )
            resp.raise_for_status()


github = GitHubClient()

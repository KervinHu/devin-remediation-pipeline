"""Turns an inbound issue event into a managed Devin session.

Idempotent by issue number: if we already created a session for an issue, we do
not create another one (webhook + reconcile can both fire for the same issue).
"""
from __future__ import annotations

import logging

from . import db
from .devin_client import devin
from .github_client import Issue, github
from .prompts import build_prompt, classify

log = logging.getLogger("orchestrator")


async def handle_issue(issue: Issue, *, source: str = "webhook") -> str:
    """Create (or reuse) a Devin session for an issue. Returns a status string."""
    existing = db.get(issue.number)
    if existing and existing.get("session_id"):
        log.info("issue #%s already has session %s; skipping (source=%s)",
                 issue.number, existing["session_id"], source)
        return "already_handled"

    issue_type = classify(issue)
    prompt = build_prompt(issue, issue_type)

    session = await devin.create_session(
        prompt=prompt,
        title=f"Fix superset issue #{issue.number}: {issue.title}"[:120],
        idempotent=True,
        tags=["superset-pipeline", f"issue-{issue.number}", issue_type],
    )
    db.create(
        issue_number=issue.number,
        issue_title=issue.title,
        issue_type=issue_type,
        session_id=session.session_id,
        session_url=session.url,
    )
    log.info("created Devin session %s for issue #%s (type=%s, source=%s)",
             session.session_id, issue.number, issue_type, source)

    try:
        await github.comment(
            issue.number,
            f"🤖 **Devin is on it.** Started an autonomous remediation session "
            f"(`{issue_type}`).\n\nTrack it here: {session.url}",
        )
    except Exception as exc:  # commenting must never break the pipeline
        log.warning("failed to comment on issue #%s: %s", issue.number, exc)

    return "created"

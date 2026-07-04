"""Background reconciliation + status polling.

Two independent loops:
  * poll_active_once  -> advances known sessions, writes state, comments PR/results
  * reconcile_once    -> the safety net: picks up labeled issues that the webhook
                          may have missed and hands them to the orchestrator

This is the "webhook as primary, polling as reconciliation" pattern that makes
the event-driven design production-safe (webhooks can be dropped).
"""
from __future__ import annotations

import asyncio
import logging

from . import db
from .config import settings
from .devin_client import SessionView, devin
from .github_client import github
from .orchestrator import handle_issue

log = logging.getLogger("poller")


def _derive_status(view: SessionView) -> str:
    if view.is_terminal:
        return db.STATUS_FINISHED if view.pr_url else db.STATUS_FAILED
    if view.pr_url:
        return db.STATUS_PR_OPEN
    if view.status in {"running", "working", "resuming"}:
        return db.STATUS_RUNNING
    return db.STATUS_QUEUED


def _extract_summary(view: SessionView) -> str | None:
    out = view.structured_output or {}
    if isinstance(out, dict):
        return out.get("summary")
    return None


async def poll_active_once() -> None:
    for row in db.list_non_terminal():
        session_id = row.get("session_id")
        if not session_id:
            continue
        try:
            view = await devin.get_session(session_id)
        except Exception as exc:
            log.warning("poll failed for session %s (issue #%s): %s",
                        session_id, row["issue_number"], exc)
            continue

        new_status = _derive_status(view)
        prev_status = row["status"]
        had_pr = bool(row.get("pr_url"))

        db.update_from_session(
            row["issue_number"],
            status=new_status,
            devin_status=view.status,
            devin_status_detail=view.status_detail,
            acus_consumed=view.acus_consumed,
            pr_url=view.pr_url,
            pr_state=view.pr_state,
            summary=_extract_summary(view),
        )

        # Comment on meaningful transitions only (avoid spam).
        try:
            if view.pr_url and not had_pr:
                await github.comment(
                    row["issue_number"],
                    f"✅ **Devin opened a pull request:** {view.pr_url}\n\n"
                    f"Session: {view.url}",
                )
            elif new_status == db.STATUS_FINISHED and prev_status != db.STATUS_FINISHED:
                summary = _extract_summary(view) or "Remediation complete."
                await github.comment(
                    row["issue_number"],
                    f"🎉 **Remediation finished.** {summary}\n\n"
                    f"PR: {view.pr_url}\nACUs consumed: {view.acus_consumed}",
                )
            elif new_status == db.STATUS_FAILED and prev_status != db.STATUS_FAILED:
                await github.comment(
                    row["issue_number"],
                    f"⚠️ **Devin session ended without a PR** "
                    f"(status: {view.status} / {view.status_detail}).\n\n"
                    f"Session: {view.url}",
                )
        except Exception as exc:
            log.warning("comment on transition failed for issue #%s: %s",
                        row["issue_number"], exc)


async def reconcile_once() -> None:
    try:
        issues = await github.list_labeled_issues()
    except Exception as exc:
        log.warning("reconcile: failed to list labeled issues: %s", exc)
        return
    for issue in issues:
        if db.get(issue.number) is None:
            log.info("reconcile: backfilling missed issue #%s", issue.number)
            try:
                await handle_issue(issue, source="reconcile")
            except Exception as exc:
                log.warning("reconcile: handle_issue #%s failed: %s",
                            issue.number, exc)


async def _loop(coro_fn, interval: int, name: str) -> None:
    log.info("starting %s loop (every %ss)", name, interval)
    while True:
        try:
            await coro_fn()
        except Exception as exc:  # never let a loop die
            log.exception("%s loop iteration error: %s", name, exc)
        await asyncio.sleep(interval)


def start_background_loops() -> list[asyncio.Task]:
    return [
        asyncio.create_task(
            _loop(poll_active_once, settings.poll_interval_seconds, "poll")
        ),
        asyncio.create_task(
            _loop(reconcile_once, settings.reconcile_interval_seconds, "reconcile")
        ),
    ]

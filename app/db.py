"""SQLite persistence for remediation records.

One row per issue we've picked up. Kept intentionally small; the whole point is
that an engineering leader can query "what did the pipeline do and how well".
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from .config import settings

# Pipeline-level status (derived from Devin session state).
STATUS_QUEUED = "queued"      # session created, no PR yet
STATUS_RUNNING = "running"    # Devin actively working
STATUS_PR_OPEN = "pr_open"    # Devin opened a PR (still may be iterating)
STATUS_FINISHED = "finished"  # terminal + PR exists -> success
STATUS_FAILED = "failed"      # terminal + no PR -> failure

_SCHEMA = """
CREATE TABLE IF NOT EXISTS remediations (
    issue_number      INTEGER PRIMARY KEY,
    issue_title       TEXT,
    issue_type        TEXT,
    session_id        TEXT,
    session_url       TEXT,
    status            TEXT,
    devin_status      TEXT,
    devin_status_detail TEXT,
    pr_url            TEXT,
    pr_state          TEXT,
    acus_consumed     REAL DEFAULT 0,
    summary           TEXT,
    created_at        INTEGER,
    updated_at        INTEGER,
    pr_opened_at      INTEGER,
    time_to_pr_seconds INTEGER
);
"""


def _now() -> int:
    return int(time.time())


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


def get(issue_number: int) -> Optional[dict[str, Any]]:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM remediations WHERE issue_number = ?", (issue_number,)
        ).fetchone()
        return dict(row) if row else None


def list_all() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM remediations ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def list_non_terminal() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM remediations WHERE status NOT IN (?, ?)",
            (STATUS_FINISHED, STATUS_FAILED),
        ).fetchall()
        return [dict(r) for r in rows]


def create(
    issue_number: int,
    issue_title: str,
    issue_type: str,
    session_id: str,
    session_url: str,
) -> None:
    now = _now()
    with _conn() as c:
        c.execute(
            """
            INSERT INTO remediations
                (issue_number, issue_title, issue_type, session_id, session_url,
                 status, devin_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(issue_number) DO NOTHING
            """,
            (
                issue_number, issue_title, issue_type, session_id, session_url,
                STATUS_QUEUED, "created", now, now,
            ),
        )


def update_from_session(
    issue_number: int,
    *,
    status: str,
    devin_status: str,
    devin_status_detail: Optional[str],
    acus_consumed: float,
    pr_url: Optional[str],
    pr_state: Optional[str],
    summary: Optional[str],
) -> None:
    now = _now()
    with _conn() as c:
        existing = c.execute(
            "SELECT created_at, pr_opened_at FROM remediations WHERE issue_number = ?",
            (issue_number,),
        ).fetchone()
        if existing is None:
            return
        pr_opened_at = existing["pr_opened_at"]
        time_to_pr = None
        if pr_url and pr_opened_at is None:
            pr_opened_at = now
        if pr_opened_at is not None and existing["created_at"] is not None:
            time_to_pr = pr_opened_at - existing["created_at"]

        c.execute(
            """
            UPDATE remediations SET
                status = ?, devin_status = ?, devin_status_detail = ?,
                acus_consumed = ?, pr_url = ?, pr_state = ?, summary = COALESCE(?, summary),
                updated_at = ?, pr_opened_at = ?, time_to_pr_seconds = ?
            WHERE issue_number = ?
            """,
            (
                status, devin_status, devin_status_detail, acus_consumed,
                pr_url, pr_state, summary, now, pr_opened_at, time_to_pr,
                issue_number,
            ),
        )

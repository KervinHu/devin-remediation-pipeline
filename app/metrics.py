"""Aggregate remediation records into leadership-friendly KPIs."""
from __future__ import annotations

from typing import Any

from . import db


def _avg(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def compute_stats() -> dict[str, Any]:
    rows = db.list_all()
    total = len(rows)
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    finished = by_status.get(db.STATUS_FINISHED, 0)
    failed = by_status.get(db.STATUS_FAILED, 0)
    active = total - finished - failed
    terminal = finished + failed
    success_rate = round(100 * finished / terminal, 1) if terminal else None

    prs_opened = sum(1 for r in rows if r.get("pr_url"))
    total_acus = round(sum(float(r.get("acus_consumed") or 0) for r in rows), 2)
    ttp_values = [
        int(r["time_to_pr_seconds"])
        for r in rows
        if r.get("time_to_pr_seconds") is not None
    ]

    return {
        "total": total,
        "active": active,
        "finished": finished,
        "failed": failed,
        "prs_opened": prs_opened,
        "success_rate": success_rate,          # % of terminal that produced a PR
        "total_acus": total_acus,
        "avg_time_to_pr_seconds": _avg(ttp_values),
        "by_status": by_status,
        "rows": rows,
    }

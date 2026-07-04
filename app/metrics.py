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

    # "Resolved" = Devin produced a PR and finished its part (finished or awaiting review).
    resolved = sum(by_status.get(s, 0) for s in db.RESOLVED_STATUSES)
    failed = by_status.get(db.STATUS_FAILED, 0)
    active = total - resolved - failed
    decided = resolved + failed
    # success rate = of the issues Devin has finished with, how many produced a PR.
    success_rate = round(100 * resolved / decided, 1) if decided else None

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
        "resolved": resolved,
        "failed": failed,
        "prs_opened": prs_opened,
        "success_rate": success_rate,          # % of decided that produced a PR
        "total_acus": total_acus,
        "avg_time_to_pr_seconds": _avg(ttp_values),
        "by_status": by_status,
        "rows": rows,
    }

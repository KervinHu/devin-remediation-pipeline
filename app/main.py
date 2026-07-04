"""FastAPI entrypoint: GitHub webhook (primary trigger) + observability.

Routes:
  POST /webhook/github   -> HMAC-verified GitHub `issues` events (primary trigger)
  POST /simulate/{n}     -> manually trigger remediation for an issue (debug)
  GET  /stats            -> KPI JSON
  GET  /dashboard        -> HTML observability dashboard
  GET  /healthz          -> liveness
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import db, metrics
from .config import settings
from .devin_client import devin
from .github_client import Issue, github
from .orchestrator import handle_issue
from .poller import start_background_loops

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("main")

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Cache Devin org metrics so the auto-refreshing dashboard (every 15s) doesn't
# hit the Devin API on every page load. Serves stale data if a fetch fails.
_USAGE_TTL_SECONDS = 60.0
_usage_cache: dict[str, Any] = {"at": 0.0, "data": None}


async def _get_org_usage() -> Optional[dict[str, Any]]:
    now = time.time()
    cached = _usage_cache["data"]
    if cached is not None and now - _usage_cache["at"] < _USAGE_TTL_SECONDS:
        return cached
    try:
        data = await devin.get_org_usage_metrics()
        data["total_acus"] = await devin.get_org_total_acus()
    except Exception as exc:  # keep the dashboard alive on API hiccups
        log.warning("org usage metrics fetch failed: %s", exc)
        return cached  # stale (or None if never fetched)
    _usage_cache.update(at=now, data=data)
    return data


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    tasks = start_background_loops()
    log.info("pipeline up: repo=%s label=%s", settings.github_repo, settings.trigger_label)
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


app = FastAPI(title="Devin Superset Remediation Pipeline", lifespan=lifespan)


def _verify_signature(body: bytes, signature: str | None) -> bool:
    """Validate GitHub's X-Hub-Signature-256 (sha256=<hex>)."""
    if not settings.webhook_secret:
        return True  # no secret configured -> skip (dev only)
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature.split("=", 1)[1])


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
):
    body = await request.body()
    if not _verify_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="invalid signature")

    payload = await request.json()

    if x_github_event != "issues":
        return {"ignored": f"event={x_github_event}"}

    action = payload.get("action")
    issue_data = payload.get("issue", {})
    labels = [lbl["name"] for lbl in issue_data.get("labels", [])]

    # Trigger on: the trigger label being added, or present on open/edit.
    label_added = payload.get("label", {}).get("name")
    triggered = (
        action == "labeled" and label_added == settings.trigger_label
    ) or (
        action in {"opened", "edited", "reopened"}
        and settings.trigger_label in labels
    )
    if not triggered:
        return {"ignored": f"action={action}, labels={labels}"}

    issue = Issue.from_api(issue_data)
    result = await handle_issue(issue, source="webhook")
    return {"issue": issue.number, "result": result}


@app.post("/simulate/{issue_number}")
async def simulate(issue_number: int):
    """Debug helper: pull an issue and run it through the pipeline directly."""
    issue = await github.get_issue(issue_number)
    result = await handle_issue(issue, source="simulate")
    return {"issue": issue_number, "result": result}


@app.get("/stats")
async def stats():
    data = metrics.compute_stats()
    data["devin_org"] = await _get_org_usage()
    return JSONResponse(data)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = metrics.compute_stats()
    return _TEMPLATES.TemplateResponse(
        "dashboard.html",
        {"request": request, "s": stats, "repo": settings.github_repo},
    )

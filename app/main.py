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
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import db, metrics
from .config import settings
from .github_client import Issue, github
from .orchestrator import handle_issue
from .poller import start_background_loops

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("main")

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


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
    return JSONResponse(metrics.compute_stats())


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = metrics.compute_stats()
    return _TEMPLATES.TemplateResponse(
        "dashboard.html",
        {"request": request, "s": stats, "repo": settings.github_repo},
    )

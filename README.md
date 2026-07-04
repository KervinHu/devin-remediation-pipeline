# Devin Superset Remediation Pipeline

An **event-driven automation** that turns GitHub issues into merged-ready pull
requests using the [Devin API](https://docs.devin.ai/api-reference/overview).

> Label an issue `devin-fix` → a GitHub webhook fires → the pipeline spins up an
> autonomous Devin session → Devin navigates the repo, makes the change, runs
> lint/tests, and opens a PR → progress is streamed back onto the issue and a
> live dashboard shows throughput, success rate, and cost (ACUs).

Built for the Apache Superset fork [`KervinHu/superset`](https://github.com/KervinHu/superset).

---

## Why this matters

Dependency bumps, lint debt, and small bug/doc fixes are a constant tax on
engineering teams: individually trivial, collectively expensive, and easy to
deprioritize. This pipeline makes **Devin the core primitive** for that class of
work — the "understand → change → validate → open PR" loop is fully autonomous.
The system around it only does two things: **orchestration** and
**observability**.

## Architecture

```
   ┌──────────────┐   issues.labeled (devin-fix)     ┌────────────────────────┐
   │   GitHub      │ ───────────────────────────────► │  POST /webhook/github  │
   │  (fork repo)  │   HMAC-SHA256 signed webhook      │  (HMAC verified)       │
   └──────────────┘                                    └───────────┬────────────┘
          ▲  ▲                                                     │
          │  │  progress comments                                 ▼
          │  │                                            ┌──────────────────┐
          │  └────────────────────────────────────────── │   Orchestrator   │
          │                                               │  classify → prompt│
          │                                               │  create session   │
          │                    ┌────────────┐  poll        └────────┬─────────┘
          │                    │  Devin API │ ◄──────────────────────┤
          │                    │ (v3, org)  │                        │ persist
          │                    └─────┬──────┘                        ▼
          │   comment PR / result    │ status, pr_url, acus   ┌────────────┐
          └──────────────────────────┴────────────────────── │  SQLite    │
                                                              └─────┬──────┘
   Reconcile loop (safety net): scans labeled issues, backfills any │
   the webhook missed  ──────────────────────────────────────────► │
                                                                    ▼
                                                   GET /dashboard  &  /stats
                                          (KPIs: active / done / failed /
                                           success rate / ACUs / time-to-PR)
```

**Webhook is the primary trigger; the reconcile loop is a safety net** — webhook
deliveries can be dropped, so a background loop periodically reconciles labeled
issues against what we've already processed. This is what makes the event-driven
design production-safe.

## Project layout

```
app/
  main.py          FastAPI: /webhook/github, /simulate/{n}, /dashboard, /stats, /healthz
  config.py        env loading (+ normalizes the Devin key's cog_ prefix)
  devin_client.py  Devin v3 API wrapper (create / get / message)
  github_client.py GitHub wrapper (read issue, list labeled, comment)
  orchestrator.py  issue event -> prompt -> Devin session -> DB (idempotent)
  poller.py        poll active sessions + reconcile missed issues
  prompts.py       per-issue-type structured prompt templates
  db.py            SQLite persistence
  metrics.py       KPI aggregation
  templates/dashboard.html
scripts/
  create_issues.py     seed the fork with 3 remediable issues
  register_webhook.sh  point the GitHub webhook at your tunnel URL
  demo.sh              one-shot demo driver
```

## Configuration

Copy `.env.example` to `.env` and fill it in:

| Var | Description |
|---|---|
| `orgId` | Devin organization id |
| `cogKey` | Devin service-user key (stored with or without `cog_` prefix) |
| `githubToken` | GitHub token with `repo` scope (locally: `gh auth token`) |
| `githubRepo` | `owner/name` of the fork, e.g. `KervinHu/superset` |
| `triggerLabel` | label that triggers remediation (default `devin-fix`) |
| `webhookSecret` | shared secret for webhook HMAC (`openssl rand -hex 24`) |
| `maxAcuLimit` | per-session ACU cost cap (default 10) |
| `pollIntervalSeconds` / `reconcileIntervalSeconds` | loop cadences |

## Run

### With Docker (recommended)

```bash
docker compose up --build          # app on http://localhost:8000
```

Open the dashboard at <http://localhost:8000/dashboard>.

### Locally

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn app.main:app --reload
```

## Wire up the webhook (public tunnel)

GitHub's servers must reach your local service, so expose it with a tunnel:

```bash
# 1. start a public tunnel to localhost:8000
cloudflared tunnel --url http://localhost:8000
#    -> prints https://<random>.trycloudflare.com

# 2. register the webhook on the fork (uses gh + the secret in .env)
./scripts/register_webhook.sh https://<random>.trycloudflare.com
```

> Alternatively, `docker compose --profile tunnel up` runs cloudflared as a
> sidecar; read its logs for the URL, then run `register_webhook.sh`.

## Demo the workflow

```bash
# seed the fork with 3 issues (each pre-labeled to trigger the pipeline)
./scripts/demo.sh          # == python scripts/create_issues.py
```

Then watch <http://localhost:8000/dashboard>. Each issue moves
`queued → running → pr_open → finished`, comments appear on the GitHub issue,
and Devin opens a PR against the fork.

No public tunnel handy? Trigger a specific issue directly:

```bash
curl -X POST http://localhost:8000/simulate/<issue_number>
```

## Observability — "how would a leader know this is working?"

- **`/dashboard`** — live (auto-refresh) KPI cards + per-issue table with links
  to each Devin session and the resulting PR.
- **`/stats`** — the same metrics as JSON for scraping/alerting:
  total, active, finished, failed, **success rate**, **PRs opened**,
  **total ACUs consumed**, **average time-to-PR**.
- **Structured logs** — every state transition (session created, PR opened,
  finished/failed) is logged and mirrored as a GitHub issue comment.

## Extending in a real engagement

- Trigger from a security scanner (Snyk/Dependabot/CodeQL) instead of a manual label.
- Devin **playbooks** to encode repo-specific conventions and raise success rate.
- Fan out across many repos; add per-team ACU budgets and SLOs to the dashboard.
- Gate auto-merge on CI green + required reviewers.

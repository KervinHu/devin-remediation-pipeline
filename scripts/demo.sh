#!/usr/bin/env bash
# One-shot local demo driver for the Loom recording.
#
# It assumes the app is already running (docker compose up, or uvicorn) and a
# tunnel + webhook are configured. It seeds issues, then tails the dashboard URL.
#
# Steps performed:
#   1. seed the fork with issues (each labeled to trigger the pipeline)
#   2. print the dashboard URL to watch
#
# The webhook fires automatically when GitHub records the new labeled issues;
# the reconcile loop is the safety net if a webhook delivery is missed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
PY="${PYTHON:-$ROOT/.venv/bin/python}"

echo "==> Seeding issues into the fork"
"$PY" "$SCRIPT_DIR/create_issues.py"

echo
echo "==> Watch the pipeline live:"
echo "    Dashboard: http://localhost:8000/dashboard"
echo "    Stats API: http://localhost:8000/stats"
echo
echo "Devin sessions will appear as 'queued' -> 'running' -> 'pr_open' -> 'finished'."

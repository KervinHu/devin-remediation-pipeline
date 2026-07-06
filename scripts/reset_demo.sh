#!/usr/bin/env bash
# Reset a single issue back to a pristine, pre-trigger state so you can safely
# re-record the live demo after a botched take.
#
# It undoes everything a trigger touches, IN THE RIGHT ORDER:
#   1. remove the trigger label   (first, so the reconcile loop won't re-pick it)
#   2. delete the pipeline's bot comments on the issue
#   3. close the PR + delete its branch (auto-detected, or pass one explicitly)
#   4. delete the SQLite row  -> dashboard reverts AND idempotency won't skip the
#      next trigger (without this, re-labeling is a no-op and no new session shows)
#
# The Devin session itself keeps running (ACUs already spent) but no longer
# appears on the dashboard once its row is gone.
#
# Usage:  ./scripts/reset_demo.sh <issue_number> [pr_number]
set -euo pipefail

ISSUE="${1:-}"
PR="${2:-}"
if [[ -z "$ISSUE" ]]; then
  echo "usage: $0 <issue_number> [pr_number]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR/.."
source "$ROOT/.env"
LABEL="${triggerLabel:-devin-fix}"

echo "Resetting issue #$ISSUE in $githubRepo ..."

# 1. remove the trigger label (ignore if not present)
if gh issue edit "$ISSUE" --repo "$githubRepo" --remove-label "$LABEL" >/dev/null 2>&1; then
  echo "  [1/4] removed label '$LABEL'"
else
  echo "  [1/4] label '$LABEL' not present (skipped)"
fi

# 2. delete the pipeline's own bot comments (matched by their known markers)
marker='Devin is on it|Devin opened a pull request|Remediation complete|Remediation finished|Devin session ended'
ids=$(gh api "repos/$githubRepo/issues/$ISSUE/comments" \
        --jq ".[] | select(.body | test(\"$marker\")) | .id" 2>/dev/null || true)
if [[ -n "$ids" ]]; then
  for id in $ids; do
    gh api -X DELETE "repos/$githubRepo/issues/comments/$id" >/dev/null && echo "  [2/4] deleted bot comment $id"
  done
else
  echo "  [2/4] no bot comments to delete"
fi

# 3. close the PR + delete its branch. Auto-detect by "Fixes #ISSUE" in the body
#    if a PR number wasn't passed explicitly.
if [[ -z "$PR" ]]; then
  PR=$(gh pr list --repo "$githubRepo" --state open --json number,body \
         --jq ".[] | select(.body | test(\"[Ff]ixes #$ISSUE\\\\b\")) | .number" 2>/dev/null | head -1 || true)
fi
if [[ -n "$PR" ]]; then
  gh pr close "$PR" --repo "$githubRepo" --delete-branch >/dev/null 2>&1 \
    && echo "  [3/4] closed PR #$PR and deleted its branch" \
    || echo "  [3/4] could not close PR #$PR (already closed?)"
else
  echo "  [3/4] no open PR found for issue #$ISSUE"
fi

# 4. delete the SQLite row via the running app container (path-agnostic)
if docker compose -f "$ROOT/docker-compose.yml" exec -T app python -c "
import sqlite3
from app.config import settings
con = sqlite3.connect(settings.db_path)
n = con.execute('DELETE FROM remediations WHERE issue_number = ?', ($ISSUE,)).rowcount
con.commit(); con.close()
print('  [4/4] deleted', n, 'DB row(s)')
" 2>/dev/null; then :; else
  echo "  [4/4] WARNING: could not delete DB row (is the app container up?)"
fi

echo "Done. Issue #$ISSUE is pristine — re-label '$LABEL' to trigger a fresh take."

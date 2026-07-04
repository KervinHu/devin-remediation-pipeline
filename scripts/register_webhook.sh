#!/usr/bin/env bash
# Register (or update) the GitHub `issues` webhook on the fork so it points at
# your public tunnel URL. Uses the already-authenticated `gh` CLI + the shared
# secret from .env.
#
# Usage:  ./scripts/register_webhook.sh https://<something>.trycloudflare.com
set -euo pipefail

PUBLIC_URL="${1:-}"
if [[ -z "$PUBLIC_URL" ]]; then
  echo "usage: $0 <public-base-url>   (e.g. https://foo.trycloudflare.com)" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../.env"

HOOK_URL="${PUBLIC_URL%/}/webhook/github"
echo "Repo:       $githubRepo"
echo "Webhook URL: $HOOK_URL"

# Remove any existing hooks pointing at /webhook/github to avoid duplicates.
existing=$(gh api "repos/$githubRepo/hooks" --jq \
  '.[] | select(.config.url | endswith("/webhook/github")) | .id' 2>/dev/null || true)
for id in $existing; do
  echo "Deleting existing hook $id"
  gh api -X DELETE "repos/$githubRepo/hooks/$id" >/dev/null
done

gh api -X POST "repos/$githubRepo/hooks" \
  -f name=web \
  -F active=true \
  -f 'events[]=issues' \
  -f config[url]="$HOOK_URL" \
  -f config[content_type]=json \
  -f config[secret]="$webhookSecret" \
  --jq '"Created webhook id=\(.id) events=\(.events)"'

echo "Done. Label an issue '$triggerLabel' to trigger the pipeline."

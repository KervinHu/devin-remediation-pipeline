#!/usr/bin/env python3
"""Seed the fork with a handful of concrete, self-contained issues to remediate.

Each issue gets the trigger label plus a type label so the pipeline classifies it.
Idempotent-ish: it will happily create duplicates if run twice, so run once.

Usage:
    python scripts/create_issues.py            # create the default seed issues
    python scripts/create_issues.py --dry-run  # print what would be created
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402

TRIGGER = settings.trigger_label

# label name -> color (GitHub hex, no #)
LABELS = {
    TRIGGER: "5319e7",
    "dependency": "0e8a16",
    "code-quality": "1d76db",
    "documentation": "d4c5f9",
}

SEED_ISSUES = [
    {
        "title": "Add missing module docstring to a utility module",
        "labels": [TRIGGER, "documentation"],
        "body": (
            "Several small utility modules are missing a top-level module "
            "docstring, which our documentation-quality gate flags.\n\n"
            "**Task:** Pick one small utility module under `superset/utils/` that "
            "lacks a module-level docstring and add a concise, accurate one "
            "describing the module's purpose. Do not change any runtime behavior."
        ),
    },
    {
        "title": "Fix lint / type-annotation issues in a small module",
        "labels": [TRIGGER, "code-quality"],
        "body": (
            "Our linter reports missing type annotations / minor style issues in "
            "some helper modules.\n\n"
            "**Task:** Pick one small module under `superset/utils/` with missing "
            "function type hints and add correct type annotations so it passes the "
            "repo's pre-commit / ruff checks. Keep the change minimal and do not "
            "refactor unrelated code."
        ),
    },
    {
        "title": "Upgrade a pinned dev dependency to a patched version",
        "labels": [TRIGGER, "dependency"],
        "body": (
            "We want to keep dependencies current for security and stability.\n\n"
            "**Task:** Identify one safely-upgradable pinned dependency in the "
            "`requirements/` files (a patch or minor bump with no breaking "
            "changes), bump it, and confirm the project still installs. Keep the "
            "change scoped to that single dependency."
        ),
    },
]


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def ensure_labels(client: httpx.Client, base: str) -> None:
    for name, color in LABELS.items():
        r = client.post(
            f"{base}/labels", headers=_headers(),
            json={"name": name, "color": color},
        )
        if r.status_code in (200, 201):
            print(f"  label created: {name}")
        elif r.status_code == 422:
            print(f"  label exists:  {name}")
        else:
            print(f"  label {name}: HTTP {r.status_code} {r.text[:120]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--no-trigger",
        action="store_true",
        help="create issues WITHOUT the trigger label (add it later to fire the webhook)",
    )
    args = ap.parse_args()

    repo = settings.github_repo
    base = f"{settings.github_api_url}/repos/{repo}"
    print(f"Seeding issues into {repo} (trigger label: {TRIGGER})")

    if args.dry_run:
        for i in SEED_ISSUES:
            print(f"  [dry-run] {i['title']}  labels={i['labels']}")
        return

    with httpx.Client(timeout=30) as client:
        ensure_labels(client, base)
        for issue in SEED_ISSUES:
            labels = issue["labels"]
            if args.no_trigger:
                labels = [lbl for lbl in labels if lbl != TRIGGER]
            r = client.post(
                f"{base}/issues", headers=_headers(),
                json={
                    "title": issue["title"],
                    "body": issue["body"],
                    "labels": labels,
                },
            )
            r.raise_for_status()
            data = r.json()
            print(f"  created #{data['number']}: {data['title']} -> {data['html_url']}")


if __name__ == "__main__":
    main()

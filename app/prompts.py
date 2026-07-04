"""Prompt templates that turn a GitHub issue into a Devin task.

The prompt is where Devin becomes the *core primitive*: we hand it the issue and
a set of guardrails, and it autonomously navigates the repo, makes the change,
validates it, and opens a PR. Issue *type* (from a secondary label) selects a
type-specific hint block; everything else is shared.
"""
from __future__ import annotations

from .config import settings
from .github_client import Issue

# Map a secondary GitHub label -> internal issue type.
LABEL_TO_TYPE = {
    "dependency": "dependency_upgrade",
    "dependencies": "dependency_upgrade",
    "code-quality": "code_quality",
    "lint": "code_quality",
    "bug": "bugfix",
    "bugfix": "bugfix",
    "documentation": "docs",
    "docs": "docs",
}

_TYPE_HINTS = {
    "dependency_upgrade": (
        "This is a DEPENDENCY UPGRADE. Locate the pinned dependency in the "
        "requirements files, bump it to the target version, and verify nothing "
        "obvious breaks. Keep the change limited to the dependency and any "
        "directly required adjustments."
    ),
    "code_quality": (
        "This is a CODE QUALITY task. Make the minimal change that satisfies the "
        "linter / type checker for the referenced file(s). Do not refactor "
        "unrelated code. Run the repo's lint (e.g. pre-commit / ruff / flake8) to "
        "confirm the fix."
    ),
    "bugfix": (
        "This is a BUG FIX. Reproduce the described behavior, make the smallest "
        "correct change, and add or update a test if it is cheap to do so."
    ),
    "docs": (
        "This is a DOCUMENTATION task. Add the missing docstring(s) / docs exactly "
        "as described. Do not change runtime behavior."
    ),
    "generic": (
        "Make the minimal, correct change described in the issue."
    ),
}


def classify(issue: Issue) -> str:
    for label in issue.labels:
        t = LABEL_TO_TYPE.get(label.lower())
        if t:
            return t
    return "generic"


def build_prompt(issue: Issue, issue_type: str) -> str:
    hint = _TYPE_HINTS.get(issue_type, _TYPE_HINTS["generic"])
    repo = settings.github_repo
    return f"""\
You are an autonomous software engineer working on the GitHub repository `{repo}`.

# Task
Remediate issue #{issue.number}: "{issue.title}"

## Issue description
{issue.body or "(no description provided)"}

## Type-specific guidance
{hint}

# Guardrails
- Work on the `{repo}` repository.
- Follow the repository's CONTRIBUTING guidelines and existing code style.
- Keep the change as MINIMAL as possible; do not touch unrelated files.
- Run the relevant lint / tests to validate your change before finishing.
- Open a Pull Request against `{repo}` that fixes this issue. In the PR
  description, include the line `Fixes #{issue.number}` so it links the issue.

# Required structured output
When done, return `structured_output` as JSON with keys:
  - "pr_url":  the URL of the PR you opened (string, or null if you could not open one)
  - "summary": one-sentence summary of what you changed
  - "status":  "success" or "blocked"
  - "notes":   any caveats or follow-ups (string)
"""

# ABOUTME: INNER connector for estate-map status — reads one repo's open issues and PRs through the gh CLI.
# ABOUTME: Every failure to read (gh error, bad JSON, a full page, no GitHub URL) raises CouldNotLook.

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Mapping
from typing import Any

from oversteward.intake.github import OPEN_LIMIT, GhError, gh_json

from .checkouts import CouldNotLook
from .status import Fetch, Item

#: Open PRs are a handful per repo; a full page is refused, never trusted.
PR_LIMIT = 200
_ISSUE_FIELDS = "number,title,body,labels"
_PR_FIELDS = "number,title,body,labels,files"
_GITHUB_URL = re.compile(r"github\.com[/:](?P<name>[^/\s]+/[^/\s]+?)(?:\.git)?/?$")

Runner = Callable[[list[str]], Any]


def full_name(registry: Mapping[str, Any], repo: str) -> str:
    """`owner/name` from the registry context's `repo` URL."""
    for ctx in registry.get("contexts") or []:
        if ctx.get("id") == repo:
            match = _GITHUB_URL.search(str(ctx.get("repo") or ""))
            if match:
                return match.group("name")
            raise CouldNotLook(f"{repo}: registry.yaml gives no GitHub repo URL")
    raise CouldNotLook(f"{repo}: not a registry.yaml context")


def _read(repo: str, run: Runner, args: list[str], limit: int) -> list[dict]:
    try:
        rows = run([*args, "--state", "open", "--limit", str(limit)])
    except (GhError, json.JSONDecodeError) as exc:
        raise CouldNotLook(f"{repo}: {exc}") from exc
    if len(rows) >= limit:
        raise CouldNotLook(f"{repo}: open {args[0]}s filled the page of {limit} — the read is incomplete")
    return rows


def open_items(repo: str, name: str, *, run: Runner = gh_json) -> list[Item]:
    issues = _read(repo, run, ["issue", "list", "--repo", name, "--json", _ISSUE_FIELDS], OPEN_LIMIT)
    prs = _read(repo, run, ["pr", "list", "--repo", name, "--json", _PR_FIELDS], PR_LIMIT)
    return [_item(repo, "issue", row) for row in issues] + [_item(repo, "pr", row) for row in prs]


def _item(repo: str, kind: str, row: Mapping[str, Any]) -> Item:
    return Item(
        repo=repo,
        kind=kind,
        number=int(row["number"]),
        title=row.get("title") or "",
        body=row.get("body") or "",
        files=tuple(f["path"] for f in row.get("files") or ()),
    )


def fetcher(registry: Mapping[str, Any], *, run_process: Callable[..., Any] = subprocess.run) -> Fetch:
    """A Fetch reading each repo the registry names, through `gh` run by `run_process`."""

    def run(args: list[str]) -> Any:
        return gh_json(args, run=run_process)

    return lambda repo: open_items(repo, full_name(registry, repo), run=run)

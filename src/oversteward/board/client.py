# ABOUTME: INNER transport for the Estate Board — reads one repository's issues through gh.
# ABOUTME: Refuses a page that fills its limit; a truncated estate must never read as a small one.

"""Read a repository's issues the way the board needs them.

Three ``gh`` calls per repository: every open issue, the label list (to learn
which ``epic:<slug>`` labels exist), and every *closed* issue carrying any of
those labels — one OR-search, so GS's 900 closed issues are never paged. Then
one read per issue an *open epic's body* names that none of those pages held —
a closed child without the label is exactly the child that turns "no children"
into "every child is closed". A number that is a pull request or does not
exist is not a child; any other failure is the repository being unreadable.

Each page is checked against its limit. ``gh`` truncates silently, and an
estate read at exactly the limit is a smaller estate than exists — that is a
:class:`TruncatedReadError`, never a report.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from oversteward.board.config import RepoRef
from oversteward.board.models import EPIC_LABEL_PREFIX, Issue

OPEN_LIMIT = 500
LABEL_LIMIT = 200
CLOSED_LIMIT = 1000

_FIELDS = "number,title,url,state,labels,createdAt,updatedAt,closedAt,body"

Runner = Callable[[list[str]], Any]

#: Parallel by-number reads per repository.
_BY_NUMBER_WORKERS = 8


class GhError(RuntimeError):
    """``gh`` itself failed — the repository could not be read."""


class TruncatedReadError(GhError):
    """A page came back full; the repository holds more than was read."""


class NotFoundError(GhError):
    """GitHub answered 404: the thing asked for does not exist."""


def gh_json(args: list[str]) -> Any:
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8", check=False
    )
    if proc.returncode != 0:
        message = f"gh {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}"
        if "HTTP 404" in proc.stderr:
            raise NotFoundError(message)
        raise GhError(message)
    out = proc.stdout.strip()
    return json.loads(out) if out else []


def _page(run: Runner, args: list[str], limit: int, what: str, repo: RepoRef) -> list:
    rows = run([*args, "--limit", str(limit)])
    if len(rows) >= limit:
        raise TruncatedReadError(
            f"{repo.name}: {what} filled its page of {limit} — the read is incomplete"
        )
    return rows


def read_repo(repo: RepoRef, *, run: Runner = gh_json) -> tuple[Issue, ...]:
    """Every open issue plus every closed issue carrying an ``epic:`` label."""
    base = ["--repo", repo.full_name]
    open_rows = _page(
        run,
        ["issue", "list", *base, "--state", "open", "--json", _FIELDS],
        OPEN_LIMIT,
        "open issues",
        repo,
    )
    labels = _page(run, ["label", "list", *base, "--json", "name"], LABEL_LIMIT, "labels", repo)
    epic_labels = sorted(row["name"] for row in labels if row["name"].startswith(EPIC_LABEL_PREFIX))
    closed_rows: list = []
    if epic_labels:
        # GitHub's search syntax reads a comma-joined label list as OR.
        search = "label:" + ",".join(f'"{label}"' for label in epic_labels)
        closed_rows = _page(
            run,
            ["issue", "list", *base, "--state", "closed", "--search", search, "--json", _FIELDS],
            CLOSED_LIMIT,
            "closed epic issues",
            repo,
        )
    rows = [*open_rows, *closed_rows]
    rows.extend(_read_missing_children(run, repo, rows))
    return tuple(Issue.from_gh(repo.id, row) for row in rows)


def _from_rest(payload: dict) -> dict:
    """Reshape a REST issue payload to the ``gh issue list --json`` shape."""
    return {
        "number": payload["number"],
        "title": payload.get("title", ""),
        "url": payload.get("html_url", ""),
        "state": payload.get("state", "open"),
        "labels": [{"name": label["name"]} for label in payload.get("labels", ())],
        "createdAt": payload.get("created_at"),
        "updatedAt": payload.get("updated_at"),
        "closedAt": payload.get("closed_at"),
        "body": payload.get("body") or "",
    }


def _read_one(run: Runner, repo: RepoRef, number: int) -> dict | None:
    try:
        payload = run(["api", f"repos/{repo.full_name}/issues/{number}"])
    except NotFoundError:
        return None
    if "pull_request" in payload:
        return None
    return _from_rest(payload)


def _read_missing_children(run: Runner, repo: RepoRef, rows: list[dict]) -> list[dict]:
    """Issues named in an open epic's body that no page above returned."""
    have = {int(row["number"]) for row in rows}
    wanted: set[int] = set()
    for row in rows:
        issue = Issue.from_gh(repo.id, row)
        if issue.is_epic and issue.is_open:
            wanted.update(n for n in issue.body_refs if n not in have)
    if not wanted:
        return []
    with ThreadPoolExecutor(max_workers=min(_BY_NUMBER_WORKERS, len(wanted))) as pool:
        found = pool.map(lambda n: _read_one(run, repo, n), sorted(wanted))
    return [row for row in found if row is not None]


def read_estate(
    repos: Sequence[RepoRef], *, reader: Callable[[RepoRef], tuple[Issue, ...]] = read_repo
) -> dict[str, tuple[Issue, ...]]:
    """Every repository's issues, keyed by registry id, in the order given.

    Reads run in parallel; any failure propagates, because a board missing a
    repository is a smaller estate than exists.
    """
    with ThreadPoolExecutor(max_workers=max(1, len(repos))) as pool:
        results = list(pool.map(reader, repos))
    return {repo.id: issues for repo, issues in zip(repos, results, strict=True)}


__all__ = [
    "CLOSED_LIMIT",
    "LABEL_LIMIT",
    "OPEN_LIMIT",
    "GhError",
    "NotFoundError",
    "TruncatedReadError",
    "gh_json",
    "read_estate",
    "read_repo",
]

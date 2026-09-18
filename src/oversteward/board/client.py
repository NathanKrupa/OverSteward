# ABOUTME: INNER transport for the Estate Board — reads one repository's issues through gh.
# ABOUTME: Refuses a page that fills its limit; a truncated estate must never read as a small one.

"""Read a repository's issues the way the board needs them.

Three ``gh`` calls per repository: every open issue, the label list (to learn
which ``epic:<slug>`` labels exist), and every *closed* issue carrying any of
those labels — one OR-search, so GS's 900 closed issues are never paged. Closed
issues without an epic label are history the board does not show.

Each page is checked against its limit. ``gh`` truncates silently, and an
estate read at exactly the limit is a smaller estate than exists — that is a
:class:`TruncatedReadError`, never a report.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

from oversteward.board.config import RepoRef
from oversteward.board.models import EPIC_LABEL_PREFIX, Issue

OPEN_LIMIT = 500
LABEL_LIMIT = 200
CLOSED_LIMIT = 1000

_FIELDS = "number,title,url,state,labels,createdAt,updatedAt,closedAt,body"

Runner = Callable[[list[str]], list]


class GhError(RuntimeError):
    """``gh`` itself failed — the repository could not be read."""


class TruncatedReadError(GhError):
    """A page came back full; the repository holds more than was read."""


def gh_json(args: list[str]) -> list:
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8", check=False
    )
    if proc.returncode != 0:
        raise GhError(f"gh {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}")
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
    return tuple(Issue.from_gh(repo.id, row) for row in [*open_rows, *closed_rows])


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
    "TruncatedReadError",
    "gh_json",
    "read_estate",
    "read_repo",
]

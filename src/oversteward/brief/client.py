# ABOUTME: INNER transport for the Estate Brief — one repository's merged PRs and needs-input issues.
# ABOUTME: Reads through the board's gh runner; a page that fills its limit is refused, never shortened.

"""Read what one repository shipped and what it is waiting on.

Two ``gh`` calls per repository: pull requests GitHub reports merged since the
day before the window opens (the search qualifier is date-granular, so the
service trims to the exact instant), and every open issue labelled
``needs-input``. Pull-request rows are returned as GitHub reported them, and
the service decides which count as shipped. For asks the query itself is the
only filter — open and labelled ``needs-input`` — and nothing downstream
re-checks it, so the argv is pinned by test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from oversteward.board.client import Runner, _page, gh_json
from oversteward.board.config import RepoRef
from oversteward.board.models import NEEDS_INPUT, Issue

MERGED_LIMIT = 300
ASK_LIMIT = 300

_PR_FIELDS = "number,title,url,state,mergedAt"
_ASK_FIELDS = "number,title,url,state,labels,createdAt,updatedAt"


@dataclass(frozen=True, slots=True)
class PullRequest:
    """One pull request as ``gh pr list --json`` reports it."""

    repo: str
    number: int
    title: str
    url: str
    state: str
    merged_at: datetime | None

    @classmethod
    def from_gh(cls, repo: str, raw: dict) -> PullRequest:
        merged = raw.get("mergedAt")
        return cls(
            repo=repo,
            number=int(raw["number"]),
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            state=str(raw.get("state", "")).upper(),
            merged_at=datetime.fromisoformat(merged) if merged else None,
        )


@dataclass(frozen=True, slots=True)
class RepoActivity:
    """What one repository reported: candidate merges and open asks."""

    repo: str
    pulls: tuple[PullRequest, ...]
    asks: tuple[Issue, ...]


def read_activity(repo: RepoRef, since: datetime, *, run: Runner = gh_json) -> RepoActivity:
    """Pull requests merged on or after the day before ``since``, and open needs-input issues."""
    base = ["--repo", repo.full_name]
    search_from = (since - timedelta(days=1)).date().isoformat()
    pr_rows = _page(
        run,
        ["pr", "list", *base, "--state", "merged", "--search", f"merged:>={search_from}",
         "--json", _PR_FIELDS],
        MERGED_LIMIT,
        "merged pull requests",
        repo,
    )
    ask_rows = _page(
        run,
        ["issue", "list", *base, "--state", "open", "--label", NEEDS_INPUT,
         "--json", _ASK_FIELDS],
        ASK_LIMIT,
        "needs-input issues",
        repo,
    )
    return RepoActivity(
        repo=repo.id,
        pulls=tuple(PullRequest.from_gh(repo.id, row) for row in pr_rows),
        asks=tuple(Issue.from_gh(repo.id, row) for row in ask_rows),
    )


__all__ = ["ASK_LIMIT", "MERGED_LIMIT", "PullRequest", "RepoActivity", "read_activity"]

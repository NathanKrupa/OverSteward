# ABOUTME: INNER transport for the Estate Brief — merged PRs, needs-input issues, an ask's thread, issue state.
# ABOUTME: Reads through the board's gh runner; a page that fills its limit is refused, never shortened.

"""Read what one repository shipped and what it is waiting on.

Two ``gh`` calls per repository: pull requests GitHub reports merged since the
day before the window opens (the search qualifier is date-granular, so the
service trims to the exact instant), and every open issue labelled
``needs-input``. Pull-request rows are returned as GitHub reported them, and
the service decides which count as shipped. For asks the query itself is the
only filter — open and labelled ``needs-input`` — and nothing downstream
re-checks it, so the argv is pinned by test.

For the one ask, one more read: that issue's body and its newest 100 comment
bodies (GraphQL ``last: 100`` — ``gh``'s own ``--json comments`` reads the
oldest 100, the wrong end for "the latest question"). For a crashed service
with a recorded issue, one REST read of that issue's state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from oversteward.board.client import NotFoundError, Runner, _page, gh_json
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


_THREAD = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) { body comments(last: 100) { nodes { body } } }
  }
}
"""


@dataclass(frozen=True, slots=True)
class AskThread:
    """An ask's body and its newest comment bodies, oldest first."""

    body: str
    comments: tuple[str, ...]


def read_thread(repo: RepoRef, number: int, *, run: Runner = gh_json) -> AskThread:
    """The issue's body and newest comments."""
    owner, name = repo.full_name.split("/", 1)
    data = run(["api", "graphql", "-f", f"query={_THREAD}", "-f", f"owner={owner}",
                "-f", f"name={name}", "-F", f"number={number}"])
    issue = data["data"]["repository"]["issue"] or {}
    nodes = (issue.get("comments") or {}).get("nodes") or []
    return AskThread(body=issue.get("body") or "", comments=tuple(n.get("body") or "" for n in nodes))


def issue_is_open(repo: RepoRef, number: int, *, run: Runner = gh_json) -> bool:
    """Whether ``number`` is an open issue. A pull request or a missing number is not."""
    try:
        payload = run(["api", f"repos/{repo.full_name}/issues/{number}"])
    except NotFoundError:
        return False
    return "pull_request" not in payload and payload.get("state") == "open"


__all__ = [
    "ASK_LIMIT",
    "MERGED_LIMIT",
    "AskThread",
    "PullRequest",
    "RepoActivity",
    "issue_is_open",
    "read_activity",
    "read_thread",
]

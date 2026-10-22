# ABOUTME: INNER transport for the abandoned-work sweep — reads one repository and writes its shelvings.
# ABOUTME: Reads and writes go through the board's gh runner; a page past its cap is refused, never shortened.

"""Read what the sweep judges, and perform what it decides.

Reads, per repository: every open pull request with its newest commit, review
and comments; every *closed* pull request and issue labelled ``shelved`` with
its newest comments; every open issue; every branch with its last commit and
whether any pull request was ever opened from it; the label list. Plus, on
demand, one issue's state and newest comments (a stale branch's linked issue).

GraphQL is used where ``gh pr list --json`` reads the wrong end of a list:
``gh`` asks for the *first* 100 comments, so on a long thread the newest
comment — the one idleness and reopening turn on — would be missing. Here
every comment list is the *last* 100, with its total count, so the caller can
tell a complete thread from a cut one.

Writes are REST calls through the same runner, ordered so a failure part-way
leaves an item the next run handles, never one it loses track of: the
``shelved`` label goes on *before* an item closes (a closed item without it is
invisible to the reopen rule), and an item reopens *before* the label comes off.
This module never deletes a branch and never creates a label; posting a label
that does not exist would create it, so the service checks first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from oversteward.board.client import (
    LABEL_LIMIT,
    OPEN_LIMIT,
    GhError,
    NotFoundError,
    Runner,
    TruncatedReadError,
    _page,
    gh_json,
)
from oversteward.board.config import RepoRef
from oversteward.board.models import Issue
from oversteward.intake.labels import AGENT_FINDING, SHELVED

#: GraphQL pages read per connection before the read is refused as incomplete.
MAX_PAGES = 40

_ISSUE_FIELDS = "number,title,url,state,labels,createdAt,updatedAt"

_PULLS = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title url createdAt headRefName
        author { login }
        commits(last: 1) { nodes { commit { committedDate } } }
        reviews(last: 1) { nodes { submittedAt } }
        comments(last: 100) { totalCount nodes { body createdAt } }
      }
    }
  }
}
"""

_SHELVED = """
query($owner: String!, $name: String!, $label: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    %s(states: CLOSED, labels: [$label], first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes { number title url closedAt comments(last: 100) { totalCount nodes { body createdAt } } }
    }
  }
}
"""

_BRANCHES = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { name }
    refs(refPrefix: "refs/heads/", first: 100, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        target { ... on Commit { committedDate } }
        associatedPullRequests(first: 1) { totalCount }
      }
    }
  }
}
"""

_ISSUE_COMMENTS = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) { comments(last: 100) { totalCount nodes { body } } }
  }
}
"""


def _when(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass(frozen=True, slots=True)
class Comment:
    body: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Thread:
    """An item's newest comments, oldest first, and whether they are all of them."""

    comments: tuple[Comment, ...]
    complete: bool

    @classmethod
    def from_gh(cls, raw: dict) -> Thread:
        nodes = raw.get("nodes") or []
        comments = tuple(Comment(n.get("body") or "", _when(n["createdAt"])) for n in nodes)
        return cls(comments=comments, complete=int(raw.get("totalCount", 0)) <= len(nodes))


@dataclass(frozen=True, slots=True)
class OpenPull:
    """An open pull request and the three kinds of motion idleness counts."""

    repo: str
    number: int
    title: str
    url: str
    branch: str
    created_at: datetime
    last_commit_at: datetime | None
    last_review_at: datetime | None
    thread: Thread
    #: The author's GraphQL login (``dependabot`` for Dependabot); ``None`` for a deleted account.
    author: str | None = None

    @classmethod
    def from_gh(cls, repo: str, raw: dict) -> OpenPull:
        commits = raw["commits"]["nodes"]
        reviews = raw["reviews"]["nodes"]
        return cls(
            repo=repo,
            number=int(raw["number"]),
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            branch=raw.get("headRefName", ""),
            created_at=_when(raw["createdAt"]),
            last_commit_at=_when(commits[-1]["commit"]["committedDate"]) if commits else None,
            last_review_at=_when(reviews[-1].get("submittedAt")) if reviews else None,
            thread=Thread.from_gh(raw["comments"]),
            author=(raw.get("author") or {}).get("login"),
        )


@dataclass(frozen=True, slots=True)
class ShelvedItem:
    """A closed pull request or issue that carries the ``shelved`` label."""

    repo: str
    kind: str  # "pr" or "issue"
    number: int
    title: str
    url: str
    closed_at: datetime
    thread: Thread

    @classmethod
    def from_gh(cls, repo: str, kind: str, raw: dict) -> ShelvedItem:
        return cls(
            repo=repo,
            kind=kind,
            number=int(raw["number"]),
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            closed_at=_when(raw["closedAt"]),
            thread=Thread.from_gh(raw["comments"]),
        )


@dataclass(frozen=True, slots=True)
class Branch:
    repo: str
    name: str
    last_commit_at: datetime | None
    #: Whether any pull request, in any state, was ever opened from this branch.
    has_pull: bool


@dataclass(frozen=True, slots=True)
class LinkedIssue:
    """The issue a branch name points at: open or not, and its newest comment bodies."""

    number: int
    open: bool
    comment_bodies: tuple[str, ...]
    #: Whether ``comment_bodies`` is the whole thread, not its newest 100.
    complete: bool = True


@dataclass(frozen=True, slots=True)
class RepoSnapshot:
    """Everything the sweep judges in one repository, read in one pass."""

    repo: RepoRef
    default_branch: str
    labels: frozenset[str]
    pulls: tuple[OpenPull, ...]
    shelved: tuple[ShelvedItem, ...]
    issues: tuple[Issue, ...]
    branches: tuple[Branch, ...]


def _graphql(run: Runner, query: str, repo: RepoRef, **variables: str) -> dict:
    owner, name = repo.full_name.split("/", 1)
    args = ["api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}"]
    for key, value in variables.items():
        args += ["-F" if key == "number" else "-f", f"{key}={value}"]
    data = run(args)
    if data.get("errors"):
        raise GhError(f"{repo.full_name}: GraphQL errors {data['errors']}")
    return data["data"]["repository"]


def _connection(
    run: Runner, query: str, repo: RepoRef, key: str, what: str, **variables: str
) -> tuple[list[dict], dict]:
    """Every node of ``repository.<key>``, paging until GitHub says there is no more."""
    nodes: list[dict] = []
    first: dict | None = None
    cursor: dict[str, str] = {}
    for _ in range(MAX_PAGES):
        page = _graphql(run, query, repo, **variables, **cursor)
        first = first if first is not None else page
        connection = page[key]
        nodes.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            return nodes, first
        cursor = {"cursor": connection["pageInfo"]["endCursor"]}
    raise TruncatedReadError(f"{repo.name}: {what} ran past {MAX_PAGES} pages")


def _read_branches(run: Runner, repo: RepoRef) -> tuple[str, tuple[Branch, ...]]:
    nodes, first = _connection(run, _BRANCHES, repo, "refs", "branches")
    default = (first.get("defaultBranchRef") or {}).get("name", "")
    branches = tuple(
        Branch(
            repo=repo.id,
            name=node["name"],
            last_commit_at=_when((node.get("target") or {}).get("committedDate")),
            has_pull=int(node["associatedPullRequests"]["totalCount"]) > 0,
        )
        for node in nodes
    )
    return default, branches


def _read_shelved(run: Runner, repo: RepoRef) -> tuple[ShelvedItem, ...]:
    items: list[ShelvedItem] = []
    for kind, key in (("pr", "pullRequests"), ("issue", "issues")):
        nodes, _ = _connection(
            run, _SHELVED % key, repo, key, f"shelved {key}", label=SHELVED
        )
        items.extend(ShelvedItem.from_gh(repo.id, kind, node) for node in nodes)
    return tuple(items)


def read_snapshot(repo: RepoRef, *, run: Runner = gh_json) -> RepoSnapshot:
    """One repository, read for the sweep. Any failure propagates."""
    base = ["--repo", repo.full_name]
    labels = _page(run, ["label", "list", *base, "--json", "name"], LABEL_LIMIT, "labels", repo)
    pulls, _ = _connection(run, _PULLS, repo, "pullRequests", "open pull requests")
    issues = _page(
        run,
        ["issue", "list", *base, "--state", "open", "--json", _ISSUE_FIELDS],
        OPEN_LIMIT,
        "open issues",
        repo,
    )
    default, branches = _read_branches(run, repo)
    return RepoSnapshot(
        repo=repo,
        default_branch=default,
        labels=frozenset(row["name"] for row in labels),
        pulls=tuple(OpenPull.from_gh(repo.id, row) for row in pulls),
        shelved=_read_shelved(run, repo),
        issues=tuple(Issue.from_gh(repo.id, row) for row in issues),
        branches=branches,
    )


def read_linked_issue(repo: RepoRef, number: int, *, run: Runner = gh_json) -> LinkedIssue | None:
    """The issue ``number`` names, or ``None`` when it is a pull request or does not exist."""
    try:
        payload = run(["api", f"repos/{repo.full_name}/issues/{number}"])
    except NotFoundError:
        return None
    if "pull_request" in payload:
        return None
    found = _graphql(run, _ISSUE_COMMENTS, repo, number=str(number))
    thread = (found.get("issue") or {}).get("comments") or {}
    nodes = thread.get("nodes") or []
    return LinkedIssue(
        number=number,
        open=payload.get("state") == "open",
        comment_bodies=tuple(node.get("body") or "" for node in nodes),
        complete=int(thread.get("totalCount", 0)) <= len(nodes),
    )


class GhWriter:
    """The sweep's only write path. Each method is one decided action, in a safe order."""

    def __init__(self, run: Runner = gh_json) -> None:
        self._run = run

    def _api(self, method: str, path: str, *fields: str) -> None:
        args = ["api", "-X", method, path]
        for field in fields:
            args += ["-f", field]
        self._run(args)

    def _label(self, repo: RepoRef, number: int) -> None:
        self._api("POST", f"repos/{repo.full_name}/issues/{number}/labels", f"labels[]={SHELVED}")

    def _comment(self, repo: RepoRef, number: int, body: str) -> None:
        self._api("POST", f"repos/{repo.full_name}/issues/{number}/comments", f"body={body}")

    def shelve_pull(self, repo: RepoRef, number: int, comment: str) -> None:
        """Label, explain, close. The branch is not touched."""
        self._label(repo, number)
        self._comment(repo, number, comment)
        self._api("PATCH", f"repos/{repo.full_name}/pulls/{number}", "state=closed")

    def close_finding(self, repo: RepoRef, number: int, comment: str) -> None:
        """Label, explain, close as not planned."""
        self._label(repo, number)
        self._comment(repo, number, comment)
        self._api(
            "PATCH",
            f"repos/{repo.full_name}/issues/{number}",
            "state=closed",
            "state_reason=not_planned",
        )

    def reopen(self, repo: RepoRef, kind: str, number: int) -> None:
        """Reopen, then take the ``shelved`` label off."""
        endpoint = "pulls" if kind == "pr" else "issues"
        self._api("PATCH", f"repos/{repo.full_name}/{endpoint}/{number}", "state=open")
        self._api("DELETE", f"repos/{repo.full_name}/issues/{number}/labels/{SHELVED}")

    def note(self, repo: RepoRef, number: int, comment: str) -> None:
        """Post a close-out note on an issue; nothing else changes."""
        self._comment(repo, number, comment)


__all__ = [
    "AGENT_FINDING",
    "MAX_PAGES",
    "SHELVED",
    "Branch",
    "Comment",
    "GhWriter",
    "LinkedIssue",
    "OpenPull",
    "RepoSnapshot",
    "ShelvedItem",
    "Thread",
    "read_linked_issue",
    "read_snapshot",
]

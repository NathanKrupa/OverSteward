# ABOUTME: INNER transport for the Estate Board — reads one repository's issues through gh.
# ABOUTME: Pages every list to its end and proves it against GitHub's count; a short read is refused.

"""Read a repository's issues the way the board needs them.

Three lists per repository: every open issue, every label (to learn which
``epic:<slug>`` labels exist), and every *closed* issue carrying any of those
labels. Then one read per issue an *open epic's body* names that none of those
lists held — a closed child without the label is exactly the child that turns
"no children" into "every child is closed". A number that is a pull request or
does not exist is not a child; any other failure is the repository being
unreadable.

Each list is read through GraphQL a page at a time until GitHub reports no
next page, and is then proved complete: every page must report the same
``totalCount``, and the distinct rows read must number exactly that. A list
that changed under the read, ran past :data:`MAX_PAGES`, or came back short is
a :class:`TruncatedReadError`, never a report — an estate read short is a
smaller estate than exists. GraphQL's issue lists hold issues only, never pull
requests.

:func:`_page` is the one-call ``gh … --limit`` read other transports still use;
it refuses a page that fills its limit, because ``gh`` truncates silently.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from oversteward.board.config import RepoRef
from oversteward.board.models import EPIC_LABEL_PREFIX, Issue

#: Rows asked for per GraphQL page — GitHub's maximum.
PAGE_SIZE = 100

#: Pages read per list before the read is refused as incomplete.
MAX_PAGES = 40

_ISSUES = """
query($owner: String!, $name: String!, $states: [IssueState!], $labels: [String!],
      $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(states: $states, labels: $labels, first: %d, after: $cursor,
           orderBy: {field: CREATED_AT, direction: ASC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        number title url state createdAt updatedAt closedAt body
        labels(first: 100) { totalCount nodes { name } }
      }
    }
  }
}
""" % PAGE_SIZE

_LABELS = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    labels(first: %d, after: $cursor) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes { name }
    }
  }
}
""" % PAGE_SIZE

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
    """``gh <args>``'s stdout parsed as JSON.

    A ``gh`` that cannot be run (absent from PATH, not executable) or exits
    non-zero is a :class:`GhError`, which reaches the same handlers as any other
    ``gh`` failure.
    """
    try:
        proc = subprocess.run(
            ["gh", *args], capture_output=True, text=True, encoding="utf-8", check=False
        )
    except OSError as exc:
        raise GhError(f"gh could not be run for `gh {' '.join(args)}`: {exc}") from exc
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


def graphql(run: Runner, query: str, repo: RepoRef, **variables: object) -> dict:
    """``repository`` from one GraphQL call; GraphQL errors are a :class:`GhError`.

    A list or tuple variable goes as a GraphQL list (``-f key[]=item`` per
    item), an ``int`` as a typed field (``-F``), anything else as a string.
    """
    owner, name = repo.full_name.split("/", 1)
    args = ["api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}"]
    for key, value in variables.items():
        if isinstance(value, list | tuple):
            for item in value:
                args += ["-f", f"{key}[]={item}"]
        elif isinstance(value, int):
            args += ["-F", f"{key}={value}"]
        else:
            args += ["-f", f"{key}={value}"]
    data = run(args)
    if data.get("errors"):
        raise GhError(f"{repo.full_name}: GraphQL errors {data['errors']}")
    return data["data"]["repository"]


def _counted(
    run: Runner, query: str, repo: RepoRef, key: str, ident: str, what: str, **variables: object
) -> list[dict]:
    """Every node of ``repository.<key>``, proved complete against its ``totalCount``.

    Rows are keyed by ``ident``, so a row two pages both return counts once
    and cannot stand in for one neither returned.
    """
    rows: dict[object, dict] = {}
    totals: set[int] = set()
    cursor: dict[str, str] = {}
    for _ in range(MAX_PAGES):
        connection = graphql(run, query, repo, **variables, **cursor)[key]
        totals.add(int(connection["totalCount"]))
        for node in connection["nodes"]:
            rows[node[ident]] = node
        if not connection["pageInfo"]["hasNextPage"]:
            break
        cursor = {"cursor": connection["pageInfo"]["endCursor"]}
    else:
        raise TruncatedReadError(f"{repo.name}: {what} ran past {MAX_PAGES} pages")
    if len(totals) != 1 or len(rows) != next(iter(totals)):
        counted = ", ".join(str(total) for total in sorted(totals))
        raise TruncatedReadError(
            f"{repo.name}: {what} read {len(rows)} rows but GitHub counts {counted}"
            " — the read is incomplete"
        )
    return list(rows.values())


def _issue_row(repo: RepoRef, node: dict) -> dict:
    """A GraphQL issue node in the ``gh issue list --json`` shape."""
    labels = node.get("labels") or {}
    names = [{"name": label["name"]} for label in labels.get("nodes") or ()]
    if int(labels.get("totalCount", 0)) > len(names):
        raise TruncatedReadError(
            f"{repo.name}: #{node['number']} carries more labels than one page holds"
            " — the read is incomplete"
        )
    return {**node, "labels": names}


def read_labels(repo: RepoRef, *, run: Runner = gh_json) -> list[str]:
    """Every label name in the repository, proved complete."""
    nodes = _counted(run, _LABELS, repo, "labels", "name", "labels")
    return [node["name"] for node in nodes]


def read_issues(
    repo: RepoRef,
    state: str,
    *,
    labels: Sequence[str] = (),
    what: str,
    run: Runner = gh_json,
) -> list[dict]:
    """Every issue in ``state`` (``OPEN``/``CLOSED``), proved complete.

    ``labels``, when given, keeps issues carrying *any* of them — GitHub's
    ``labels`` filter is an OR. Rows come back in the ``gh issue list --json``
    shape :meth:`Issue.from_gh` reads.
    """
    variables: dict[str, object] = {"states": [state]}
    if labels:
        variables["labels"] = list(labels)
    nodes = _counted(run, _ISSUES, repo, "issues", "number", what, **variables)
    return [_issue_row(repo, node) for node in nodes]


def read_repo(repo: RepoRef, *, run: Runner = gh_json) -> tuple[Issue, ...]:
    """Every open issue plus every closed issue carrying an ``epic:`` label."""
    open_rows = read_issues(repo, "OPEN", what="open issues", run=run)
    epic_labels = sorted(
        name for name in read_labels(repo, run=run) if name.startswith(EPIC_LABEL_PREFIX)
    )
    closed_rows: list[dict] = []
    if epic_labels:
        closed_rows = read_issues(
            repo, "CLOSED", labels=epic_labels, what="closed epic issues", run=run
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
    "MAX_PAGES",
    "PAGE_SIZE",
    "GhError",
    "NotFoundError",
    "TruncatedReadError",
    "gh_json",
    "graphql",
    "read_estate",
    "read_issues",
    "read_labels",
    "read_repo",
]

# ABOUTME: INNER connector for the ci-red sweep — reads ci-red issues, PRs and runs through gh,
# ABOUTME: closes an issue when told to, and reads each repo's committed ci.yml through git refs.

"""What the ci-red sweep reads, and the one write it makes.

GitHub is reached through ``gh`` (an injected runner); every failure, a
truncated page included, is :class:`SourceUnavailableError` — a repository that
could not be read must never print as a repository with nothing open.

Whether a repository is *watched* is read from its committed
``origin/<branch>:.github/workflows/ci.yml`` through :class:`GitRepo`, never
its working tree: a workflow carrying a ``ci-red-alert`` job files the issues
this sweep reads, so a repo without one reports ``0 open`` because nothing
could ever be filed there. The ref is read as it stands, without a fetch.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import yaml

from oversteward.board.config import repos_from_registry
from oversteward.dev_family import GitRepo
from oversteward.intake.github import GhError, gh, gh_json
from oversteward.intake.labels import CI_RED

#: One page of open ci-red issues per repository; a full page is refused, not trusted.
ISSUE_LIMIT = 200
CI_WORKFLOW = ".github/workflows/ci.yml"
ALERT_JOB = "ci-red-alert"

STATE_OPEN = "open"
STATE_CLOSED = "closed"

Runner = Callable[[list[str]], Any]


class SourceUnavailableError(RuntimeError):
    """GitHub or a checkout could not be read; nothing read from it may be reported."""


@dataclass(frozen=True)
class Target:
    """One dispatch target: its registry id, GitHub ``owner/name``, checkout and branch."""

    id: str
    full_name: str
    checkout: Path
    branch: str


def targets_from_registry(registry: dict[str, Any]) -> list[Target]:
    """Every dispatch target, in registry order; one missing its checkout or branch is refused."""
    contexts = {c.get("id"): c for c in registry.get("contexts") or []}
    targets: list[Target] = []
    for ref in repos_from_registry(registry):
        context = contexts.get(ref.id) or {}
        checkout, branch = context.get("local_path"), context.get("branch")
        if not checkout or not branch:
            raise ValueError(f"dispatch target {ref.id!r} names no local_path or branch")
        targets.append(Target(ref.id, ref.full_name, Path(checkout), str(branch)))
    return targets


@dataclass(frozen=True)
class RawIssue:
    number: int
    title: str
    body: str
    comments: tuple[str, ...]
    state: str
    labels: frozenset[str]
    #: When the issue was opened, and when each comment was posted (parallel to ``comments``),
    #: as GitHub's ISO-8601 strings.
    created_at: str = ""
    comment_times: tuple[str, ...] = ()


@dataclass(frozen=True)
class PrInfo:
    #: ``OPEN``, ``CLOSED`` or ``MERGED``, as GitHub spells it.
    state: str
    merged_at: str | None
    #: The PR's head commit — for a merged PR, the head it merged at — or ``None`` if unread.
    head_sha: str | None = None
    #: The PR's commits, oldest first, as GitHub lists them.
    commits: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunInfo:
    conclusion: str
    head_sha: str
    workflow_id: int


def _raw_issue(row: Any, where: str) -> RawIssue:
    if not isinstance(row, dict) or not isinstance(row.get("number"), int):
        raise SourceUnavailableError(f"{where}: gh returned no issue object")
    comments = tuple(row.get("comments") or ())
    return RawIssue(
        number=row["number"],
        title=row.get("title") or "",
        body=row.get("body") or "",
        comments=tuple(c.get("body") or "" for c in comments),
        state=str(row.get("state") or "").lower(),
        labels=frozenset(label.get("name", "") for label in row.get("labels") or ()),
        created_at=str(row.get("createdAt") or ""),
        comment_times=tuple(str(c.get("createdAt") or "") for c in comments),
    )


class GithubCiRed:
    """The ci-red sweep's GitHub reads, and its one write: closing an issue with a comment."""

    _FIELDS = "number,title,body,comments,state,labels,createdAt"

    def __init__(self, *, run_json: Runner = gh_json, run: Runner = gh) -> None:
        self._json = run_json
        self._run = run

    def _read(self, args: list[str]) -> Any:
        try:
            return self._json(args)
        except GhError as exc:
            raise SourceUnavailableError(str(exc)) from exc

    def open_ci_red(self, full_name: str) -> tuple[RawIssue, ...]:
        rows = self._read(
            [
                "issue", "list", "--repo", full_name, "--label", CI_RED, "--state", "open",
                "--json", self._FIELDS, "--limit", str(ISSUE_LIMIT),
            ]
        )
        if not isinstance(rows, list):
            raise SourceUnavailableError(f"{full_name}: gh returned no issue list")
        if len(rows) >= ISSUE_LIMIT:
            raise SourceUnavailableError(
                f"{full_name}: open ci-red issues filled the page of {ISSUE_LIMIT}"
            )
        return tuple(_raw_issue(row, full_name) for row in rows)

    def issue(self, full_name: str, number: int) -> RawIssue:
        row = self._read(
            ["issue", "view", str(number), "--repo", full_name, "--json", self._FIELDS]
        )
        return _raw_issue(row, f"{full_name}#{number}")

    def issue_state(self, full_name: str, number: int) -> str:
        """``open`` or ``closed``; anything else is a failed read."""
        state = self.issue(full_name, number).state
        if state not in (STATE_OPEN, STATE_CLOSED):
            raise SourceUnavailableError(f"{full_name}#{number}: unexpected state {state!r}")
        return state

    def pr_info(self, full_name: str, number: int) -> PrInfo:
        row = self._read(
            [
                "pr", "view", str(number), "--repo", full_name,
                "--json", "state,mergedAt,headRefOid,commits",
            ]
        )
        state = row.get("state") if isinstance(row, dict) else None
        if state not in ("OPEN", "CLOSED", "MERGED"):
            raise SourceUnavailableError(f"{full_name} PR #{number}: unexpected state {state!r}")
        commits = tuple(
            str(c["oid"]) for c in row.get("commits") or () if isinstance(c, dict) and c.get("oid")
        )
        return PrInfo(state, row.get("mergedAt") or None, row.get("headRefOid") or None, commits)

    def run_info(self, full_name: str, run_id: int) -> RunInfo:
        row = self._read(
            [
                "run", "view", str(run_id), "--repo", full_name,
                "--json", "conclusion,headSha,workflowDatabaseId",
            ]
        )
        if not isinstance(row, dict) or not isinstance(row.get("workflowDatabaseId"), int):
            raise SourceUnavailableError(f"{full_name} run {run_id}: gh returned no run object")
        return RunInfo(
            conclusion=str(row.get("conclusion") or ""),
            head_sha=str(row.get("headSha") or ""),
            workflow_id=row["workflowDatabaseId"],
        )

    def close(self, full_name: str, number: int, comment: str) -> None:
        try:
            self._run(["issue", "close", str(number), "--repo", full_name, "--comment", comment])
        except GhError as exc:
            raise SourceUnavailableError(str(exc)) from exc


class RefReader(Protocol):
    def has_ref(self, ref: str) -> bool: ...

    def blob(self, ref: str, relpath: str) -> bytes | None: ...


def watched(target: Target, *, repo_factory: Callable[[Path], RefReader] = GitRepo) -> bool:
    """Whether ``origin/<branch>:ci.yml`` carries a ``ci-red-alert`` job.

    No workflow file is *unwatched*; an absent ref or an unparseable workflow is
    a failed read, never a guess either way.
    """
    repo = repo_factory(target.checkout)
    ref = f"origin/{target.branch}"
    if not repo.has_ref(ref):
        raise SourceUnavailableError(f"{target.id}: {ref} is not a ref in {target.checkout}")
    blob = repo.blob(ref, CI_WORKFLOW)
    if blob is None:
        return False
    try:
        workflow = yaml.safe_load(blob)
    except yaml.YAMLError as exc:
        raise SourceUnavailableError(f"{target.id}: {ref}:{CI_WORKFLOW} is not YAML") from exc
    jobs = workflow.get("jobs") if isinstance(workflow, dict) else None
    return isinstance(jobs, dict) and ALERT_JOB in jobs

# ABOUTME: INNER connector for the ci-red sweep — reads ci-red issues, PRs, runs and jobs through
# ABOUTME: gh, closes an issue when told to, and reads each repo's committed ci.yml via git refs.

"""What the ci-red sweep reads, and the one write it makes.

GitHub is reached through ``gh`` (an injected runner); every failure, a
truncated page included, is :class:`SourceUnavailableError` — a repository that
could not be read must never print as a repository with nothing open.

Whether a repository is *watched* is read from its committed
``origin/<branch>:.github/workflows/ci.yml`` through :class:`GitRepo`, never
its working tree: a workflow carrying a ``ci-red-alert`` job files the issues
this sweep reads, so a repo without one reports ``0 open`` because nothing
could ever be filed there. The ref is read as it stands, without a fetch. The
same job's ``if:`` names the trunks it watches (each ``github.base_ref ==
'<branch>'``), and the sweep reads the watched workflow's latest run on each.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
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
#: Each trunk the alert job's ``if:`` covers is named as ``github.base_ref == '<branch>'``.
_BASE_REF = re.compile(r"github\.base_ref\s*==\s*'([^']+)'")
#: One page of a run's jobs, or of a job's annotations; a full or short page is refused.
JOB_PAGE = 100

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


@dataclass(frozen=True)
class WatchRun:
    """The newest run of the watched workflow on one PR head, as of its latest attempt."""

    id: int
    status: str
    conclusion: str
    started_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class JobInfo:
    """One job of a run's latest attempt; ``steps`` is how many steps GitHub lists for it."""

    id: int
    name: str
    conclusion: str
    steps: int


def _stamp(value: Any, where: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise SourceUnavailableError(f"{where}: unreadable timestamp {value!r}") from exc
    if stamp.tzinfo is None:
        raise SourceUnavailableError(f"{where}: timestamp {value!r} names no zone")
    return stamp


def _watch_run(row: Any, where: str) -> WatchRun:
    if not isinstance(row, dict) or not isinstance(row.get("id"), int):
        raise SourceUnavailableError(f"{where}: gh returned no run object")
    return WatchRun(
        id=row["id"],
        status=str(row.get("status") or ""),
        conclusion=str(row.get("conclusion") or ""),
        started_at=_stamp(row.get("run_started_at"), where),
        updated_at=_stamp(row.get("updated_at"), where),
    )


def _job(row: Any, where: str) -> JobInfo:
    if not isinstance(row, dict) or not isinstance(row.get("id"), int):
        raise SourceUnavailableError(f"{where}: gh returned no job object")
    steps = row.get("steps")
    if not isinstance(steps, list):
        raise SourceUnavailableError(f"{where}: job {row['id']} lists no steps array")
    return JobInfo(row["id"], str(row.get("name") or ""), str(row.get("conclusion") or ""),
                   len(steps))


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

    def recent_pr_heads(self, full_name: str, base: str, limit: int) -> tuple[str, ...]:
        """The head commit of each of the ``limit`` most recently updated PRs into ``base``."""
        rows = self._read(
            [
                "pr", "list", "--repo", full_name, "--base", base, "--state", "all",
                "--search", "sort:updated-desc",
                "--limit", str(limit), "--json", "number,headRefOid",
            ]
        )
        if not isinstance(rows, list):
            raise SourceUnavailableError(f"{full_name}: gh returned no PR list into {base}")
        heads = tuple(row.get("headRefOid") for row in rows if isinstance(row, dict))
        if len(heads) != len(rows) or not all(isinstance(h, str) and h for h in heads):
            raise SourceUnavailableError(f"{full_name}: a PR into {base} came back without a head")
        return heads

    def newest_run(self, full_name: str, workflow: str, head_sha: str) -> WatchRun | None:
        """The newest ``pull_request`` run of ``workflow`` on ``head_sha``, or ``None``."""
        row = self._read(
            [
                "api", f"repos/{full_name}/actions/workflows/{workflow}/runs"
                f"?head_sha={head_sha}&event=pull_request&per_page=1",
            ]
        )
        runs = row.get("workflow_runs") if isinstance(row, dict) else None
        if not isinstance(runs, list):
            raise SourceUnavailableError(f"{full_name}: {workflow} runs on {head_sha} unreadable")
        return _watch_run(runs[0], f"{full_name} {workflow}") if runs else None

    def run_jobs(self, full_name: str, run_id: int) -> tuple[JobInfo, ...]:
        """Every job of the run's latest attempt; a page that does not hold them all is refused."""
        where = f"{full_name} run {run_id}"
        row = self._read(
            ["api", f"repos/{full_name}/actions/runs/{run_id}/jobs?per_page={JOB_PAGE}"]
        )
        jobs = row.get("jobs") if isinstance(row, dict) else None
        if not isinstance(jobs, list) or row.get("total_count") != len(jobs):
            raise SourceUnavailableError(f"{where}: jobs unreadable or not all on one page")
        return tuple(_job(job, where) for job in jobs)

    def job_annotations(self, full_name: str, job_id: int) -> tuple[str, ...]:
        """The message of each annotation on a job's check run."""
        rows = self._read(
            ["api", f"repos/{full_name}/check-runs/{job_id}/annotations?per_page={JOB_PAGE}"]
        )
        if not isinstance(rows, list) or len(rows) >= JOB_PAGE:
            raise SourceUnavailableError(f"{full_name} job {job_id}: annotations unreadable")
        return tuple(str(row.get("message") or "") for row in rows if isinstance(row, dict))

    def close(self, full_name: str, number: int, comment: str) -> None:
        try:
            self._run(["issue", "close", str(number), "--repo", full_name, "--comment", comment])
        except GhError as exc:
            raise SourceUnavailableError(str(exc)) from exc


class RefReader(Protocol):
    def has_ref(self, ref: str) -> bool: ...

    def blob(self, ref: str, relpath: str) -> bytes | None: ...


def _workflow_jobs(target: Target, repo_factory: Callable[[Path], RefReader]) -> dict | None:
    """The ``jobs`` of ``origin/<branch>:ci.yml``, or ``None`` when there is no such file."""
    repo = repo_factory(target.checkout)
    ref = f"origin/{target.branch}"
    if not repo.has_ref(ref):
        raise SourceUnavailableError(f"{target.id}: {ref} is not a ref in {target.checkout}")
    blob = repo.blob(ref, CI_WORKFLOW)
    if blob is None:
        return None
    try:
        workflow = yaml.safe_load(blob)
    except yaml.YAMLError as exc:
        raise SourceUnavailableError(f"{target.id}: {ref}:{CI_WORKFLOW} is not YAML") from exc
    jobs = workflow.get("jobs") if isinstance(workflow, dict) else None
    return jobs if isinstance(jobs, dict) else None


def alert_trunks(
    target: Target, *, repo_factory: Callable[[Path], RefReader] = GitRepo
) -> tuple[str, ...]:
    """The trunks ``origin/<branch>:ci.yml``'s ``ci-red-alert`` job covers; ``()`` is unwatched.

    No workflow file, or no alert job, is *unwatched*. An absent ref, an
    unparseable workflow, or an alert job whose ``if:`` names no
    ``github.base_ref`` is a failed read, never a guess either way: the sweep
    cannot say which trunk's runs to read.
    """
    jobs = _workflow_jobs(target, repo_factory)
    if jobs is None or ALERT_JOB not in jobs:
        return ()
    job = jobs[ALERT_JOB]
    condition = job.get("if") if isinstance(job, dict) else None
    trunks = tuple(dict.fromkeys(_BASE_REF.findall(str(condition or ""))))
    if not trunks:
        raise SourceUnavailableError(
            f"{target.id}: origin/{target.branch}:{CI_WORKFLOW} {ALERT_JOB} names no "
            "github.base_ref trunk"
        )
    return trunks

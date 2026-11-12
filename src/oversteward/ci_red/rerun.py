# ABOUTME: MIDDLE service for `ci_red.py rerun` — re-dispatches a ci-red issue's workflow on the
# ABOUTME: one commit its closing verdict would accept, through a temporary branch it then deletes.

"""Re-run a ci-red issue's CI after GitHub orphaned the run that would have cleared it (OS#702).

``green`` and ``fixed-in-place`` close an issue only on a successful run of the
red run's workflow at one particular commit. When GitHub loses that run, this
produces a fresh one there, and nothing more: it closes nothing, and the caller
records the verdict with ``ci_red.py record`` once the run is green.

**Which commit.** The red PR's merge head when the PR merged at a commit it
lists after the one the issue reports testing — the commit ``fixed-in-place``
accepts. Otherwise (the PR is unmerged, merged at the tested commit itself, or
the issue names no PR) the tested commit, which ``green`` accepts.

**How.** A workflow is dispatched on a branch, so ``ci-verify-<n>`` is created
at that commit and the workflow is dispatched on it. Once the new run is seen,
the branch is deleted, but only while it still points at that commit: a branch
someone has moved is left where it is and reported. A branch already gone is
done.

Everything that can refuse is checked before anything is written: the issue
must be one the last sweep saw and still open, it must report its tested commit
and red run, the workflow at that commit must declare ``workflow_dispatch``, and
``ci-verify-<n>`` must not already exist.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

import yaml

from .sources import SourceUnavailableError, Target
from .triage import (
    VERDICT_FIXED_IN_PLACE,
    VERDICT_GREEN,
    CiRedIssue,
    CiRedSource,
    CiRedUnreadable,
    VerdictError,
    VerdictStore,
    follows,
    swept_issue,
)

BRANCH_PREFIX = "ci-verify-"
#: How often, and how many seconds apart, the new run is looked for after the dispatch.
RUN_READS = 10
RUN_READ_INTERVAL = 3.0

REF_DELETED = "deleted"
REF_ALREADY_GONE = "already gone"
DISPATCH_TRIGGER = "workflow_dispatch"


class RerunRefused(RuntimeError):
    """The rerun was refused before anything was written."""


class WorkflowSource(Protocol):
    def workflow_path(self, full_name: str, workflow_id: int) -> str: ...

    def file_at(self, full_name: str, path: str, sha: str) -> bytes: ...

    def ref_sha(self, full_name: str, branch: str) -> str | None: ...

    def create_ref(self, full_name: str, branch: str, sha: str) -> None: ...

    def delete_ref(self, full_name: str, branch: str) -> None: ...

    def dispatch(self, full_name: str, workflow_id: int, branch: str) -> None: ...

    def dispatched_runs(
        self, full_name: str, workflow_id: int, branch: str
    ) -> tuple[tuple[int, str], ...]: ...


@dataclass(frozen=True)
class Rerun:
    """A dispatched run, the verdict it can support, and what became of the temporary branch."""

    key: str
    verdict: str
    sha: str
    run_id: int
    workflow_path: str
    branch: str
    #: :data:`REF_DELETED`, :data:`REF_ALREADY_GONE`, or why the branch was left in place.
    ref_outcome: str

    @property
    def ref_left(self) -> bool:
        return self.ref_outcome not in (REF_DELETED, REF_ALREADY_GONE)


def _read[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except SourceUnavailableError as exc:
        raise CiRedUnreadable(str(exc)) from exc


def verdict_commit(issue: CiRedIssue, target: Target, source: CiRedSource) -> tuple[str, str]:
    """The closing verdict a green run can support, and the commit that run must test."""
    if issue.tested_sha is None or issue.red_run is None:
        raise RerunRefused(f"{issue.key} reports no tested commit and red run to re-run")
    if issue.red_pr is None:
        return VERDICT_GREEN, issue.tested_sha
    pr = _read(lambda: source.pr_info(target.full_name, issue.red_pr))
    if pr.state != "MERGED":
        return VERDICT_GREEN, issue.tested_sha
    if pr.head_sha is None:
        raise CiRedUnreadable(f"PR #{issue.red_pr}'s merge head could not be read")
    if follows(pr.commits, issue.tested_sha, pr.head_sha):
        return VERDICT_FIXED_IN_PLACE, pr.head_sha
    return VERDICT_GREEN, issue.tested_sha


def _triggers(workflow: Any) -> Any:
    """The workflow's ``on:``, which YAML 1.1 reads as the key ``True``."""
    if not isinstance(workflow, dict):
        return None
    return workflow.get("on", workflow.get(True))


def dispatchable(blob: bytes) -> bool:
    """Whether a workflow file declares the ``workflow_dispatch`` trigger."""
    try:
        triggers = _triggers(yaml.safe_load(blob))
    except yaml.YAMLError as exc:
        raise CiRedUnreadable("the workflow file is not YAML") from exc
    if isinstance(triggers, str):
        return triggers == DISPATCH_TRIGGER
    if isinstance(triggers, (list, dict)):
        return DISPATCH_TRIGGER in triggers
    return False


@dataclass(frozen=True)
class _Plan:
    target: Target
    issue: CiRedIssue
    verdict: str
    sha: str
    workflow_id: int
    workflow_path: str
    branch: str


def _plan(
    store: VerdictStore,
    source: CiRedSource,
    workflows: WorkflowSource,
    targets: Iterable[Target],
    key: str,
) -> _Plan:
    """Everything the rerun needs, with every refusal raised before anything is written."""
    try:
        target, issue = swept_issue(store, source, targets, key)
    except VerdictError as exc:
        raise RerunRefused(str(exc)) from exc
    verdict, sha = verdict_commit(issue, target, source)
    red = _read(lambda: source.run_info(target.full_name, issue.red_run))
    path = _read(lambda: workflows.workflow_path(target.full_name, red.workflow_id))
    blob = _read(lambda: workflows.file_at(target.full_name, path, sha))
    if not dispatchable(blob):
        raise RerunRefused(
            f"{target.id}: {path} at {sha} has no {DISPATCH_TRIGGER} trigger, so it cannot be "
            "dispatched"
        )
    branch = f"{BRANCH_PREFIX}{issue.number}"
    existing = _read(lambda: workflows.ref_sha(target.full_name, branch))
    if existing is not None:
        raise RerunRefused(
            f"{target.id}: branch {branch} already exists at {existing}; left in place"
        )
    return _Plan(target, issue, verdict, sha, red.workflow_id, path, branch)


def _settle_ref(workflows: WorkflowSource, plan: _Plan) -> str:
    """Delete the temporary branch only while it still holds the dispatched commit."""
    full_name = plan.target.full_name
    now = _read(lambda: workflows.ref_sha(full_name, plan.branch))
    if now is None:
        return REF_ALREADY_GONE
    if now != plan.sha:
        return f"moved to {now}"
    _read(lambda: workflows.delete_ref(full_name, plan.branch))
    return REF_DELETED


def _settle_or_report(workflows: WorkflowSource, plan: _Plan) -> str:
    """:func:`_settle_ref`, with a branch that could not be read reported as left in place."""
    try:
        return _settle_ref(workflows, plan)
    except CiRedUnreadable as exc:
        return f"could not be checked — {exc}"


def _new_run(
    workflows: WorkflowSource, plan: _Plan, before: set[int], sleep: Callable[[float], None]
) -> int | None:
    for _ in range(RUN_READS):
        sleep(RUN_READ_INTERVAL)
        try:
            runs = workflows.dispatched_runs(plan.target.full_name, plan.workflow_id, plan.branch)
        except SourceUnavailableError as exc:
            raise CiRedUnreadable(
                f"dispatched, but the runs on {plan.branch} could not be read — {exc}; "
                f"{plan.branch} left in place"
            ) from exc
        fresh = [run_id for run_id, head in runs if run_id not in before and head == plan.sha]
        if fresh:
            return max(fresh)
    return None


def _dispatch(workflows: WorkflowSource, plan: _Plan) -> None:
    """Dispatch the workflow; on failure take the branch back down and report what is left."""
    full_name = plan.target.full_name
    try:
        workflows.dispatch(full_name, plan.workflow_id, plan.branch)
    except SourceUnavailableError as exc:
        outcome = _settle_or_report(workflows, plan)
        left = "" if outcome in (REF_DELETED, REF_ALREADY_GONE) else (
            f"; {plan.branch} {outcome}, left in place"
        )
        raise CiRedUnreadable(f"the dispatch failed — {exc}{left}") from exc


def rerun(
    store: VerdictStore,
    source: CiRedSource,
    workflows: WorkflowSource,
    targets: Iterable[Target],
    key: str,
    *,
    sleep: Callable[[float], None],
) -> Rerun:
    """Dispatch the issue's workflow on the commit its verdict needs, then clear the branch."""
    plan = _plan(store, source, workflows, targets, key)
    full_name = plan.target.full_name
    before = {
        run_id
        for run_id, _ in _read(
            lambda: workflows.dispatched_runs(full_name, plan.workflow_id, plan.branch)
        )
    }
    _read(lambda: workflows.create_ref(full_name, plan.branch, plan.sha))
    _dispatch(workflows, plan)
    run_id = _new_run(workflows, plan, before, sleep)
    if run_id is None:
        raise CiRedUnreadable(
            f"dispatched, but no run of {plan.workflow_path} on {plan.branch} at {plan.sha} "
            f"appeared after {RUN_READS} reads; {plan.branch} left in place"
        )
    outcome = _settle_or_report(workflows, plan)
    return Rerun(
        plan.issue.key, plan.verdict, plan.sha, run_id, plan.workflow_path, plan.branch, outcome
    )

# ABOUTME: MIDDLE service for the ci-red sweep — proves the watched workflow actually ran on each
# ABOUTME: trunk, so a run GitHub refused to start (billing) reads "could not look", never "0 open".

"""Did the watchdog that files ci-red issues run at all? (OS#838)

``0 open`` means "CI ran and nothing went red" only if CI ran. On 2026-11-27
GitHub refused every job in two repositories at the billing gate: each run
concluded ``failure`` in seconds with zero steps, the ``ci-red-alert`` job was
refused with the rest, and the sweep printed the same zero as a clean line.

For each trunk a watched repository's alert job covers, this reads the newest
run of the watched workflow on the newest PR into that trunk whose run has
finished: a PR whose newest run is still queued or in progress is passed over
for the next, since its verdict is not in yet, and so is a PR GitHub started no
run for at all. A billing refusal still creates the run, so it is not missed
that way. That run is refused as
:class:`SourceUnavailableError` — the sweep's "could not read", exit 1 — when

- no job of its latest attempt ran a step (no jobs at all included), or
- it concluded ``failure`` within :data:`REFUSAL_SECONDS` of starting and a job
  carries GitHub's "The job was not started" annotation.

A red run whose jobs ran steps is the alert job's business, and a green run is
clean; neither is touched here. Re-running the refused run (``gh run rerun``)
is what clears it, because GitHub then reports the new attempt.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Protocol

from .sources import CI_WORKFLOW, JobInfo, SourceUnavailableError, Target, WatchRun

#: How many of a trunk's newest PRs are tried for a finished run before the read is refused.
RECENT_PRS = 5
#: Refused runs concluded about 5 s after starting on 2026-11-27 (grantspider 45956424130).
#: A quick green run exists too (marketing-manager's took 17 s), so the window never decides
#: alone: the run must also have failed with the "not started" annotation on a failed job.
REFUSAL_SECONDS = 10
#: The start of GitHub's check-run annotation on a job it never started (billing, among others).
NOT_STARTED = "The job was not started"
WORKFLOW_FILE = PurePosixPath(CI_WORKFLOW).name
STATUS_COMPLETED = "completed"
CONCLUSION_FAILURE = "failure"


class WatchdogSource(Protocol):
    def recent_pr_heads(self, full_name: str, base: str, limit: int) -> tuple[str, ...]: ...

    def newest_run(self, full_name: str, workflow: str, head_sha: str) -> WatchRun | None: ...

    def run_jobs(self, full_name: str, run_id: int) -> tuple[JobInfo, ...]: ...

    def job_annotations(self, full_name: str, job_id: int) -> tuple[str, ...]: ...


def latest_run(target: Target, trunk: str, source: WatchdogSource) -> WatchRun:
    """The newest finished run on the newest PR into ``trunk`` that has one."""
    for head in source.recent_pr_heads(target.full_name, trunk, RECENT_PRS):
        run = source.newest_run(target.full_name, WORKFLOW_FILE, head)
        if run is not None and run.status == STATUS_COMPLETED:
            return run
    raise SourceUnavailableError(
        f"could not look — no finished {WORKFLOW_FILE} run on the last "
        f"{RECENT_PRS} PRs into {trunk}"
    )


def _not_started(target: Target, jobs: tuple[JobInfo, ...], source: WatchdogSource) -> str:
    """The first "job was not started" annotation among the failed jobs, or ``""``."""
    for job in jobs:
        if job.conclusion != CONCLUSION_FAILURE:
            continue
        for message in source.job_annotations(target.full_name, job.id):
            if message.startswith(NOT_STARTED):
                return message
    return ""


def never_ran(target: Target, run: WatchRun, source: WatchdogSource) -> str:
    """Why ``run`` shows the watchdog never ran, or ``""`` when it ran."""
    jobs = source.run_jobs(target.full_name, run.id)
    if all(job.steps == 0 for job in jobs):
        cause = _not_started(target, jobs, source)
        reason = "no job ran a step" if jobs else "the run has no jobs"
        return f"{reason}: {cause}" if cause else reason
    quick = (run.updated_at - run.started_at).total_seconds() <= REFUSAL_SECONDS
    if run.conclusion == CONCLUSION_FAILURE and quick:
        cause = _not_started(target, jobs, source)
        if cause:
            return f"failed within {REFUSAL_SECONDS}s: {cause}"
    return ""


def check_watchdog(target: Target, trunks: tuple[str, ...], source: WatchdogSource) -> None:
    """Refuse the reading when the watched workflow's latest run on any trunk never ran."""
    for trunk in trunks:
        run = latest_run(target, trunk, source)
        reason = never_ran(target, run, source)
        if reason:
            raise SourceUnavailableError(
                f"could not look — the watchdog never ran on {trunk}: "
                f"{WORKFLOW_FILE} run {run.id} ({reason}); after the cause is fixed, "
                f"gh run rerun {run.id} --repo {target.full_name}"
            )

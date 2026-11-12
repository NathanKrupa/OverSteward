# ABOUTME: Renders the ci-red sweep — a headline with the repo count, each repo's watch state,
# ABOUTME: and every open ci-red issue with its override count; also a verdict and a rerun.

from __future__ import annotations

from .rerun import Rerun
from .triage import VERDICTS, Ruling, SweepResult


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def render_sweep(result: SweepResult) -> str:
    lines = [
        f"ci-red sweep — {_plural(result.open_count, 'ci-red issue')} open across "
        f"{_plural(len(result.readings), 'repo')} checked"
    ]
    for reading in result.readings:
        state = "watched" if reading.watched else "unwatched"
        lines.append(f"  {reading.target.id}: {len(reading.issues)} open ci-red, {state}")
    if result.queue:
        lines.append(f"Awaiting a verdict ({len(result.queue)}):")
        for queued in result.queue:
            issue = queued.issue
            lines.append(
                f"  {issue.key} — {issue.title} — {_plural(issue.overrides, 'override')}"
            )
            if queued.reason:
                lines.append(f"      {queued.reason}")
        lines.append(
            "Record: scripts/ci_red.py record <repo>#<n> "
            f"{'|'.join(VERDICTS)} --ref <ref>"
        )
    if result.tracked:
        lines.append(f"Line stays stopped, ruled ({len(result.tracked)}):")
        for tracked in result.tracked:
            issue, ruling = tracked.issue, tracked.ruling
            lines.append(
                f"  {issue.key} — {ruling.verdict} → {ruling.ref} — "
                f"{_plural(issue.overrides, 'override')}"
            )
    return "\n".join(lines) + "\n"


def render_record(ruling: Ruling) -> str:
    return f"recorded {ruling.key}: {ruling.verdict} → {ruling.ref}"


def render_rerun(result: Rerun) -> str:
    return (
        f"dispatched run {result.run_id} of {result.workflow_path} on {result.sha} "
        f"via {result.branch} for {result.key}\n"
        f"  {result.branch}: {result.ref_outcome}\n"
        f"Once it is green: scripts/ci_red.py record {result.key} {result.verdict} "
        f"--ref {result.run_id}\n"
    )

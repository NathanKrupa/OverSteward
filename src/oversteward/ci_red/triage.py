# ABOUTME: MIDDLE service for the ci-red sweep — reads every dispatch target's open ci-red issues,
# ABOUTME: keeps the verdict ledger, and closes an issue only after its verdict's ref is verified.

"""The ci-red sweep (OS#664): the eighth session-start sweep.

An open ``ci-red`` issue stops the line (``intake/line.py``) and the promote
(``guard_promote_ci_red.py``). The alert that files it never closes it, so
something must, or the line stays stopped after the fix. This module is that
something, and it closes nothing it has not verified.

**Verdicts.** Each open ci-red issue is keyed ``<repo>#<n>`` (the registry id)
and takes one of five:

- ``fixed --ref <repo>#<pr>`` — that PR is MERGED. The issue is closed with a
  comment naming it.
- ``unmerged --ref <pr>`` — the PR that went red (the one the issue's title
  names) closed without merging, so no red code landed. The issue is closed.
- ``green --ref <run id>`` — that run of the same workflow concluded
  ``success`` on the commit the issue last reports testing. The red was the
  runner, not the code. The issue is closed.
- ``filed`` / ``known --ref <repo>#<issue>`` — the line stays stopped; the
  ruling holds while that issue is open and lapses, back into the queue, when
  it closes.

A ref that does not verify is :class:`VerdictError`; a ref that could not be
read is :class:`CiRedUnreadable`. Either way nothing is closed and nothing is
written. A closing verdict closes first and writes the ledger after, so a
failed close leaves no ruling claiming it happened.

**The sweep reads everything before it writes anything.** Any repository that
could not be read — its issues, its ``ci.yml`` ref, a ruling's ref issue —
fails the whole sweep, and the snapshot ``record`` checks keys against is left
as it was.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from oversteward.intake.labels import CI_RED
from oversteward.intake.line import LINE_OVERRIDE_PREFIX, PROMOTE_OVERRIDE_PREFIX

from .sources import (
    STATE_OPEN,
    RawIssue,
    RunInfo,
    SourceUnavailableError,
    Target,
)

VERDICT_FIXED = "fixed"
VERDICT_UNMERGED = "unmerged"
VERDICT_GREEN = "green"
VERDICT_FILED = "filed"
VERDICT_KNOWN = "known"
VERDICTS: tuple[str, ...] = (
    VERDICT_FIXED, VERDICT_UNMERGED, VERDICT_GREEN, VERDICT_FILED, VERDICT_KNOWN,
)
#: Verdicts that close the issue once their ref verifies.
CLOSING_VERDICTS = frozenset({VERDICT_FIXED, VERDICT_UNMERGED, VERDICT_GREEN})
#: Verdicts that leave the line stopped and hold only while their ref issue is open.
TRACKING_VERDICTS = frozenset({VERDICT_FILED, VERDICT_KNOWN})
OVERRIDE_PREFIXES = (LINE_OVERRIDE_PREFIX, PROMOTE_OVERRIDE_PREFIX)

#: The alert's title, ``ci is red on PR #<n>`` (grantspider scripts/ci/ci_red_alert.py).
_RED_PR = re.compile(r"\bci is red on PR #(\d+)\b")
#: The alert's details block, in the body and in every repeat-red comment.
_TESTED = re.compile(r"^- Commit tested: `([0-9a-f]{40})`", re.MULTILINE)
_RUN = re.compile(r"^- Run: \S*/actions/runs/(\d+)", re.MULTILINE)
_REPO_REF = re.compile(r"^(?P<repo>[a-z0-9][a-z0-9-]*)#(?P<number>[1-9][0-9]*)$")
_PR_REF = re.compile(r"^(?:(?P<repo>[a-z0-9][a-z0-9-]*)#|#)?(?P<number>[1-9][0-9]*)$")
_RUN_REF = re.compile(r"^[1-9][0-9]*$")


class CiRedUnreadable(RuntimeError):
    """A repository, an issue or a ref could not be read; nothing may be reported or written."""


class VerdictError(ValueError):
    """A verdict cannot be recorded as asked; nothing was closed."""


class CiRedSource(Protocol):
    def open_ci_red(self, full_name: str) -> tuple[RawIssue, ...]: ...

    def issue(self, full_name: str, number: int) -> RawIssue: ...

    def issue_state(self, full_name: str, number: int) -> str: ...

    def pr_state(self, full_name: str, number: int) -> str: ...

    def run_info(self, full_name: str, run_id: int) -> RunInfo: ...

    def close(self, full_name: str, number: int, comment: str) -> None: ...


# --- the issues -------------------------------------------------------------------


@dataclass(frozen=True)
class CiRedIssue:
    repo: str
    number: int
    title: str
    #: The PR the alert names in its title, if it does.
    red_pr: int | None
    #: The commit the latest red reports testing, and that red's run.
    tested_sha: str | None
    red_run: int | None
    overrides: int

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}"


def _last(pattern: re.Pattern[str], texts: Sequence[str]) -> str | None:
    found = [m.group(1) for text in texts for m in pattern.finditer(text)]
    return found[-1] if found else None


def ci_red_issue(repo: str, raw: RawIssue) -> CiRedIssue:
    """The parts of one alert issue a verdict is checked against."""
    texts = (raw.body, *raw.comments)
    pr = _RED_PR.search(raw.title)
    run = _last(_RUN, texts)
    return CiRedIssue(
        repo=repo,
        number=raw.number,
        title=raw.title,
        red_pr=int(pr.group(1)) if pr else None,
        tested_sha=_last(_TESTED, texts),
        red_run=int(run) if run else None,
        overrides=sum(1 for c in raw.comments if c.lstrip().startswith(OVERRIDE_PREFIXES)),
    )


@dataclass(frozen=True)
class RepoReading:
    target: Target
    watched: bool
    issues: tuple[CiRedIssue, ...]


def read_estate(
    targets: Iterable[Target], source: CiRedSource, watched: Callable[[Target], bool]
) -> tuple[RepoReading, ...]:
    """Every target's open ci-red issues and watch state; any unreadable one fails them all."""
    readings: list[RepoReading] = []
    failures: list[str] = []
    for target in targets:
        try:
            raws = source.open_ci_red(target.full_name)
            is_watched = watched(target)
        except SourceUnavailableError as exc:
            failures.append(f"{target.id}: {exc}")
            continue
        issues = tuple(ci_red_issue(target.id, raw) for raw in raws)
        readings.append(RepoReading(target, is_watched, issues))
    if failures:
        raise CiRedUnreadable("; ".join(failures))
    return tuple(readings)


# --- the verdict ledger ---------------------------------------------------------


@dataclass(frozen=True)
class Ruling:
    """One recorded verdict. Keyed by ``key``; a later line supersedes an earlier one."""

    key: str
    verdict: str
    ref: str
    recorded_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "verdict": self.verdict,
            "ref": self.ref,
            "recordedAt": self.recorded_at,
        }


@dataclass(frozen=True)
class VerdictStore:
    """The append-only verdict ledger, and the keys the last measured sweep found open."""

    ledger_path: Path
    pending_path: Path

    def rulings(self) -> dict[str, Ruling]:
        """Every ruling so far, keyed by issue. A damaged line is skipped, not fatal."""
        rulings: dict[str, Ruling] = {}
        try:
            text = self.ledger_path.read_text(encoding="utf-8")
        except OSError:
            return rulings
        for line in text.splitlines():
            ruling = _ruling_from_line(line)
            if ruling is not None:
                rulings[ruling.key] = ruling
        return rulings

    def append(self, ruling: Ruling) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(ruling.to_dict(), sort_keys=True) + "\n")

    def pending(self) -> frozenset[str] | None:
        try:
            raw = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or not isinstance(raw.get("open"), list):
            return None
        return frozenset(str(key) for key in raw["open"])

    def save_pending(self, keys: Iterable[str]) -> None:
        """Replace the snapshot. Only ever called after a fully measured sweep."""
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"open": sorted(keys)}
        self.pending_path.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")


def _ruling_from_line(line: str) -> Ruling | None:
    if not line.strip():
        return None
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not payload.get("key"):
        return None
    return Ruling(
        key=str(payload["key"]),
        verdict=str(payload.get("verdict", "")),
        ref=str(payload.get("ref", "")),
        recorded_at=str(payload.get("recordedAt", "")),
    )


# --- refs -----------------------------------------------------------------------


def _by_id(targets: Iterable[Target]) -> dict[str, Target]:
    return {t.id: t for t in targets}


def _repo_ref(text: str, targets: dict[str, Target]) -> tuple[Target, int]:
    """``<repo>#<n>`` for a dispatch-target ``repo``, or :class:`VerdictError`."""
    match = _REPO_REF.match(text.strip())
    if match is None or match["repo"] not in targets:
        known = ", ".join(sorted(targets))
        raise VerdictError(f"{text!r} is not <repo>#<n> for a dispatch target ({known})")
    return targets[match["repo"]], int(match["number"])


def _read(call: Callable[[], object]) -> object:
    try:
        return call()
    except SourceUnavailableError as exc:
        raise CiRedUnreadable(str(exc)) from exc


# --- sweep --------------------------------------------------------------------------


@dataclass(frozen=True)
class Queued:
    """An open ci-red issue awaiting a verdict; ``reason`` says why an earlier one lapsed."""

    issue: CiRedIssue
    reason: str


@dataclass(frozen=True)
class Tracked:
    """An open ci-red issue whose filed/known ruling still holds."""

    issue: CiRedIssue
    ruling: Ruling


@dataclass(frozen=True)
class SweepResult:
    readings: tuple[RepoReading, ...]
    queue: tuple[Queued, ...]
    tracked: tuple[Tracked, ...]

    @property
    def open_count(self) -> int:
        return sum(len(r.issues) for r in self.readings)


def _lapse_reason(ruling: Ruling, source: CiRedSource, targets: dict[str, Target]) -> str:
    """Why ``ruling`` no longer holds the issue out of the queue, or ``""`` if it does."""
    if ruling.verdict in CLOSING_VERDICTS:
        return f"ruled {ruling.verdict} → {ruling.ref}, yet the issue is open"
    if ruling.verdict not in TRACKING_VERDICTS:
        return f"unknown verdict {ruling.verdict!r} in the ledger"
    try:
        target, number = _repo_ref(ruling.ref, targets)
    except VerdictError:
        return f"ruled {ruling.verdict} with an unreadable ref {ruling.ref!r}"
    state = _read(lambda: source.issue_state(target.full_name, number))
    if state == STATE_OPEN:
        return ""
    return f"ruled {ruling.verdict} → {ruling.ref}, and {ruling.ref} is {state}"


def sweep(
    readings: tuple[RepoReading, ...],
    store: VerdictStore,
    source: CiRedSource,
    targets: Iterable[Target],
) -> SweepResult:
    """Split every open ci-red issue into those awaiting a verdict and those tracked."""
    by_id = _by_id(targets)
    rulings = store.rulings()
    queue: list[Queued] = []
    tracked: list[Tracked] = []
    for issue in (i for r in readings for i in r.issues):
        ruling = rulings.get(issue.key)
        reason = _lapse_reason(ruling, source, by_id) if ruling else ""
        if ruling is None or reason:
            queue.append(Queued(issue, reason))
        else:
            tracked.append(Tracked(issue, ruling))
    return SweepResult(readings, tuple(queue), tuple(tracked))


# --- record -------------------------------------------------------------------------


def _verify_fixed(ref: str, source: CiRedSource, targets: dict[str, Target]) -> str:
    target, number = _repo_ref(ref, targets)
    state = _read(lambda: source.pr_state(target.full_name, number))
    if state != "MERGED":
        raise VerdictError(f"{ref} is {state}, not MERGED — an unlanded fix fixes nothing")
    return f"{target.id}#{number}"


def _verify_unmerged(ref: str, issue: CiRedIssue, target: Target, source: CiRedSource) -> str:
    match = _PR_REF.match(ref.strip())
    if match is None or match["repo"] not in (None, target.id):
        raise VerdictError(f"{ref!r} is not a PR in {target.id}")
    number = int(match["number"])
    if issue.red_pr != number:
        raise VerdictError(f"{issue.key} names PR #{issue.red_pr}, not #{number}")
    state = _read(lambda: source.pr_state(target.full_name, number))
    if state != "CLOSED":
        raise VerdictError(f"{target.id} PR #{number} is {state}, not CLOSED without merging")
    return f"{target.id}#{number}"


def _verify_green(ref: str, issue: CiRedIssue, target: Target, source: CiRedSource) -> str:
    if not _RUN_REF.match(ref.strip()):
        raise VerdictError(f"{ref!r} is not a run id")
    if issue.tested_sha is None or issue.red_run is None:
        raise VerdictError(f"{issue.key} reports no tested commit and run to compare against")
    run_id = int(ref.strip())
    run = _read(lambda: source.run_info(target.full_name, run_id))
    red = _read(lambda: source.run_info(target.full_name, issue.red_run))
    if run.conclusion != "success":
        raise VerdictError(f"run {run_id} concluded {run.conclusion!r}, not success")
    if run.head_sha != issue.tested_sha:
        raise VerdictError(f"run {run_id} tested {run.head_sha}, not {issue.tested_sha}")
    if run.workflow_id != red.workflow_id:
        raise VerdictError(f"run {run_id} is another workflow than red run {issue.red_run}")
    return str(run_id)


def _verify_tracking(ref: str, source: CiRedSource, targets: dict[str, Target]) -> str:
    target, number = _repo_ref(ref, targets)
    state = _read(lambda: source.issue_state(target.full_name, number))
    if state != STATE_OPEN:
        raise VerdictError(f"{ref} is {state}; a ruling on a closed issue lapses at once")
    return f"{target.id}#{number}"


def _open_issue(
    key: str, targets: dict[str, Target], source: CiRedSource
) -> tuple[Target, CiRedIssue]:
    target, number = _repo_ref(key, targets)
    raw = _read(lambda: source.issue(target.full_name, number))
    if raw.state != STATE_OPEN or CI_RED not in raw.labels:
        raise VerdictError(f"{key} is not an open ci-red issue")
    return target, ci_red_issue(target.id, raw)


def _close_comment(verdict: str, ref: str) -> str:
    what = {
        VERDICT_FIXED: f"the fix {ref} is merged",
        VERDICT_UNMERGED: f"the red PR {ref} closed without merging",
        VERDICT_GREEN: f"run {ref} of the same workflow is green on the tested commit",
    }[verdict]
    return f"Closed by `scripts/ci_red.py record` ({verdict}): {what}."


def record(
    store: VerdictStore,
    source: CiRedSource,
    targets: Iterable[Target],
    key: str,
    verdict: str,
    ref: str,
    when: datetime,
) -> Ruling:
    """Verify ``ref``, close the issue for a closing verdict, then append the ruling."""
    if verdict not in VERDICTS:
        raise VerdictError(f"unknown verdict {verdict!r} — expected one of {', '.join(VERDICTS)}")
    pending = store.pending()
    if pending is None:
        raise VerdictError("no measured sweep on record — run `ci_red.py sweep` first")
    if key not in pending:
        raise VerdictError(
            f"{key} was not open in the last sweep; open: {', '.join(sorted(pending)) or 'none'}"
        )
    by_id = _by_id(targets)
    target, issue = _open_issue(key, by_id, source)
    if verdict == VERDICT_FIXED:
        verified = _verify_fixed(ref, source, by_id)
    elif verdict == VERDICT_UNMERGED:
        verified = _verify_unmerged(ref, issue, target, source)
    elif verdict == VERDICT_GREEN:
        verified = _verify_green(ref, issue, target, source)
    else:
        verified = _verify_tracking(ref, source, by_id)
    if verdict in CLOSING_VERDICTS:
        comment = _close_comment(verdict, verified)
        _read(lambda: source.close(target.full_name, issue.number, comment))
    ruling = Ruling(key, verdict, verified, when.isoformat())
    store.append(ruling)
    return ruling

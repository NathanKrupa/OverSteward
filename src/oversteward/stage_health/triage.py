# ABOUTME: MIDDLE service for /stage-health — reads the `dq health --json` document, keeps the verdict ledger.
# ABOUTME: Every RED row is fixed, filed or known; an unruled or lapsed row is back in the queue next run.

"""The stage-health sweep (OS#536).

GrantSpider's ``grantspider dq health --json`` measures whether each pipeline
stage is still doing its work and emits RED/YELLOW findings. It exists because
GS#2075 cut snapshot fetches by an order of magnitude for weeks and nothing
alerted: the nightly DQ snapshot measured presence, and nobody read it. This
module is the reader, so something does.

**The document is a contract, read strictly.** Schema 1 is the only version
understood; any other value — including ``true``, which Python would otherwise
compare equal to ``1`` — is "could not read", never a best guess. The document's
``status``, its ``exit_code`` and the process's own exit code must all agree,
because the exit code is what the sweep hands back unchanged: ``0`` measured,
``1`` unreadable, ``2`` no ledger rows in the window. A click usage error also
exits 2 but prints no document, and must never pass for "the asset is not
running".

**Verdicts, in the sentry-triage shape.** A RED row is keyed ``rule@stage``
(``rule`` alone when the finding names no stage) and takes one of three
verdicts. There is no "later".

- ``fixed`` holds for the ledger day it was recorded against. The next day's
  measurement is what proves the fix, so a row still RED on a later ledger day
  is back in the queue, carrying the earlier ruling as its reason.
- ``filed`` and ``known`` point at an issue and hold only while that issue is
  open. When it closes — or never existed — the row is back in the queue.
  An issue whose state cannot be read fails the sweep: a tracked row that
  could not be checked must not print as tracked.

There are no LLM calls here. It decides what is *unruled*, never the fix.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .sources import STATE_MISSING

#: The only ``--json`` document version this reader understands.
REPORT_SCHEMA = 1

STATUS_MEASURED = "measured"
STATUS_UNREADABLE = "unreadable"
STATUS_NO_ROWS = "no_rows"
#: Each status and the one exit code the producer pairs it with.
STATUS_EXIT: Mapping[str, int] = {STATUS_MEASURED: 0, STATUS_UNREADABLE: 1, STATUS_NO_ROWS: 2}

RED = "RED"

VERDICT_FIXED = "fixed"
VERDICT_FILED = "filed"
VERDICT_KNOWN = "known"
#: All terminal. There is no "later" — "later" is how a queue stops draining.
VERDICTS: tuple[str, ...] = (VERDICT_FIXED, VERDICT_FILED, VERDICT_KNOWN)
#: Verdicts that point at an issue and hold only while it is open.
TRACKING_VERDICTS = frozenset({VERDICT_FILED, VERDICT_KNOWN})

STATE_OPEN = "open"
STATE_CLOSED = "closed"

#: Issue-ref prefixes and the repositories they name.
REF_REPOS: Mapping[str, str] = {
    "GS": "NathanKrupa/grantspider",
    "OS": "NathanKrupa/OverSteward",
    "AG": "NathanKrupa/aigranthelper",
}
_REF = re.compile(r"^(?P<prefix>[A-Z]+)#(?P<number>[1-9][0-9]*)$")

#: ``(repo, number) -> "open" | "closed" | "missing"``.
IssueStates = Callable[[str, int], str]


class StageHealthUnreadable(RuntimeError):
    """The producer's output cannot be trusted as a measurement."""


class VerdictError(ValueError):
    """A verdict cannot be recorded as asked."""


# --- the document ---------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    stage: str | None
    message: str

    @property
    def key(self) -> str:
        """The row's identity in the verdict ledger: ``rule@stage``, or ``rule``."""
        return f"{self.rule}@{self.stage}" if self.stage else self.rule


@dataclass(frozen=True)
class MetricRow:
    """One line of the per-stage table: a metric's value on the window's last day."""

    stage: str
    metric: str
    latest: float | None


@dataclass(frozen=True)
class HealthDocument:
    """The parts of the schema-1 document the sweep reads."""

    status: str
    exit_code: int
    first_day: str
    last_day: str
    window_days: int
    latest_day: str | None
    stage_count: int
    day_count: int
    verdict: str | None
    findings: tuple[Finding, ...]
    not_evaluated_count: int
    metrics: tuple[MetricRow, ...]
    canaries_configured: bool
    canaries_expected: int | None
    canaries_evaluated: int | None
    canaries_failed: int | None
    error: str | None

    @property
    def reds(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == RED)


def _expect(value: Any, kinds: tuple[type, ...], where: str) -> Any:
    """``value``, refused unless it is one of ``kinds`` (``bool`` is not an int)."""
    if (isinstance(value, bool) and bool not in kinds) or not isinstance(value, kinds):
        raise StageHealthUnreadable(f"{where}: expected {kinds}, got {value!r}")
    return value


def _field(mapping: Any, key: str, kinds: tuple[type, ...], where: str) -> Any:
    """``mapping[key]``, refused unless present and of one of ``kinds``."""
    if not isinstance(mapping, dict) or key not in mapping:
        raise StageHealthUnreadable(f"{where}: no {key!r}")
    return _expect(mapping[key], kinds, f"{where}.{key}")


def _optional_field(mapping: dict, key: str, kinds: tuple[type, ...], where: str) -> Any:
    """``mapping[key]`` of one of ``kinds`` when present, else ``None``.

    For keys added to schema 1 after the fact: GrantSpider PR #2834 added ``canaries.expected``
    and ``canaries.failed``, and a producer older than it omits them. Present,
    they are read as strictly as any other field.
    """
    if key not in mapping:
        return None
    return _expect(mapping[key], kinds, f"{where}.{key}")


def _check_schema(doc: Any) -> None:
    schema = doc.get("schema") if isinstance(doc, dict) else None
    if type(schema) is not int or schema != REPORT_SCHEMA:
        raise StageHealthUnreadable(
            f"schema {schema!r} is not {REPORT_SCHEMA}; this sweep reads schema "
            f"{REPORT_SCHEMA} only"
        )


def _check_exit(doc: dict, returncode: int) -> tuple[str, int]:
    status = _field(doc, "status", (str,), "document")
    if status not in STATUS_EXIT:
        raise StageHealthUnreadable(f"unknown status {status!r}")
    exit_code = _field(doc, "exit_code", (int,), "document")
    if exit_code != STATUS_EXIT[status]:
        raise StageHealthUnreadable(f"status {status!r} carries exit_code {exit_code}")
    if exit_code != returncode:
        raise StageHealthUnreadable(
            f"the document says exit {exit_code}, the process exited {returncode}"
        )
    return status, exit_code


def _finding(raw: Any, index: int) -> Finding:
    where = f"findings[{index}]"
    return Finding(
        severity=_field(raw, "severity", (str,), where),
        rule=_field(raw, "rule", (str,), where),
        stage=_field(raw, "stage", (str, type(None)), where),
        message=_field(raw, "message", (str,), where),
    )


def _metrics(stages: dict) -> tuple[MetricRow, ...]:
    rows: list[MetricRow] = []
    for stage, metrics in stages.items():
        for metric, series in _expect(metrics, (dict,), f"stages.{stage}").items():
            points = _expect(series, (list,), f"stages.{stage}.{metric}")
            last = points[-1] if points else {}
            value = last.get("value") if isinstance(last, dict) else None
            numeric = isinstance(value, int | float) and not isinstance(value, bool)
            rows.append(MetricRow(stage, metric, value if numeric else None))
    return tuple(rows)


def parse_document(stdout: str, returncode: int) -> HealthDocument:
    """The producer's stdout as a :class:`HealthDocument`, or :class:`StageHealthUnreadable`."""
    try:
        doc = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise StageHealthUnreadable(
            f"the producer printed no JSON document (exit {returncode})"
        ) from exc
    _check_schema(doc)
    status, exit_code = _check_exit(doc, returncode)
    window = _field(doc, "window", (dict,), "document")
    counts = _field(doc, "counts", (dict,), "document")
    canaries = _field(doc, "canaries", (dict,), "document")
    findings = _field(doc, "findings", (list,), "document")
    return HealthDocument(
        status=status,
        exit_code=exit_code,
        first_day=_field(window, "first_day", (str,), "window"),
        last_day=_field(window, "last_day", (str,), "window"),
        window_days=_field(window, "days", (int,), "window"),
        latest_day=_field(doc, "latest_day", (str, type(None)), "document"),
        stage_count=_field(counts, "stages", (int,), "counts"),
        day_count=_field(counts, "days", (int,), "counts"),
        verdict=_field(doc, "verdict", (str, type(None)), "document"),
        findings=tuple(_finding(raw, index) for index, raw in enumerate(findings)),
        not_evaluated_count=len(_field(doc, "not_evaluated", (list,), "document")),
        metrics=_metrics(_field(doc, "stages", (dict,), "document")),
        canaries_configured=_field(canaries, "configured", (bool,), "canaries"),
        canaries_expected=_optional_field(canaries, "expected", (int, type(None)), "canaries"),
        canaries_evaluated=_field(canaries, "evaluated", (int, type(None)), "canaries"),
        canaries_failed=_optional_field(canaries, "failed", (int, type(None)), "canaries"),
        error=_field(doc, "error", (str, type(None)), "document"),
    )


# --- issue refs -------------------------------------------------------------------


@dataclass(frozen=True)
class IssueRef:
    prefix: str
    number: int

    @property
    def repo(self) -> str:
        return REF_REPOS[self.prefix]

    def __str__(self) -> str:
        return f"{self.prefix}#{self.number}"


def parse_ref(text: str) -> IssueRef:
    """``GS#2805`` and its kin, or :class:`VerdictError`."""
    match = _REF.match(text.strip())
    if match is None or match["prefix"] not in REF_REPOS:
        known = ", ".join(f"{prefix}#<n>" for prefix in REF_REPOS)
        raise VerdictError(f"{text!r} is not an issue ref — expected one of {known}")
    return IssueRef(match["prefix"], int(match["number"]))


# --- the verdict ledger ---------------------------------------------------------


@dataclass(frozen=True)
class Ruling:
    """One recorded verdict. Keyed by ``key``; a later line supersedes an earlier one."""

    key: str
    verdict: str
    ref: str
    ledger_day: str
    recorded_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "verdict": self.verdict,
            "ref": self.ref,
            "ledgerDay": self.ledger_day,
            "recordedAt": self.recorded_at,
        }


@dataclass(frozen=True)
class Pending:
    """The last measured sweep's RED keys, and the ledger day they were measured on."""

    latest_day: str
    reds: frozenset[str]


@dataclass(frozen=True)
class VerdictStore:
    """The append-only verdict ledger, and the last measured sweep's RED rows.

    The pending snapshot is what lets ``record`` run with no producer call: it
    names the RED rows a verdict may be recorded for and the ledger day a
    ruling is stamped with.
    """

    ledger_path: Path
    pending_path: Path

    def rulings(self) -> dict[str, Ruling]:
        """Every ruling so far, keyed by row. A damaged line is skipped, not fatal."""
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

    def pending(self) -> Pending | None:
        try:
            raw = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict) or not isinstance(raw.get("latestDay"), str):
            return None
        return Pending(raw["latestDay"], frozenset(str(key) for key in raw.get("reds") or ()))

    def save_pending(self, document: HealthDocument) -> None:
        """Replace the snapshot. Only ever called with a measured document."""
        payload = {"latestDay": document.latest_day, "reds": [f.key for f in document.reds]}
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
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
        ledger_day=str(payload.get("ledgerDay", "")),
        recorded_at=str(payload.get("recordedAt", "")),
    )


# --- sweep and record -------------------------------------------------------------


@dataclass(frozen=True)
class Queued:
    """A RED row awaiting a verdict; ``reason`` says why an earlier ruling no longer holds."""

    finding: Finding
    reason: str


@dataclass(frozen=True)
class Tracked:
    """A RED row whose ruling still holds."""

    finding: Finding
    ruling: Ruling


@dataclass(frozen=True)
class SweepResult:
    document: HealthDocument
    queue: tuple[Queued, ...]
    tracked: tuple[Tracked, ...]


def _lapse_reason(ruling: Ruling, latest_day: str | None, issue_states: IssueStates) -> str:
    """Why ``ruling`` no longer holds, or ``""`` if it still does."""
    if ruling.verdict == VERDICT_FIXED:
        if ruling.ledger_day == latest_day:
            return ""
        return f"ruled fixed on ledger day {ruling.ledger_day}; still RED on {latest_day}"
    if ruling.verdict not in TRACKING_VERDICTS:
        return f"unknown verdict {ruling.verdict!r} in the ledger"
    try:
        ref = parse_ref(ruling.ref)
    except VerdictError:
        return f"ruled {ruling.verdict} with an unreadable ref {ruling.ref!r}"
    state = issue_states(ref.repo, ref.number)
    if state == STATE_OPEN:
        return ""
    if state == STATE_CLOSED:
        return f"ruled {ruling.verdict} → {ref}, and {ref} is closed"
    if state == STATE_MISSING:
        return f"ruled {ruling.verdict} → {ref}, and {ref} does not exist"
    raise StageHealthUnreadable(f"{ref}: unexpected issue state {state!r}")


def sweep(
    document: HealthDocument, store: VerdictStore, issue_states: IssueStates
) -> SweepResult:
    """Split the document's RED rows into those awaiting a verdict and those ruled on."""
    rulings = store.rulings()
    queue: list[Queued] = []
    tracked: list[Tracked] = []
    for finding in document.reds:
        ruling = rulings.get(finding.key)
        if ruling is None:
            queue.append(Queued(finding, ""))
            continue
        reason = _lapse_reason(ruling, document.latest_day, issue_states)
        if reason:
            queue.append(Queued(finding, reason))
        else:
            tracked.append(Tracked(finding, ruling))
    return SweepResult(document, tuple(queue), tuple(tracked))


def record(store: VerdictStore, key: str, verdict: str, ref: str, when: datetime) -> Ruling:
    """Rule on one RED row from the last measured sweep. The clock is a parameter."""
    if verdict not in VERDICTS:
        raise VerdictError(f"unknown verdict {verdict!r} — expected one of {', '.join(VERDICTS)}")
    pending = store.pending()
    if pending is None:
        raise VerdictError("no measured sweep on record — run `stage_health.py sweep` first")
    if key not in pending.reds:
        raise VerdictError(
            f"{key} is not a RED row in the last sweep (ledger day {pending.latest_day}); "
            f"RED rows: {', '.join(sorted(pending.reds)) or 'none'}"
        )
    if verdict in TRACKING_VERDICTS:
        ref = str(parse_ref(ref))
    ruling = Ruling(key, verdict, ref, pending.latest_day, when.isoformat())
    store.append(ruling)
    return ruling

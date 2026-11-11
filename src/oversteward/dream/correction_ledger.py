# ABOUTME: The correction pass's append-only ledger: an `opened` row, one row per verdict, and a closing row
# ABOUTME: every run writes. It is the re-check clock the worklist reads and the record the probe reports.

"""The correction ledger (OS#691).

One JSON object per line, beside the cycle's other per-machine ledgers in
``data/dream/``. Three row shapes, each carrying the ``run`` it belongs to:

- ``opened`` ``{run, at}`` — written before any verdict is weighed;
- ``verdict`` ``{run, filename, verdict, basis | searched | reason}`` — one per
  verdict the pass accepted;
- ``closed`` ``{run, at, checked, confirmed, unverified, conflicts, corrected,
  superseded, skipped, error}`` — written by every run, zero included, so a
  pass that never ran cannot read as a quiet one.

A verdict counts for the re-check clock only once its run has a ``closed`` row.
``at`` is an ISO datetime carrying the writer's UTC offset, and the clock reads
the calendar day it names. An absent file is a pass that never ran; a line that
does not parse raises :class:`LedgerUnreadable`, never a skip.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "CLOSED",
    "FILENAME",
    "OPENED",
    "STALE_AFTER_DAYS",
    "VERDICT",
    "CorrectionLedger",
    "LedgerUnreadable",
    "Probe",
    "new_run_id",
    "stamp",
]

FILENAME = "corrections.jsonl"
OPENED = "opened"
VERDICT = "verdict"
CLOSED = "closed"
_EVENTS = frozenset({OPENED, VERDICT, CLOSED})

#: A pass whose last closing row is older than this many days reads as stale.
#: The planner's choice, not a measured /dream cadence.
STALE_AFTER_DAYS = 7


class LedgerUnreadable(RuntimeError):
    """The ledger exists but a line in it could not be read. The message names the file and line."""


def new_run_id() -> str:
    """A fresh run identifier."""
    return uuid.uuid4().hex[:12]


def stamp(now: datetime) -> str:
    """``now`` as the ledger writes ``at``: ISO seconds with the local UTC offset."""
    return now.astimezone().isoformat(timespec="seconds")


@dataclass(frozen=True)
class Probe:
    """Whether the pass has run lately: its last closing row, and runs opened but never closed."""

    last_closed: dict[str, Any] | None
    days_since: int | None
    unclosed: int
    stale: bool

    @property
    def never_run(self) -> bool:
        return self.last_closed is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "never_run": self.never_run,
            "stale": self.stale,
            "last_closed": self.last_closed,
            "days_since": self.days_since,
            "unclosed": self.unclosed,
        }


class CorrectionLedger:
    """The append-only correction ledger at ``path``."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def append(self, rows: Sequence[dict[str, Any]]) -> None:
        """Append ``rows`` in a single write, so a closing row never lands without its verdicts."""
        text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    def rows(self) -> list[dict[str, Any]]:
        """Every row in file order. Raises :class:`LedgerUnreadable` on a malformed line."""
        if not self._path.exists():
            return []
        try:
            text = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise LedgerUnreadable(f"{self._path}: {exc}") from exc
        rows = []
        for number, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                rows.append(self._parse(line, number))
        return rows

    def last_checked(self) -> dict[str, date]:
        """Each note's latest verdict day, counting only runs that closed."""
        rows = self.rows()
        closed_on = {row["run"]: _day(row["at"]) for row in rows if row["event"] == CLOSED}
        checked: dict[str, date] = {}
        for row in rows:
            day = closed_on.get(row["run"])
            if row["event"] != VERDICT or day is None:
                continue
            filename = row["filename"]
            if filename not in checked or day > checked[filename]:
                checked[filename] = day
        return checked

    def probe(self, *, today: date) -> Probe:
        """The last closing row, its age in days, and how many opened runs never closed."""
        rows = self.rows()
        closed = [row for row in rows if row["event"] == CLOSED]
        closed_runs = {row["run"] for row in closed}
        unclosed = len({row["run"] for row in rows if row["event"] == OPENED} - closed_runs)
        if not closed:
            return Probe(last_closed=None, days_since=None, unclosed=unclosed, stale=True)
        last = closed[-1]
        days_since = (today - _day(last["at"])).days
        return Probe(
            last_closed=last,
            days_since=days_since,
            unclosed=unclosed,
            stale=days_since > STALE_AFTER_DAYS,
        )

    def _parse(self, line: str, number: int) -> dict[str, Any]:
        where = f"{self._path}:{number}"
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise LedgerUnreadable(f"{where}: not JSON ({exc})") from exc
        if not isinstance(row, dict) or row.get("event") not in _EVENTS:
            raise LedgerUnreadable(f"{where}: not a ledger row")
        if not isinstance(row.get("run"), str):
            raise LedgerUnreadable(f"{where}: row has no run")
        if row["event"] == VERDICT and not isinstance(row.get("filename"), str):
            raise LedgerUnreadable(f"{where}: verdict row has no filename")
        if row["event"] == CLOSED:
            try:
                _day(row.get("at"))
            except (TypeError, ValueError) as exc:
                raise LedgerUnreadable(f"{where}: closing row has no readable `at`") from exc
        return row


def _day(at: Any) -> date:
    """The calendar day an ``at`` stamp names, in the offset it was written with."""
    return datetime.fromisoformat(at).date()

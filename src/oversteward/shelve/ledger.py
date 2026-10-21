# ABOUTME: INNER store for the abandoned-work sweep — one JSON line per action, dry-run or applied.
# ABOUTME: Shapes and serialises lines only; the outer script owns the file, at a path it is given.

"""The action ledger: what the sweep did, or would have done, and when.

Every action the sweep decides is one line, written whether or not it was
performed. ``mode`` is ``dry`` for a dry run and ``applied`` for a write that
completed; a reader must never render a ``dry`` line as something that
happened. An applied line is written only after its write returned, so a run
that dies part-way leaves a ledger that claims no more than was done.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime

MODE_DRY = "dry"
MODE_APPLIED = "applied"


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    at: datetime
    mode: str
    repo: str
    kind: str
    number: int | None
    ref: str | None
    title: str
    url: str
    rule: str
    action: str
    idle_days: int | None
    reason: str

    def to_json(self) -> str:
        row = asdict(self)
        row["at"] = self.at.isoformat()
        return json.dumps(row, ensure_ascii=False, sort_keys=True)


def to_lines(entries: Sequence[LedgerEntry]) -> str:
    """The ledger text for ``entries``: one JSON object per line, newline-terminated."""
    return "".join(entry.to_json() + "\n" for entry in entries)


__all__ = ["MODE_APPLIED", "MODE_DRY", "LedgerEntry", "to_lines"]

# ABOUTME: INNER store for the abandoned-work sweep — one JSON line per action, dry-run or applied.
# ABOUTME: Shapes and serialises lines only; the outer script owns the file, at a path it is given.

"""The action ledger: what the sweep did, or would have done, and when.

Every action the sweep decides is one line. ``mode`` is the run's: ``dry`` for
a dry run, ``applied`` for an apply. A reader must never render a ``dry`` line
as something that happened. In an applied run a line is written only after its
write returned, so a run that dies part-way claims no more than was done; a
write ``gh`` did not complete is written with ``action`` ``failed`` and the
attempted verb in ``reason``. Each completed run ends with one ``sweep-run``
line, whose ``reason`` counts its actions and failures.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

MODE_DRY = "dry"
MODE_APPLIED = "applied"

#: The only directory a ledger may live in; the sweep writes it and the Estate Brief reads it.
STATE_DIR = Path.home() / ".local" / "state" / "oversteward"
#: Where the nightly units keep the ledger; either side may be given another path inside STATE_DIR.
LEDGER_ENV = "SHELVE_LEDGER_PATH"


def confine(requested: Path, base: Path) -> Path:
    """``requested`` resolved, refused with ``ValueError`` unless it lies inside ``base``."""
    resolved = Path(requested).expanduser().resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ValueError(f"ledger {resolved} is outside the state directory {base}")
    return resolved


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

    @classmethod
    def from_json(cls, line: str) -> LedgerEntry:
        row = json.loads(line)
        row["at"] = datetime.fromisoformat(row["at"])
        return cls(**row)


def to_lines(entries: Sequence[LedgerEntry]) -> str:
    """The ledger text for ``entries``: one JSON object per line, newline-terminated."""
    return "".join(entry.to_json() + "\n" for entry in entries)


def parse(text: str) -> tuple[LedgerEntry, ...]:
    """Every entry in ledger ``text``. A line that does not parse is an error, never skipped."""
    entries = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entries.append(LedgerEntry.from_json(line))
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"ledger line {number} does not parse: {exc}") from exc
    return tuple(entries)


__all__ = [
    "LEDGER_ENV",
    "MODE_APPLIED",
    "MODE_DRY",
    "STATE_DIR",
    "LedgerEntry",
    "confine",
    "parse",
    "to_lines",
]

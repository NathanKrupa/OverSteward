# ABOUTME: The correction pass's verdicts that never edit a note: confirmed, unverified, conflict.
# ABOUTME: Checks each against the worksheet row it was judged from, then writes the ledger and any CONFLICT hold.

"""Applying the correction pass's verdicts (OS#691).

The judge reads a :mod:`~oversteward.dream.correction` worksheet and returns one
verdict per note, keyed by filename. This module checks each verdict against the
row it was judged from and records it. No verdict here edits a note:

- ``confirmed`` needs a ``basis``: one or more paths the row reports
  ``tracked``. An issue state is never a basis, because a closed issue says
  nothing about whether the note is still true. When the row also holds an
  ``untracked`` path or a ``missing`` issue, the verdict needs a ``reason``.
- ``unverified`` needs ``searched``, what the judge looked for. It is counted
  apart from ``confirmed``, because the engine cannot check a judge's search.
- ``conflict`` needs a ``reason``. It becomes one hold in the cycle's durable
  open set (:class:`~oversteward.dream.cycle.FlaggedStore`), keyed on the note,
  so a repeat collapses onto it; ``MEMORY_REVIEW.md`` is rebuilt from the whole
  open set and committed alone in the store repo.

A verdict on a filename the worksheet does not hold, outside that vocabulary
(``corrected`` and ``superseded`` included), missing what its kind needs, or a
second verdict for one note is *refused*. A note whose bytes changed since the
worksheet hashed them is *stale*. Neither gets a ledger row. Every run writes an
``opened`` row first, and its accepted verdicts and its closing row together, in
a ``finally``, so a run that fails still closes.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .consolidate import CommitResult, FlaggedItem, MemoryFile, MemoryParseError, MemoryStore
from .correction_ledger import CLOSED, OPENED, VERDICT, CorrectionLedger, stamp
from .cycle import SKIP_CI_MARKER, FlaggedStore
from .extract import VALID_TYPES, CandidateFact

__all__ = [
    "CONFIRMED",
    "CONFLICT",
    "UNVERIFIED",
    "VOCABULARY",
    "ApplyContext",
    "ApplyResult",
    "ApplyUnreadable",
    "CommitFailed",
    "CorrectionVerdict",
    "apply_corrections",
    "close_aborted",
    "parse_verdicts",
    "parse_worksheet",
]

CONFIRMED = "confirmed"
UNVERIFIED = "unverified"
CONFLICT = "conflict"
VOCABULARY = (CONFIRMED, UNVERIFIED, CONFLICT)

_TRACKED = "tracked"
_CONTRARY_PATH = "untracked"
_CONTRARY_ISSUE = "missing"

# A conflict hold is a CandidateFact so the open set and the review surface take
# it unchanged. The proposal is the judge's, hence claude-inferred; a note with no
# valid metadata.type is held under one fixed type, so its key stays stable.
_HOLD_PROVENANCE = "claude-inferred"
_HOLD_CONFIDENCE = "medium"
_HOLD_FALLBACK_TYPE = "project"
_CONFLICT_PREFIX = "CONFLICT: "

#: ``(paths, message) -> CommitResult``: commits exactly ``paths`` in the store repo.
Commit = Callable[[list[Path], str], CommitResult]


class ApplyUnreadable(RuntimeError):
    """The worksheet, the verdicts or a note could not be read. The message names which."""


class CommitFailed(RuntimeError):
    """The store commit of the rebuilt review surface failed."""


@dataclass(frozen=True)
class CorrectionVerdict:
    """One judged note."""

    filename: str
    verdict: str
    basis: tuple[str, ...] = ()
    reason: str = ""
    searched: tuple[str, ...] = ()
    proposal: str = ""


@dataclass(frozen=True)
class ApplyContext:
    """Where a pass reads and writes, and the run it records."""

    store: MemoryStore
    ledger: CorrectionLedger
    flagged: FlaggedStore
    commit: Commit
    run: str
    now: datetime


@dataclass
class ApplyResult:
    """The closing row, each refusal with its reason, the stale notes, and any commit."""

    closed: dict[str, Any]
    refused: list[dict[str, str]] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    commit: CommitResult | None = None

    def to_dict(self) -> dict[str, Any]:
        commit = None
        if self.commit is not None:
            commit = {"committed": self.commit.committed, "message": self.commit.message,
                      "paths": self.commit.paths}
        return {"closed": self.closed, "refused": self.refused, "stale": self.stale,
                "commit": commit}


@dataclass
class _Weighed:
    accepted: list[tuple[CorrectionVerdict, bytes]] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    unjudged: int = 0


# ---- input --------------------------------------------------------------------


def parse_worksheet(payload: Any) -> list[dict[str, Any]]:
    """The worklist rows of a ``correction worklist`` document. Raises :class:`ApplyUnreadable`."""
    rows = payload.get("worklist") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ApplyUnreadable("worksheet has no `worklist` list")
    for index, row in enumerate(rows):
        if not _well_formed_row(row):
            raise ApplyUnreadable(f"worksheet row {index} lacks a filename, content_sha256 or references")
    return rows


def _well_formed_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    filename = row.get("filename")
    refs = row.get("references")
    return (
        isinstance(filename, str)
        and filename == Path(filename).name
        and isinstance(row.get("content_sha256"), str)
        and isinstance(refs, dict)
        and isinstance(refs.get("paths"), list)
        and isinstance(refs.get("issues"), list)
    )


def parse_verdicts(payload: Any) -> list[CorrectionVerdict]:
    """The judge's verdicts file: a JSON list of objects. Raises :class:`ApplyUnreadable`."""
    if not isinstance(payload, list):
        raise ApplyUnreadable("verdicts file is not a JSON list")
    return [_verdict(index, item) for index, item in enumerate(payload)]


def _verdict(index: int, item: Any) -> CorrectionVerdict:
    where = f"verdict {index}"
    if not isinstance(item, dict):
        raise ApplyUnreadable(f"{where} is not an object")
    texts = {key: item.get(key) or "" for key in ("filename", "verdict", "reason", "proposal")}
    lists = {key: item.get(key) or [] for key in ("basis", "searched")}
    if not all(isinstance(value, str) for value in texts.values()):
        raise ApplyUnreadable(f"{where}: filename, verdict, reason and proposal must be strings")
    if not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in lists.values()):
        raise ApplyUnreadable(f"{where}: basis and searched must be lists of strings")
    return CorrectionVerdict(
        filename=texts["filename"],
        verdict=texts["verdict"],
        basis=tuple(lists["basis"]),
        reason=texts["reason"].strip(),
        searched=tuple(lists["searched"]),
        proposal=texts["proposal"],
    )


# ---- the pass -----------------------------------------------------------------


def apply_corrections(
    ctx: ApplyContext, rows: Sequence[Mapping[str, Any]], verdicts: Sequence[CorrectionVerdict]
) -> ApplyResult:
    """Record each verdict that passes its guards; hold and surface each conflict.

    Raises :class:`CommitFailed` when the review-surface commit fails, and
    :class:`ApplyUnreadable` when a note cannot be read; the closing row is
    written either way, carrying the error.
    """
    ctx.ledger.append([{"event": OPENED, "run": ctx.run, "at": stamp(ctx.now)}])
    ledgered: list[dict[str, Any]] = []
    weighed = _Weighed()
    commit: CommitResult | None = None
    error: str | None = None
    try:
        weighed = _weigh(ctx.store, {row["filename"]: row for row in rows}, verdicts)
        plain = [v for v, _ in weighed.accepted if v.verdict != CONFLICT]
        ledgered.extend(_verdict_row(ctx.run, v) for v in plain)
        conflicts = [(v, text) for v, text in weighed.accepted if v.verdict == CONFLICT]
        if conflicts:
            open_set = ctx.flagged.merge([_hold(v, text) for v, text in conflicts])
            ledgered.extend(_verdict_row(ctx.run, v) for v, _ in conflicts)
            commit = _commit(ctx, ctx.store.write_review_surface(open_set), len(conflicts))
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        closed = _closed_row(ctx, ledgered, weighed, error)
        ctx.ledger.append([*ledgered, closed])
    return ApplyResult(closed=closed, refused=weighed.refused, stale=weighed.stale, commit=commit)


def close_aborted(ledger: CorrectionLedger, *, run: str, now: datetime, reason: str) -> dict[str, Any]:
    """Open and close a run that judged nothing, naming why. Returns the closing row."""
    at = stamp(now)
    closed = {**_counts(at, run, [], _Weighed()), "error": None, "aborted": reason}
    ledger.append([{"event": OPENED, "run": run, "at": at}, closed])
    return closed


def _weigh(
    store: MemoryStore, rows: Mapping[str, Mapping[str, Any]], verdicts: Sequence[CorrectionVerdict]
) -> _Weighed:
    weighed = _Weighed(unjudged=len(set(rows) - {v.filename for v in verdicts}))
    seen: set[str] = set()
    for verdict in verdicts:
        why = _refusal(verdict, rows.get(verdict.filename), seen)
        seen.add(verdict.filename)
        if why:
            weighed.refused.append({"filename": verdict.filename, "why": why})
            continue
        current = _note_bytes(store, verdict.filename)
        expected = rows[verdict.filename]["content_sha256"]
        if current is None or hashlib.sha256(current).hexdigest() != expected:
            weighed.stale.append(verdict.filename)
            continue
        weighed.accepted.append((verdict, current))
    return weighed


def _refusal(verdict: CorrectionVerdict, row: Mapping[str, Any] | None, seen: set[str]) -> str:
    """Why ``verdict`` cannot be recorded, or "" when it can."""
    if row is None:
        return "not on the worksheet"
    if verdict.filename in seen:
        return "duplicate verdict for this note"
    if verdict.verdict not in VOCABULARY:
        return f"unknown verdict {verdict.verdict!r}; this pass takes {', '.join(VOCABULARY)}"
    if verdict.verdict == CONFIRMED:
        return _confirmed_refusal(verdict, row["references"])
    if verdict.verdict == UNVERIFIED and not verdict.searched:
        return "unverified needs searched: what the judge looked for"
    if verdict.verdict == CONFLICT and not verdict.reason:
        return "conflict needs a reason"
    return ""


def _confirmed_refusal(verdict: CorrectionVerdict, refs: Mapping[str, Any]) -> str:
    if not verdict.basis:
        return "confirmed needs a basis: a path the worksheet row reports tracked"
    tracked = {p.get("path") for p in refs["paths"] if p.get("status") == _TRACKED}
    for path in verdict.basis:
        if path not in tracked:
            return f"basis {path} is not a tracked path on the worksheet row"
    contrary = any(p.get("status") == _CONTRARY_PATH for p in refs["paths"]) or any(
        i.get("state") == _CONTRARY_ISSUE for i in refs["issues"]
    )
    if contrary and not verdict.reason:
        return "confirmed over an untracked path or a missing issue needs a reason"
    return ""


def _note_bytes(store: MemoryStore, filename: str) -> bytes | None:
    """The note's bytes now, or None when it is gone."""
    try:
        return (store.root / filename).read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ApplyUnreadable(f"{filename} could not be read: {exc}") from exc


def _hold(verdict: CorrectionVerdict, current: bytes) -> FlaggedItem:
    """A conflict as an open-set hold, keyed on the note: its own type, description and filename."""
    try:
        note = MemoryFile.parse(current.decode("utf-8"), verdict.filename)
    except (UnicodeDecodeError, MemoryParseError) as exc:
        raise ApplyUnreadable(f"{verdict.filename} could not be parsed: {exc}") from exc
    note_type = note.metadata.get("type")
    candidate = CandidateFact(
        type=note_type if note_type in VALID_TYPES else _HOLD_FALLBACK_TYPE,
        description=note.description,
        body=verdict.proposal,
        provenance=_HOLD_PROVENANCE,
        confidence=_HOLD_CONFIDENCE,
        is_procedural=False,
    )
    return FlaggedItem(candidate=candidate, reason=_CONFLICT_PREFIX + verdict.reason,
                       similarity=1.0, nearest=note)


def _commit(ctx: ApplyContext, review_path: Path, conflicts: int) -> CommitResult:
    message = f"dream: correction pass surfaced {conflicts} conflict(s) {SKIP_CI_MARKER}"
    try:
        return ctx.commit([review_path], message)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise CommitFailed(f"correction commit failed: {type(exc).__name__}: {exc}") from exc


# ---- ledger rows --------------------------------------------------------------


def _verdict_row(run: str, verdict: CorrectionVerdict) -> dict[str, Any]:
    row: dict[str, Any] = {"event": VERDICT, "run": run, "filename": verdict.filename,
                           "verdict": verdict.verdict}
    if verdict.basis:
        row["basis"] = list(verdict.basis)
    if verdict.searched:
        row["searched"] = list(verdict.searched)
    if verdict.reason:
        row["reason"] = verdict.reason
    return row


def _counts(at: str, run: str, ledgered: list[dict[str, Any]], weighed: _Weighed) -> dict[str, Any]:
    tally = Counter(row["verdict"] for row in ledgered)
    return {
        "event": CLOSED,
        "run": run,
        "at": at,
        "checked": len(ledgered),
        "confirmed": tally[CONFIRMED],
        "unverified": tally[UNVERIFIED],
        "conflicts": tally[CONFLICT],
        "corrected": 0,
        "superseded": 0,
        "skipped": {
            "stale": len(weighed.stale),
            "refused": len(weighed.refused),
            "unjudged": weighed.unjudged,
        },
    }


def _closed_row(
    ctx: ApplyContext, ledgered: list[dict[str, Any]], weighed: _Weighed, error: str | None
) -> dict[str, Any]:
    return {**_counts(stamp(ctx.now), ctx.run, ledgered, weighed), "error": error}

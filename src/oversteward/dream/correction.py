# ABOUTME: The correction pass's read-only worklist: the Laws and Habits least recently reinforced,
# ABOUTME: each with deterministic evidence about the paths and issues its code spans name. Writes nothing.

"""The correction worklist (OS#691, PR 1 of 2).

The dream cycle writes and consolidates notes but never re-checks one, so a Law
whose subject has gone keeps loading as live law. This module builds the list a
correction pass works from; it issues no verdicts and writes nothing.

- **Population.** Notes :func:`~oversteward.dream.standing.classify` files as a
  Law or a Habit.
- **Ranking.** Oldest first by ``last_reinforced``, else ``created``. A note
  with neither field, or an unparseable one, is *undated*: it ranks first and is
  counted. Age only ranks the list; it never retires a note.
- **Due and offered.** A note is due when it is undated or at least
  ``min_age_days`` old; the first ``limit`` due notes are offered.
- **Evidence.** Read for offered notes only, from the inline code spans of the
  description, the digest and the body (fenced blocks are not inline spans).
  A path-like token is looked up in every registry checkout through a
  :class:`TreeLookup`; an absolute, ``~``-rooted or ``*``-bearing one is
  ``unchecked``. An ``OS#``/``GS#``/``AG#`` ref is looked up through an
  injected issue-state callable; any other prefix is ``unchecked``. A span
  yielding neither is ``named``, unverified.

Anything that cannot be read raises :class:`WorklistUnreadable`: an absent or
empty store, a note that does not parse, a tree or issue read that fails, and
the canary — this module's own path must read as tracked in the home repo, or
the tree reader is blind and every ``untracked`` would be a false finding.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from oversteward.estate_map.checkouts import Checkout, CouldNotLook, checkouts
from oversteward.estate_map.status import mentioned_paths
from oversteward.stage_health.sources import IssueStateUnavailableError
from oversteward.stage_health.triage import REF_REPOS

from .consolidate import MemoryFile, MemoryParseError, MemoryStore
from .standing import HABIT, LAW, classify
from .store_health import unfenced_lines

__all__ = [
    "CANARY_PATH",
    "DEFAULT_LIMIT",
    "DEFAULT_MIN_AGE_DAYS",
    "HOME_REPO",
    "IssueStates",
    "Sources",
    "TreeLookup",
    "Worklist",
    "WorklistUnreadable",
    "build_worklist",
    "tree_checkouts",
]

# Nathan's defaults (OS#691 Q3): ten notes per run, re-checked no sooner than 30 days.
DEFAULT_LIMIT = 10
DEFAULT_MIN_AGE_DAYS = 30

#: The registry id of the repo this module ships in, and the path the canary asks for there.
HOME_REPO = "oversteward"
CANARY_PATH = "src/oversteward/dream/correction.py"

TRACKED = "tracked"
UNTRACKED = "untracked"
ISSUE_STATES = frozenset({"open", "closed", "missing"})

#: ``(owner/repo, number) -> "open" | "closed" | "missing"``.
IssueStates = Callable[[str, int], str]

_POPULATION = (LAW, HABIT)
_DATE_FIELDS = ("last_reinforced", "created")
_DIGEST = "digest"
_CODE_SPAN_RE = re.compile(r"(`+)(.+?)\1")
_ISSUE_REF_RE = re.compile(r"(?<![\w#])([A-Z]+)#([1-9][0-9]*)\b")


class WorklistUnreadable(RuntimeError):
    """The worklist could not be measured. The message names what could not be read."""


class TreeLookup(Protocol):
    """The tree reader's one call this module makes (:class:`~oversteward.estate_map.checkouts.TreeReader`)."""

    def existing(self, repo: str, paths: Sequence[str]) -> set[str]: ...


@dataclass(frozen=True)
class Sources:
    """Where evidence is read: the trees of ``repos`` and the issue-state callable."""

    trees: TreeLookup
    repos: tuple[str, ...]
    issue_states: IssueStates


@dataclass(frozen=True)
class _Spans:
    """One note's code-span references, before any lookup."""

    paths: tuple[str, ...]
    issues: tuple[tuple[str, int], ...]
    unchecked: tuple[str, ...]
    named: tuple[str, ...]


@dataclass(frozen=True)
class _Candidate:
    memory: MemoryFile
    kind: str
    effective: date | None


@dataclass(frozen=True)
class Worklist:
    """The counts and the offered rows, each row already in its JSON form."""

    counts: Mapping[str, int]
    rows: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"counts": dict(self.counts), "worklist": list(self.rows)}


def build_worklist(
    store: MemoryStore,
    sources: Sources,
    *,
    today: date,
    min_age_days: int = DEFAULT_MIN_AGE_DAYS,
    limit: int = DEFAULT_LIMIT,
) -> Worklist:
    """The Laws and Habits due for a re-check, oldest first, with their evidence.

    Reads the store and, for the offered notes only, the trees and issue states
    in ``sources``. Writes nothing. Raises :class:`WorklistUnreadable` on any
    failure to read, and when the canary does not come back tracked.
    """
    population = _ranked(_population(store))
    due = [c for c in population if c.effective is None or (today - c.effective).days >= min_age_days]
    offered = due[:limit]
    spans = {c.memory.filename: _spans(c.memory) for c in offered}
    tracked_in = _tracked_in(sources, sorted({p for s in spans.values() for p in s.paths}))
    states = _issue_states(sources.issue_states, sorted({i for s in spans.values() for i in s.issues}))
    rows = tuple(
        _row(store.root, c, spans[c.memory.filename], tracked_in, states) for c in offered
    )
    counts = {
        "standing": len(population),
        "due": len(due),
        "offered": len(offered),
        "undated": sum(1 for c in population if c.effective is None),
    }
    return Worklist(counts, rows)


def tree_checkouts(registry: Mapping[str, Any], *, home_root: Path) -> dict[str, Checkout]:
    """:func:`~oversteward.estate_map.checkouts.checkouts` for the contexts that give a local_path."""
    local = {
        str(ctx.get("id")) for ctx in registry.get("contexts") or [] if ctx.get("local_path")
    }
    found = checkouts(registry, home_repo=HOME_REPO, home_root=home_root)
    return {repo: checkout for repo, checkout in found.items() if repo in local}


# ---- population and ranking ---------------------------------------------------


def _population(store: MemoryStore) -> list[_Candidate]:
    if not store.root.is_dir():
        raise WorklistUnreadable(f"store root is not a directory: {store.root}")
    try:
        memories = store.memories()
    except (MemoryParseError, UnicodeDecodeError, OSError) as exc:
        raise WorklistUnreadable(f"a note could not be read: {exc}") from exc
    if not memories:
        raise WorklistUnreadable(f"store holds no fact notes: {store.root}")
    candidates = []
    for memory in memories:
        kind = classify(memory).kind
        if kind in _POPULATION:
            candidates.append(_Candidate(memory, kind, _effective_date(memory.metadata)))
    return candidates


def _ranked(candidates: list[_Candidate]) -> list[_Candidate]:
    """Undated first, then oldest date first; ties on filename."""
    return sorted(
        candidates,
        key=lambda c: (c.effective is not None, c.effective or date.min, c.memory.filename),
    )


def _effective_date(metadata: Mapping[str, Any]) -> date | None:
    """The first of ``last_reinforced``/``created`` present, as a date; None when absent or unparseable."""
    for field in _DATE_FIELDS:
        if metadata.get(field) is not None:
            return _as_date(metadata[field])
    return None


def _as_date(value: Any) -> date | None:
    """A YAML date, a datetime, or an ISO string (date or datetime) as a date; else None."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for parse in (date.fromisoformat, lambda t: datetime.fromisoformat(t).date()):
        try:
            return parse(text)
        except ValueError:
            continue
    return None


# ---- evidence -----------------------------------------------------------------


def _spans(memory: MemoryFile) -> _Spans:
    paths: list[str] = []
    issues: list[tuple[str, int]] = []
    unchecked: list[str] = []
    named: list[str] = []
    for span in _code_spans(memory):
        found = _read_span(span)
        _extend_unique(paths, found.paths)
        _extend_unique(issues, found.issues)
        _extend_unique(unchecked, found.unchecked)
        if not (found.paths or found.issues or found.unchecked):
            _extend_unique(named, (span,))
    return _Spans(tuple(paths), tuple(issues), tuple(unchecked), tuple(named))


def _code_spans(memory: MemoryFile) -> list[str]:
    digest = memory.metadata.get(_DIGEST)
    texts = [memory.description, digest if isinstance(digest, str) else "", memory.body]
    return [
        match.group(2).strip()
        for text in texts
        for line in unfenced_lines(text)
        for match in _CODE_SPAN_RE.finditer(line)
        if match.group(2).strip()
    ]


def _read_span(span: str) -> _Spans:
    issues: list[tuple[str, int]] = []
    unchecked: list[str] = []
    for prefix, number in _ISSUE_REF_RE.findall(span):
        if prefix in REF_REPOS:
            issues.append((prefix, int(number)))
        else:
            unchecked.append(f"{prefix}#{number}")
    paths: list[str] = []
    for token in span.split():
        if "://" in token or not mentioned_paths(token):
            continue
        if token.startswith(("/", "~")) or "*" in token:
            unchecked.append(token)
        else:
            paths.extend(mentioned_paths(token))
    return _Spans(tuple(paths), tuple(issues), tuple(unchecked), ())


def _extend_unique(into: list, items) -> None:
    for item in items:
        if item not in into:
            into.append(item)


def _tracked_in(sources: Sources, paths: list[str]) -> dict[str, list[str]]:
    """Each path's repos, read from every repo's tree; the canary rides the home repo's call."""
    if HOME_REPO not in sources.repos:
        raise WorklistUnreadable(f"instrument blind: {HOME_REPO} is not among the trees read")
    found: dict[str, list[str]] = {path: [] for path in paths}
    for repo in sources.repos:
        wanted = [*paths, CANARY_PATH] if repo == HOME_REPO else paths
        if not wanted:
            continue
        try:
            present = sources.trees.existing(repo, wanted)
        except CouldNotLook as exc:
            raise WorklistUnreadable(str(exc)) from exc
        if repo == HOME_REPO and CANARY_PATH not in present:
            raise WorklistUnreadable(f"instrument blind: {CANARY_PATH} did not read as tracked in {HOME_REPO}")
        for path in paths:
            if path in present:
                found[path].append(repo)
    return found


def _issue_states(read: IssueStates, refs: list[tuple[str, int]]) -> dict[tuple[str, int], str]:
    states: dict[tuple[str, int], str] = {}
    for prefix, number in refs:
        try:
            state = read(REF_REPOS[prefix], number)
        except IssueStateUnavailableError as exc:
            raise WorklistUnreadable(str(exc)) from exc
        if state not in ISSUE_STATES:
            raise WorklistUnreadable(f"{prefix}#{number}: unrecognised issue state {state!r}")
        states[(prefix, number)] = state
    return states


def _row(
    root: Path,
    candidate: _Candidate,
    spans: _Spans,
    tracked_in: Mapping[str, list[str]],
    states: Mapping[tuple[str, int], str],
) -> dict[str, Any]:
    memory = candidate.memory
    return {
        "filename": memory.filename,
        "kind": candidate.kind,
        "provenance": memory.provenance(),
        "effective_date": candidate.effective.isoformat() if candidate.effective else None,
        "undated": candidate.effective is None,
        "description": memory.description,
        "content_sha256": _sha256(root / memory.filename),
        "references": {
            "paths": [
                {
                    "path": path,
                    "status": TRACKED if tracked_in[path] else UNTRACKED,
                    "repos": list(tracked_in[path]),
                }
                for path in spans.paths
            ],
            "issues": [
                {"ref": f"{prefix}#{number}", "state": states[(prefix, number)]}
                for prefix, number in spans.issues
            ],
            "unchecked": list(spans.unchecked),
            "named": list(spans.named),
        },
    }


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise WorklistUnreadable(f"{path.name} could not be read: {exc}") from exc

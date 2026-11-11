# ABOUTME: The dream store's health report — the dangling [[link]] queue, oldest first, and store size
# ABOUTME: against a ceiling. Reads the store and one git log; no LLM, no note classification, no writes.

"""Store health: what the dream run reports at its close (OS#692).

Two measurements, both read-only:

- **The dangling-link queue.** Every ``[[target]]`` in a fact note's body that
  names no note — neither a filename stem nor a ``name:`` — listed with the notes
  citing it and the date the oldest of them was first committed, oldest first.
  A dangling link is often deliberate ("something worth writing later"), so it is
  a queue the run works, not a failure.
- **Store size against a ceiling.** Fact-note count, ``MEMORY_FULL.md`` bytes and
  the total bytes of the top-level ``*.md`` files, each compared with a ceiling.
  Over a ceiling is a reported finding.

:func:`measure` takes the add dates as a map so it never touches git;
:func:`assess` composes it with :func:`~oversteward.dream.consolidate.first_added_dates`.
Anything unreadable raises :class:`StoreUnreadable` rather than reporting an
empty, clean-looking store.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .consolidate import (
    FULL_INDEX_FILENAME,
    MemoryFile,
    MemoryParseError,
    MemoryStore,
    StoreUnreadable,
    first_added_dates,
)

__all__ = [
    "DEFAULT_CEILINGS",
    "DEFAULT_QUEUE_LIMIT",
    "Ceilings",
    "DanglingLink",
    "StoreHealth",
    "StoreSizes",
    "StoreUnreadable",
    "assess",
    "measure",
    "resolvable_names",
    "unfenced_lines",
]

# How many of the oldest dangling targets one dream run rules on (Nathan, OS#692).
DEFAULT_QUEUE_LIMIT = 10

_KB = 1_000
_MD_SUFFIX = ".md"

# A wiki link's target, and the two Markdown code forms a link inside is not a link.
_LINK_RE = re.compile(r"\[\[([^\[\]]*)\]\]")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_CODE_SPAN_RE = re.compile(r"(`+).+?\1")


@dataclass(frozen=True)
class Ceilings:
    """The store-size ceilings (Nathan, OS#692). A measure is over only when strictly greater."""

    notes: int = 3_500
    memory_full_bytes: int = 1_000_000
    total_bytes: int = 6_000_000


DEFAULT_CEILINGS = Ceilings()


@dataclass(frozen=True)
class DanglingLink:
    """One unresolved ``[[target]]``: who cites it and how long it has waited."""

    target: str
    citers: tuple[str, ...]
    added: date | None
    age_days: int

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "citers": list(self.citers),
            "added": self.added.isoformat() if self.added is not None else None,
            "age_days": self.age_days,
        }


@dataclass(frozen=True)
class StoreSizes:
    """The three size measures, named as :class:`Ceilings` names their limits."""

    notes: int
    memory_full_bytes: int
    total_bytes: int


@dataclass(frozen=True)
class StoreHealth:
    """One measurement of the store. ``ruled`` is None when no snapshot was given."""

    dangling: tuple[DanglingLink, ...]
    unique_targets: int
    sizes: StoreSizes
    ceilings: Ceilings
    over: tuple[str, ...]
    ruled: int | None

    def closing_line(self) -> str:
        """``N dangling (M ruled this run); store X notes / Y KB of Z KB ceiling[ — OVER …]``."""
        ruled = "ruled: unmeasured" if self.ruled is None else f"{self.ruled} ruled this run"
        line = (
            f"{len(self.dangling)} dangling ({ruled}); store {self.sizes.notes:,} notes / "
            f"{round(self.sizes.total_bytes / _KB):,} KB of "
            f"{round(self.ceilings.total_bytes / _KB):,} KB ceiling"
        )
        if not self.over:
            return line
        return f"{line} — OVER CEILING: " + "; ".join(self._overage(name) for name in self.over)

    def _overage(self, measure_name: str) -> str:
        label, unit = _MEASURE_LABELS[measure_name]
        value = getattr(self.sizes, measure_name)
        limit = getattr(self.ceilings, measure_name)
        return f"{label} {value:,}/{limit:,}{unit}"

    def to_dict(self, limit: int = DEFAULT_QUEUE_LIMIT) -> dict:
        """The JSON report: the closing line, counts, the oldest ``limit`` targets, sizes."""
        return {
            "closing_line": self.closing_line(),
            "dangling_total": len(self.dangling),
            "ruled": self.ruled,
            "unique_targets": self.unique_targets,
            "queue": [link.to_dict() for link in self.dangling[:limit]],
            "sizes": asdict(self.sizes),
            "ceilings": asdict(self.ceilings),
            "over": list(self.over),
        }


_MEASURE_LABELS = {
    "notes": ("notes", ""),
    "memory_full_bytes": (FULL_INDEX_FILENAME, " B"),
    "total_bytes": ("total", " B"),
}


def measure(
    store: MemoryStore,
    *,
    added_on: Mapping[str, date],
    today: date,
    ceilings: Ceilings = DEFAULT_CEILINGS,
    dangling_before: frozenset[str] | None = None,
) -> StoreHealth:
    """Measure ``store``: its dangling links, oldest first, and its size against ``ceilings``.

    ``added_on`` maps a note's filename to the date it was first committed; a note
    missing from it has age 0. ``dangling_before`` is the set of targets that
    dangled before this run ruled on them; ``ruled`` counts those that no longer
    do. Raises :class:`StoreUnreadable` when the root is not a directory or a note
    cannot be read or parsed.
    """
    memories = _fact_notes(store)
    resolvable = _resolvable(memories)
    citers_by_target = _citers_by_target(memories)
    dangling = _oldest_first(
        _dangling(target, citers, added_on, today)
        for target, citers in citers_by_target.items()
        if target not in resolvable
    )
    sizes = _sizes(store.root, len(memories))
    names = {link.target for link in dangling}
    return StoreHealth(
        dangling=tuple(dangling),
        unique_targets=len(citers_by_target),
        sizes=sizes,
        ceilings=ceilings,
        over=tuple(
            name for name in _MEASURE_LABELS if getattr(sizes, name) > getattr(ceilings, name)
        ),
        ruled=None if dangling_before is None else len(dangling_before - names),
    )


def assess(
    store: MemoryStore,
    repo_root: Path,
    *,
    today: date,
    ceilings: Ceilings = DEFAULT_CEILINGS,
    dangling_before: frozenset[str] | None = None,
) -> StoreHealth:
    """:func:`measure` the store, dating each note from the store repo's git history."""
    return measure(
        store,
        added_on=first_added_dates(repo_root, store.root),
        today=today,
        ceilings=ceilings,
        dangling_before=dangling_before,
    )


def resolvable_names(store: MemoryStore) -> frozenset[str]:
    """Every name a reference to a note in ``store`` resolves by: each filename stem and each ``name:``.

    Raises :class:`StoreUnreadable` when the root is not a directory or a note
    cannot be read or parsed.
    """
    return _resolvable(_fact_notes(store))


def _resolvable(memories: list[MemoryFile]) -> frozenset[str]:
    return frozenset({Path(mem.filename).stem for mem in memories} | {mem.name for mem in memories})


def _fact_notes(store: MemoryStore) -> list[MemoryFile]:
    if not store.root.is_dir():
        raise StoreUnreadable(f"store root is not a directory: {store.root}")
    try:
        return store.memories()
    except (MemoryParseError, UnicodeDecodeError, OSError) as exc:
        raise StoreUnreadable(f"a note could not be read: {exc}") from exc


def _oldest_first(links: Iterable[DanglingLink]) -> list[DanglingLink]:
    return sorted(links, key=lambda link: (-link.age_days, link.target))


def _citers_by_target(memories: list[MemoryFile]) -> dict[str, set[str]]:
    citers: dict[str, set[str]] = {}
    for mem in memories:
        for target in _link_targets(mem.body):
            citers.setdefault(target, set()).add(mem.filename)
    return citers


def _link_targets(body: str) -> set[str]:
    """The normalized ``[[targets]]`` in ``body``'s prose, outside fences and code spans."""
    targets: set[str] = set()
    for raw in _LINK_RE.findall(_prose(body)):
        target = raw.strip()
        if target.endswith(_MD_SUFFIX):
            target = target[: -len(_MD_SUFFIX)]
        if target:
            targets.add(target)
    return targets


def _prose(body: str) -> str:
    """``body`` with fenced blocks and inline code spans removed."""
    return "\n".join(_CODE_SPAN_RE.sub("", line) for line in unfenced_lines(body))


def unfenced_lines(body: str) -> Iterator[str]:
    """Each line of ``body`` outside a fenced code block; the fence lines themselves are dropped."""
    fence: str | None = None
    for line in body.splitlines():
        opener = _FENCE_RE.match(line)
        if fence is None and opener is not None:
            fence = opener.group(1)
            continue
        if fence is not None:
            if line.strip().startswith(fence[0] * len(fence)):
                fence = None
            continue
        yield line


def _dangling(
    target: str, citers: set[str], added_on: Mapping[str, date], today: date
) -> DanglingLink:
    dates = [added_on[name] for name in citers if name in added_on]
    added = min(dates) if dates else None
    return DanglingLink(
        target=target,
        citers=tuple(sorted(citers)),
        added=added,
        age_days=(today - added).days if added is not None else 0,
    )


def _sizes(root: Path, notes: int) -> StoreSizes:
    try:
        full = root / FULL_INDEX_FILENAME
        return StoreSizes(
            notes=notes,
            memory_full_bytes=full.stat().st_size if full.is_file() else 0,
            total_bytes=sum(path.stat().st_size for path in root.glob(f"*{_MD_SUFFIX}")),
        )
    except OSError as exc:
        raise StoreUnreadable(f"store size could not be read: {exc}") from exc

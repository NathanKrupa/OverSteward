# ABOUTME: The estate map's memory-cite check — every `memory` cite must name a note in the steward-memory store.
# ABOUTME: Resolves through dream.store_health's resolver (stem or `name:`); an unreadable store is could-not-look.

"""Memory cites: the map's citations of steward-memory notes (OS#695).

A row's ``cite`` is a ``;``-separated list of sources, each a source word
followed by backticked references — ``wphelper `src/wphelper/`; memory
`project_wphelper_is_connector_home```. Every backticked reference in a
segment whose source word is ``memory`` is a note slug. Invariants and seams
are the rows that carry a ``cite``.

A slug resolves when it is a note's filename stem or its ``name:``, by the same
resolver the dream run's dangling-link queue uses. One that resolves to nothing
is a finding naming the row. A store that cannot be read, or that lists no
notes at all, is could-not-look: an empty listing is what pathlib returns for a
directory it may not read, and it would otherwise report every cite as missing.
The store is read only when the map holds at least one memory cite.
"""

from __future__ import annotations

import re

from oversteward.dream.consolidate import MemoryStore, StoreUnreadable
from oversteward.dream.store_health import resolvable_names

from .model import EstateMap
from .outcome import Finding, Outcome

CHECK = "memory-cite"
_LABEL = "memory cites"
_SOURCE_RE = re.compile(r"\s*memory\b")
_REFERENCE_RE = re.compile(r"`([^`]+)`")


def memory_cites(estate: EstateMap) -> list[tuple[str, str]]:
    """Each ``(row id, slug)`` the map cites from memory, invariants first, in map order."""
    rows = [*estate.invariants, *estate.seams]
    return [(row.id, slug) for row in rows for slug in _slugs(row.cite)]


def check_memory_cites(estate: EstateMap, store: MemoryStore) -> Outcome:
    cites = memory_cites(estate)
    if not cites:
        return Outcome(notes=(f"{_LABEL}: none in the map",))
    try:
        names = resolvable_names(store)
    except StoreUnreadable as exc:
        return Outcome(could_not_look=(f"{_LABEL}: {exc}",))
    if not names:
        return Outcome(could_not_look=(f"{_LABEL}: store {store.root} holds no notes",))
    findings = tuple(
        Finding(CHECK, row, f"memory `{slug}` names no note in {store.root}")
        for row, slug in cites
        if slug not in names
    )
    note = f"{_LABEL}: {len(cites)} checked against {store.root}, {len(findings)} unresolved"
    return Outcome(findings, (), (note,))


def _slugs(cite: str) -> list[str]:
    return [
        slug.strip()
        for segment in cite.split(";")
        if _SOURCE_RE.match(segment)
        for slug in _REFERENCE_RE.findall(segment)
    ]

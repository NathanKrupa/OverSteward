# ABOUTME: The explicit supersede op — stamp metadata.superseded_by on a stored memory so it files under Graveyard.
# ABOUTME: One named memory, one operator-supplied replacement; never a scan, never keyword-derived.

"""Retiring one stored memory (OS#288).

``metadata.superseded_by`` is the ONLY route into the always-loaded Graveyard
(:mod:`oversteward.dream.standing`), and it is deliberately explicit — a keyword
scan over retirement vocabulary inflated the Graveyard the same way it inflated
Laws, so :func:`~oversteward.dream.standing.classify` never derives it.

The dream cycle sets the marker on the way in: the extractor emits
``superseded_by`` on a candidate that retires an approach, and both write paths
(append and auto-merge) persist it. That covers a fact the store learns about
while it is still being discussed. It cannot cover the opposite case — a rule
that was lifted long enough ago that no transcript raises it again, which is
precisely the state a dead law decays into. Such a fact goes quiet while still
loading as live law, and nothing in a normal cycle will ever revisit it.

This module is that second route: an operator names ONE memory and states what
supersedes it. It is a single explicit write, never a side effect of a run and
never a heuristic over the store — the judgment about whether a fact is dead
stays with the operator (or the model reading it), exactly where the memory
architecture puts classification judgment.
"""

from __future__ import annotations

from .consolidate import MemoryFile, MemoryStore

# The graveyard marker key (mirrors ``standing._SUPERSEDED_BY``; the two modules
# stay import-independent so nothing forms a consolidate <-> standing cycle).
SUPERSEDED_BY = "superseded_by"

_MARKDOWN_SUFFIX = ".md"


class SupersedeError(RuntimeError):
    """The supersede op could not be applied as asked."""


def supersede(store: MemoryStore, filename: str, replacement: str) -> MemoryFile:
    """Mark one stored memory superseded and write it back.

    ``filename`` is the memory's ``<slug>.md`` basename (a bare slug is accepted).
    ``replacement`` is what to reach for instead — a live successor, or a plain
    statement that the rule was lifted with nothing taking its place. It is
    required: a blank marker would file a corpse with no forwarding address, and
    the Graveyard entry renders the replacement as the reader's next step.

    Additive — every other frontmatter field (the audit trail included) survives.
    Raises :class:`SupersedeError` for an unknown memory or a blank replacement.
    The caller regenerates the index; this op writes exactly one file.
    """
    target = replacement.strip()
    if not target:
        raise SupersedeError("replacement must name what to reach for instead (it was blank)")
    memory = _find(store, filename)
    memory.metadata[SUPERSEDED_BY] = target
    store.write(memory)
    return memory


def _find(store: MemoryStore, filename: str) -> MemoryFile:
    """The stored memory with this basename, or a :class:`SupersedeError`."""
    wanted = filename if filename.endswith(_MARKDOWN_SUFFIX) else filename + _MARKDOWN_SUFFIX
    for memory in store.memories():
        if memory.filename == wanted:
            return memory
    raise SupersedeError(f"no such memory in {store.root}: {wanted}")

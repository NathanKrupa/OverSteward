# ABOUTME: Tests for the explicit supersede op — marking a stored memory retired via metadata.superseded_by.
# ABOUTME: Uses a TEMP memory store only — NEVER the live steward-memory repo or ~/.claude.

from __future__ import annotations

from pathlib import Path

import pytest

from oversteward.dream.consolidate import MemoryFile, MemoryStore
from oversteward.dream.standing import GRAVEYARD, LAW, classify
from oversteward.dream.supersede import SupersedeError, supersede


def _memory(name: str, description: str, **metadata: object) -> MemoryFile:
    base: dict[str, object] = {
        "type": "user",
        "provenance": "nathan-stated",
        "created": "2026-01-01",
        "last_reinforced": "2026-01-01",
        "confidence": "high",
        "decay_status": "active",
    }
    base.update(metadata)
    return MemoryFile(
        name=name,
        description=description,
        metadata=base,
        body="The rule this fact records.\n",
        filename=f"{name}.md",
    )


def _store_with(tmp_path: Path, *memories: MemoryFile) -> MemoryStore:
    store = MemoryStore(tmp_path / "memory")
    for mem in memories:
        store.write(mem)
    return store


def test_supersede_moves_a_live_law_into_the_graveyard(tmp_path: Path) -> None:
    # The whole point (OS#288): a `user` fact is a law outright, so a rule that
    # has since been lifted keeps loading as live law until it is marked retired.
    store = _store_with(tmp_path, _memory("user_x", "RETIRED 2026-07-11 — the hours boundary"))
    assert classify(store.memories()[0]).kind == LAW

    supersede(store, "user_x.md", "no successor — AG work is no longer clock-gated")

    reloaded = store.memories()[0]
    classification = classify(reloaded)
    assert classification.kind == GRAVEYARD
    assert classification.replacement == "no successor — AG work is no longer clock-gated"


def test_supersede_accepts_the_bare_slug(tmp_path: Path) -> None:
    store = _store_with(tmp_path, _memory("user_x", "a lifted hold"))
    memory = supersede(store, "user_x", "the hold is lifted")
    assert memory.filename == "user_x.md"
    assert store.memories()[0].metadata["superseded_by"] == "the hold is lifted"


def test_supersede_preserves_the_rest_of_the_frontmatter(tmp_path: Path) -> None:
    # Additive only — the audit trail (created/provenance/sessions) must survive.
    store = _store_with(tmp_path, _memory("user_x", "a lifted hold", source_sessions=["sess-a"]))
    supersede(store, "user_x.md", "the hold is lifted")
    metadata = store.memories()[0].metadata
    assert metadata["created"] == "2026-01-01"
    assert metadata["provenance"] == "nathan-stated"
    assert metadata["source_sessions"] == ["sess-a"]


def test_supersede_rejects_an_unknown_memory(tmp_path: Path) -> None:
    store = _store_with(tmp_path, _memory("user_x", "a rule"))
    with pytest.raises(SupersedeError, match="no such memory"):
        supersede(store, "user_absent.md", "the replacement")


def test_supersede_rejects_an_empty_replacement(tmp_path: Path) -> None:
    # The marker's job is to name what to reach for instead; a blank value would
    # file a corpse with no forwarding address.
    store = _store_with(tmp_path, _memory("user_x", "a rule"))
    with pytest.raises(SupersedeError, match="replacement"):
        supersede(store, "user_x.md", "   ")


def test_supersede_overwrites_an_earlier_marker(tmp_path: Path) -> None:
    store = _store_with(tmp_path, _memory("user_x", "a rule", superseded_by="the first successor"))
    supersede(store, "user_x.md", "the second successor")
    assert store.memories()[0].metadata["superseded_by"] == "the second successor"

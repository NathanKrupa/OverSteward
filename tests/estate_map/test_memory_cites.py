# ABOUTME: Tests for the estate map's memory-cite check — each `memory` cite must name a steward-memory note.
# ABOUTME: Temp stores only; a cite resolves by filename stem or `name:`, and an unreadable store is exit 2.

from __future__ import annotations

from pathlib import Path
from typing import Any

from oversteward.dream.consolidate import MemoryStore
from oversteward.estate_map.memory_cites import check_memory_cites, memory_cites
from oversteward.estate_map.model import parse
from oversteward.estate_map.outcome import EXIT_CLEAN, EXIT_COULD_NOT_LOOK, EXIT_FINDINGS


def _note(root: Path, filename: str, *, name: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / filename).write_text(f"---\nname: {name}\ndescription: d\n---\n\nBody.\n", encoding="utf-8")


def _invariant(raw: dict[str, Any], inv_id: str) -> dict[str, Any]:
    return next(i for i in raw["invariants"] if i["id"] == inv_id)


def _store(tmp_path: Path) -> MemoryStore:
    """A store holding one note whose stem and ``name:`` differ."""
    root = tmp_path / "memory"
    _note(root, "feedback_stem_only.md", name="name_only")
    return MemoryStore(root)


class TestCites:
    def test_reads_memory_cites_from_invariants_and_seams(self, raw):
        _invariant(raw, "I-1")["cite"] = "wphelper `src/wphelper/`; memory `a_note`"
        raw["seams"][0]["cite"] = "memory `b_note`, `c_note`"
        assert memory_cites(parse(raw)) == [("I-1", "a_note"), ("S-1", "b_note"), ("S-1", "c_note")]

    def test_a_backticked_path_outside_a_memory_segment_is_not_a_cite(self, raw):
        _invariant(raw, "I-1")["cite"] = "GS `services/memory.py:12`, `memory`"
        assert memory_cites(parse(raw)) == []


class TestResolution:
    def test_a_cite_naming_no_note_is_a_finding_naming_the_row(self, raw, tmp_path):
        _invariant(raw, "I-2")["cite"] = "memory `no_such_note`"
        outcome = check_memory_cites(parse(raw), _store(tmp_path))
        assert outcome.exit_code == EXIT_FINDINGS
        assert [(f.check, f.subject) for f in outcome.findings] == [("memory-cite", "I-2")]
        assert "no_such_note" in outcome.findings[0].message

    def test_a_cite_matching_only_a_name_field_resolves(self, raw, tmp_path):
        _invariant(raw, "I-2")["cite"] = "memory `name_only`"
        outcome = check_memory_cites(parse(raw), _store(tmp_path))
        assert outcome.exit_code == EXIT_CLEAN, outcome

    def test_a_cite_matching_only_a_filename_stem_resolves(self, raw, tmp_path):
        _invariant(raw, "I-2")["cite"] = "memory `feedback_stem_only`"
        outcome = check_memory_cites(parse(raw), _store(tmp_path))
        assert outcome.exit_code == EXIT_CLEAN, outcome

    def test_the_note_counts_the_cites_checked(self, raw, tmp_path):
        _invariant(raw, "I-1")["cite"] = "memory `name_only`"
        _invariant(raw, "I-2")["cite"] = "memory `no_such_note`"
        outcome = check_memory_cites(parse(raw), _store(tmp_path))
        assert outcome.notes == (f"memory cites: 2 checked against {tmp_path / 'memory'}, 1 unresolved",)


class TestCouldNotLook:
    def test_an_absent_store_root_is_could_not_look(self, raw, tmp_path):
        _invariant(raw, "I-2")["cite"] = "memory `name_only`"
        outcome = check_memory_cites(parse(raw), MemoryStore(tmp_path / "absent"))
        assert outcome.exit_code == EXIT_COULD_NOT_LOOK
        assert outcome.findings == ()
        assert "memory cites:" in outcome.could_not_look[0]
        assert "not a directory" in outcome.could_not_look[0]

    def test_a_store_holding_no_notes_is_could_not_look(self, raw, tmp_path):
        # A directory that lists empty (an unreadable one does, under pathlib's glob)
        # cannot resolve anything, so every cite would read as a finding it never measured.
        (tmp_path / "empty").mkdir()
        _invariant(raw, "I-2")["cite"] = "memory `name_only`"
        outcome = check_memory_cites(parse(raw), MemoryStore(tmp_path / "empty"))
        assert outcome.exit_code == EXIT_COULD_NOT_LOOK
        assert outcome.findings == ()
        assert "holds no notes" in outcome.could_not_look[0]

    def test_an_unparseable_note_is_could_not_look(self, raw, tmp_path):
        store = _store(tmp_path)
        (store.root / "broken.md").write_text("no frontmatter here\n", encoding="utf-8")
        _invariant(raw, "I-2")["cite"] = "memory `name_only`"
        outcome = check_memory_cites(parse(raw), store)
        assert outcome.exit_code == EXIT_COULD_NOT_LOOK
        assert "could not be read" in outcome.could_not_look[0]

    def test_a_map_with_no_memory_cites_never_reads_the_store(self, raw, tmp_path):
        outcome = check_memory_cites(parse(raw), MemoryStore(tmp_path / "absent"))
        assert outcome.exit_code == EXIT_CLEAN
        assert outcome.notes == ("memory cites: none in the map",)

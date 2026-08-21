# ABOUTME: Tests for the trajectory-note tag gate — vocabulary, scoping, exit codes, false-green guard.
# ABOUTME: The untagged fixture is the gate's negative proof: if it ever passes, the gate is dead.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from oversteward.trajectory_tags import (
    CATEGORIES,
    UnreadableNoteError,
    format_violation,
    iter_bullets,
    suggest_category,
    validate_note,
    validate_text,
)

FIXTURES = Path(__file__).parent / "fixtures"
TAGGED = FIXTURES / "trajectory-tagged-note.md"
UNTAGGED = FIXTURES / "trajectory-untagged-note.md"

NOTE = Path("note.md")
DIDNT = "What didn't"
UNTAGGED_BULLET = "## What worked\n\n- Something useful happened.\n"

NO_CAPTURE_SECTIONS = """\
# Trajectory — a note the parser cannot understand

## Context

The three capture sections are missing entirely.

## Notes

- Some bullet nobody can classify.
"""


def _reasons(text: str) -> list[str]:
    return [v.reason for v in validate_text(NOTE, text).violations]


# --- the compliant fixture --------------------------------------------------


class TestTaggedNote:
    def test_compliant_fixture_has_no_violations(self) -> None:
        report = validate_note(TAGGED)
        assert report.violations == ()
        assert report.ok

    def test_compliant_fixture_actually_checked_bullets(self) -> None:
        # A validator that silently parsed zero bullets would also report clean.
        report = validate_note(TAGGED)
        assert report.bullets_checked == 4
        assert len(report.sections_found) == 3


# --- the negative proof required by OS#327 rule 1 ---------------------------


class TestUntaggedFixture:
    def test_untagged_fixture_fails(self) -> None:
        assert not validate_note(UNTAGGED).ok

    def test_every_violation_class_is_caught(self) -> None:
        # 3 missing/unknown categories + 4 unroutable promote tags.
        assert len(validate_note(UNTAGGED).violations) == 7

    def test_compliant_bullets_in_the_fixture_are_not_flagged(self) -> None:
        flagged = {v.bullet for v in validate_note(UNTAGGED).violations}
        assert not any("must NOT be flagged" in bullet for bullet in flagged)

    def test_bullets_outside_capture_sections_are_not_judged(self) -> None:
        flagged = {v.section for v in validate_note(UNTAGGED).violations}
        assert flagged <= {"What worked", DIDNT, "What was learned"}


# --- the category vocabulary ------------------------------------------------


class TestCategoryVocabulary:
    def test_missing_category_is_flagged(self) -> None:
        text = UNTAGGED_BULLET
        assert _reasons(text) == ["missing leading `[category]` tag"]

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_every_vocabulary_value_is_accepted(self, category: str) -> None:
        text = f"## What worked\n\n- [{category}] Something useful happened.\n"
        assert _reasons(text) == []

    def test_off_vocabulary_category_is_flagged(self) -> None:
        text = "## What worked\n\n- [misc] Something useful happened.\n"
        assert _reasons(text) == ["unknown category `[misc]`"]

    def test_cost_tag_after_category_is_accepted(self) -> None:
        text = "## What didn't\n\n- [process][hours] It bit → remedy: none.\n"
        assert _reasons(text) == []

    def test_violation_names_the_allowed_vocabulary(self) -> None:
        text = UNTAGGED_BULLET
        assert validate_text(NOTE, text).violations[0].allowed == CATEGORIES


# --- the promote vocabulary -------------------------------------------------


class TestPromoteVocabulary:
    def test_promote_is_required_only_in_what_was_learned(self) -> None:
        assert _reasons("## What worked\n\n- [design] No promote tag here.\n") == []

    @pytest.mark.parametrize("target", ["doctrine", "memory", "lessons.jsonl", "none"])
    def test_every_target_is_accepted(self, target: str) -> None:
        text = f"## What was learned\n\n- [design] A rule → promote: {target}.\n"
        assert _reasons(text) == []

    def test_missing_promote_is_flagged(self) -> None:
        text = "## What was learned\n\n- [design] A rule with no routing.\n"
        assert _reasons(text) == ["missing trailing `→ promote:` tag"]

    def test_off_vocabulary_target_is_flagged(self) -> None:
        text = "## What was learned\n\n- [design] A rule → promote: someday.\n"
        assert "cannot read it" in _reasons(text)[0]

    def test_promote_tag_the_analyzer_cannot_reach_is_flagged(self) -> None:
        # The consumer's regex is end-anchored, so trailing prose hides the tag.
        # A gate with a looser pattern would pass a bullet that still routes nowhere.
        text = "## What was learned\n\n- [design] A rule → promote: memory, plus prose.\n"
        assert "cannot read it" in _reasons(text)[0]


# --- bullet parsing ---------------------------------------------------------


class TestBulletParsing:
    def test_wrapped_bullet_keeps_its_promote_tag_readable(self) -> None:
        text = (
            "## What was learned\n\n"
            "- [design] A rule that wrapped onto\n  a second line → promote: memory.\n"
        )
        assert _reasons(text) == []

    def test_fenced_code_is_not_read_as_bullets(self) -> None:
        assert list(iter_bullets("## What worked\n\n```\n- not a lesson bullet\n```\n")) == []

    def test_template_guidance_blockquote_is_skipped(self) -> None:
        assert list(iter_bullets("## What worked\n\n> - [category] example in guidance\n")) == []

    def test_section_closes_at_the_next_heading(self) -> None:
        text = "## What worked\n\n- [design] Fine.\n\n## Tools\n\n- `pytest` [used] — untagged.\n"
        assert [b.section for b in iter_bullets(text)] == ["What worked"]

    def test_cost_legend_in_the_heading_is_tolerated(self) -> None:
        text = "## What didn't  (cost: trivial | minutes)\n\n- [process][trivial] x → remedy: none.\n"
        assert [b.section for b in iter_bullets(text)] == [DIDNT]

    def test_typographic_apostrophe_heading_is_recognised(self) -> None:
        text = "## What didn’t\n\n- [process][trivial] x → remedy: none.\n"
        assert [b.section for b in iter_bullets(text)] == [DIDNT]


# --- "could not look" is never "found nothing" ------------------------------


class TestCouldNotLook:
    def test_note_without_capture_sections_raises(self, tmp_path: Path) -> None:
        note = tmp_path / "2026-08-21-PR1.md"
        note.write_text(NO_CAPTURE_SECTIONS, encoding="utf-8")
        with pytest.raises(UnreadableNoteError, match="capture sections"):
            validate_note(note)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(UnreadableNoteError, match="cannot be read"):
            validate_note(tmp_path / "absent.md")


# --- suggestions and rendering ----------------------------------------------


class TestSuggestions:
    def test_suggests_a_category_from_cheap_keywords(self) -> None:
        assert suggest_category("The pytest gaudi hook could not find the venv") == "tooling"

    def test_suggests_nothing_when_no_keyword_matches(self) -> None:
        assert suggest_category("Quiet week, nothing notable at all.") is None

    def test_suggestion_reaches_the_rendered_violation(self) -> None:
        text = "## What worked\n\n- The pre-commit hook resolved gaudi from the venv.\n"
        rendered = format_violation(validate_text(NOTE, text).violations[0])
        assert "suggest: [tooling]" in rendered


class TestRendering:
    def test_message_names_file_line_bullet_and_vocabulary(self) -> None:
        text = UNTAGGED_BULLET
        rendered = format_violation(validate_text(Path("notes/a.md"), text).violations[0])
        assert "notes/a.md:3" in rendered
        assert "Something useful happened." in rendered
        assert "design | functional | tooling | process | outcome" in rendered

    def test_long_bullets_are_truncated(self) -> None:
        text = f"## What worked\n\n- {'x' * 400}\n"
        rendered = format_violation(validate_text(Path("a.md"), text).violations[0])
        assert "..." in rendered
        assert len(rendered.splitlines()[1]) < 200


# --- the gate's three-valued exit-code contract -----------------------------


def _load_cli():
    script = Path(__file__).resolve().parents[1] / "scripts" / "lint" / "trajectory_tags.py"
    spec = importlib.util.spec_from_file_location("oversteward_trajectory_tags_cli", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _load_cli()


@pytest.fixture
def unparseable_note(tmp_path: Path) -> Path:
    note = tmp_path / "2026-08-21-PR1.md"
    note.write_text(NO_CAPTURE_SECTIONS, encoding="utf-8")
    return note


class TestGateExitCodes:
    def test_a_compliant_note_exits_zero(self, cli, capsys) -> None:
        assert cli.main([str(TAGGED)]) == 0
        assert "all tagged" in capsys.readouterr().out

    def test_a_clean_run_names_the_count_it_checked(self, cli, capsys) -> None:
        # "all 4 accounted for" is a measurement; "ok" is a claim.
        cli.main([str(TAGGED)])
        out = capsys.readouterr().out
        assert "1 note(s)" in out
        assert "4 lesson bullet(s)" in out

    def test_the_untagged_fixture_exits_one(self, cli) -> None:
        assert cli.main([str(UNTAGGED)]) == 1

    def test_violation_output_names_file_bullet_and_vocabulary(self, cli, capsys) -> None:
        cli.main([str(UNTAGGED)])
        err = capsys.readouterr().err
        assert "trajectory-untagged-note.md:" in err
        assert "No leading category tag at all" in err
        assert "design | functional | tooling | process | outcome" in err
        assert "doctrine | memory | lessons.jsonl | none" in err

    def test_an_unparseable_note_exits_two_not_zero(self, cli, capsys, unparseable_note) -> None:
        assert cli.main([str(unparseable_note)]) == 2
        assert "COULD NOT LOOK" in capsys.readouterr().err

    def test_a_missing_path_exits_two(self, cli, tmp_path) -> None:
        assert cli.main([str(tmp_path / "absent.md")]) == 2

    def test_could_not_look_outranks_violations(self, cli, unparseable_note) -> None:
        # A run that both found violations and failed to read a note reports the
        # blindness — the louder, less-recoverable fact.
        assert cli.main([str(UNTAGGED), str(unparseable_note)]) == 2

    def test_no_markdown_paths_is_a_no_op(self, cli) -> None:
        assert cli.main(["scripts/lint/trajectory_tags.py"]) == 0

    def test_a_mixed_run_fails_on_the_untagged_note(self, cli) -> None:
        assert cli.main([str(TAGGED), str(UNTAGGED)]) == 1

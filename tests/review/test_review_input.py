# ABOUTME: Tests for review_input — the deterministic assembly of the adversarial reviewer's inputs.
# ABOUTME: The author agent must not be able to curate what the reviewer sees, so assembly is code.

from __future__ import annotations

import pytest

from oversteward.review_input import (
    COULD_NOT_LOOK,
    DELETION_LIST_UNREADABLE,
    EXIT_COULD_NOT_LOOK,
    EXIT_OK,
    GAUDI_SECTION,
    PREVIOUS_VERDICT_SECTION,
    SECTION_ORDER,
    TEST_FILES_SECTION,
    AssembledInput,
    CouldNotLookError,
    RoundCapError,
    Section,
    assemble,
    derive_round,
    exit_code_for,
    is_test_path,
    ledger_line,
    render,
)


class _Collector:
    """A scripted stand-in for the git/gh/gaudi probes assembly depends on.

    Every probe is injected, so a test states exactly what the outside world
    answered — including "it refused", which is the case the gate exists for.
    """

    def __init__(
        self,
        *,
        diff: str | None = "diff --git a/x.py b/x.py\n",
        changed: list[str] | None = None,
        deleted: list[str] | None = (),
        issue: str | None = "the issue body",
        file_bodies: dict[str, str] | None = None,
        base_bodies: dict[str, str] | None = None,
        claude_md: str | None = "# CLAUDE.md\n",
        gaudi: str | None = '{"findings": []}',
    ) -> None:
        self._diff = diff
        self._changed = ["src/x.py", "tests/test_x.py"] if changed is None else changed
        # `deleted=None` is "the deletion list could not be read", which is a
        # different state from "nothing was deleted" and must stay expressible.
        self._deleted = None if deleted is None else list(deleted)
        self._issue = issue
        # An explicitly empty mapping means "no file is readable" — a real
        # case — so it must not fall through to the default body.
        self._file_bodies = (
            {"tests/test_x.py": "def test_x():\n    assert True\n"}
            if file_bodies is None
            else file_bodies
        )
        self._base_bodies = base_bodies or {}
        self._claude_md = claude_md
        self._gaudi = gaudi
        self.gaudi_calls: list[list[str]] = []
        self.diff_calls: list[str] = []
        self.changed_files_calls: list[str] = []
        self.deleted_files_calls: list[str] = []
        self.base_text_calls: list[str] = []

    def merge_base(self, base: str) -> str | None:
        return "f00dbase"

    def diff(self, base: str) -> str | None:
        self.diff_calls.append(base)
        return self._diff

    def changed_files(self, base: str) -> list[str] | None:
        self.changed_files_calls.append(base)
        return self._changed

    def deleted_files(self, base: str) -> list[str] | None:
        self.deleted_files_calls.append(base)
        return None if self._deleted is None else list(self._deleted)

    def issue_body(self, repo: str, number: int) -> str | None:
        return self._issue

    def file_text(self, relpath: str) -> str | None:
        return self._file_bodies.get(relpath)

    def file_text_at_base(self, base: str, relpath: str) -> str | None:
        self.base_text_calls.append(base)
        return self._base_bodies.get(relpath)

    def claude_md(self) -> str | None:
        return self._claude_md

    def gaudi_json(self, relpaths: list[str]) -> str | None:
        self.gaudi_calls.append(list(relpaths))
        return self._gaudi


def _assemble(**kwargs) -> AssembledInput:
    collector = kwargs.pop("collector", None) or _Collector()
    params = {"base": "origin/master", "repo": "NathanKrupa/OverSteward", "issue": 428}
    params.update(kwargs)
    return assemble(collector, **params)


class TestAssembleGathersEveryInput:
    def test_the_diff_issue_tests_doctrine_and_gaudi_report_are_all_present(self):
        result = _assemble()
        names = [section.name for section in result.sections]
        assert names == list(SECTION_ORDER)

    def test_every_section_is_measured_when_every_probe_answers(self):
        assert all(section.measured for section in _assemble().sections)
        assert exit_code_for(_assemble()) == EXIT_OK

    def test_changed_test_files_are_included_whole_not_as_diff_hunks(self):
        result = _assemble()
        tests_section = next(s for s in result.sections if s.name == "changed-test-files")
        assert "def test_x():" in tests_section.body

    def test_a_diff_touching_no_test_file_says_so_rather_than_going_silent(self):
        result = _assemble(collector=_Collector(changed=["src/x.py"]))
        tests_section = next(s for s in result.sections if s.name == "changed-test-files")
        assert tests_section.measured
        assert "no test files" in tests_section.body.lower()


#: The deleted module's test function, asserted on from several angles.
DELETED_TEST_NAME = "test_a_blocked_url_never_reaches_httpx"


def _deleting_collector(**overrides) -> _Collector:
    """A diff that deletes a test module — the GS `b14cb9b4` shape, and the flagship case.

    The deleted test is precisely the reviewable material: it is the thing that
    could have failed, and the diff removed it.
    """
    params = {
        "changed": ["src/safe_http.py", "tests/test_safe_http.py"],
        "deleted": ["tests/test_safe_http.py"],
        "file_bodies": {},
        "base_bodies": {
            "tests/test_safe_http.py": "def test_a_blocked_url_never_reaches_httpx():\n    ...\n"
        },
    }
    params.update(overrides)
    return _Collector(**params)


class TestADeletedFileIsReviewableNotUnmeasurable:
    def test_the_deleted_test_is_rendered_from_its_base_version(self):
        result = _assemble(collector=_deleting_collector())
        section = next(s for s in result.sections if s.name == "changed-test-files")
        assert DELETED_TEST_NAME in section.body

    def test_the_section_is_measured_because_the_content_was_actually_obtained(self):
        result = _assemble(collector=_deleting_collector())
        section = next(s for s in result.sections if s.name == "changed-test-files")
        assert section.measured

    def test_the_base_version_is_labelled_deleted_never_passed_off_as_current(self):
        result = _assemble(collector=_deleting_collector())
        section = next(s for s in result.sections if s.name == "changed-test-files")
        assert "DELETED BY THIS DIFF" in section.body

    def test_a_diff_that_deletes_a_test_assembles_a_fully_measured_input(self):
        result = _assemble(collector=_deleting_collector())
        assert result.unmeasured == ()
        assert exit_code_for(result) == EXIT_OK

    def test_the_deleted_content_survives_into_the_rendered_document(self):
        # The section body is only worth gathering if it reaches the reviewer;
        # a body discarded at render time is the same as never reading it.
        text = render(_assemble(collector=_deleting_collector()))
        assert DELETED_TEST_NAME in text
        assert COULD_NOT_LOOK not in text

    def test_gaudi_reads_the_files_that_still_exist_and_skips_the_deleted_one(self):
        collector = _deleting_collector()
        result = _assemble(collector=collector)
        assert collector.gaudi_calls == [["src/safe_http.py"]]
        section = next(s for s in result.sections if s.name == "gaudi-warn")
        assert section.measured

    def test_a_deleted_python_file_is_recorded_as_skipped_by_design(self):
        result = _assemble(collector=_deleting_collector())
        section = next(s for s in result.sections if s.name == "gaudi-warn")
        assert "tests/test_safe_http.py" in section.body
        assert "skipped" in section.body.lower()

    def test_a_diff_deleting_every_python_file_leaves_gaudi_measured_and_honest(self):
        collector = _deleting_collector(
            changed=["tests/test_safe_http.py"], deleted=["tests/test_safe_http.py"]
        )
        result = _assemble(collector=collector)
        section = next(s for s in result.sections if s.name == "gaudi-warn")
        assert section.measured
        assert collector.gaudi_calls == []
        assert "tests/test_safe_http.py" in section.body


class TestMeasuredStillMeansMeasured:
    """Making deletions readable must not make everything read as measured."""

    def test_a_changed_test_file_that_is_neither_present_nor_deleted_is_unmeasured(self):
        collector = _Collector(changed=["tests/test_x.py"], file_bodies={}, deleted=[])
        result = _assemble(collector=collector)
        section = next(s for s in result.sections if s.name == "changed-test-files")
        assert not section.measured
        assert exit_code_for(result) == EXIT_COULD_NOT_LOOK

    def test_a_deleted_test_whose_base_version_cannot_be_read_is_unmeasured(self):
        collector = _deleting_collector(base_bodies={})
        result = _assemble(collector=collector)
        section = next(s for s in result.sections if s.name == "changed-test-files")
        assert not section.measured
        assert exit_code_for(result) == EXIT_COULD_NOT_LOOK

    def test_an_unreadable_deletion_list_is_not_read_as_nothing_deleted(self):
        # "Could not list the deletions" and "there were none" must not produce
        # the same document: the first cannot tell a gone file from a blind spot.
        collector = _deleting_collector(deleted=None)
        result = _assemble(collector=collector)
        section = next(s for s in result.sections if s.name == "changed-test-files")
        assert not section.measured
        assert exit_code_for(result) == EXIT_COULD_NOT_LOOK

    def test_an_unmeasured_section_is_named_in_the_header_of_a_deleting_diff(self):
        text = render(_assemble(collector=_deleting_collector(base_bodies={})))
        assert "UNMEASURED INPUTS: changed-test-files" in text


class TestAnUnreadableDeletionListNamesItselfRatherThanFoldingAway:
    """`None` and `frozenset()` must not produce the same document (OS#442).

    The third state used to be inert: `_gaudi_section` folded it away with
    `deleted or frozenset()`, and an empty set can never certify a missing
    file as deleted, so the mutation `deleted = frozenset(reported or ())`
    left every test green while the comment beside it claimed the distinction
    was load-bearing. A comment asserting an invariant is part of the security
    surface, so the claim is enforced here instead.
    """

    def test_a_missing_test_file_names_the_unreadable_deletion_list_as_the_reason(self):
        result = _assemble(collector=_deleting_collector(deleted=None))
        section = next(s for s in result.sections if s.name == TEST_FILES_SECTION)
        assert not section.measured
        assert DELETION_LIST_UNREADABLE in section.reason
        assert exit_code_for(result) == EXIT_COULD_NOT_LOOK

    def test_a_readable_deletion_list_never_blames_the_deletion_list(self):
        # The same missing file, but the list was read and did not name it:
        # the blind spot is the file, not the list, and saying otherwise would
        # send the reviewer after the wrong thing.
        collector = _Collector(changed=["tests/test_x.py"], file_bodies={}, deleted=[])
        result = _assemble(collector=collector)
        section = next(s for s in result.sections if s.name == TEST_FILES_SECTION)
        assert not section.measured
        assert DELETION_LIST_UNREADABLE not in section.reason
        assert DELETION_LIST_UNREADABLE not in section.body

    def test_the_reason_reaches_the_reviewer_and_not_only_the_section(self):
        # An unmeasured section renders as COULD NOT LOOK, so a reason held
        # only in the body is a reason the reviewer never sees.
        text = render(_assemble(collector=_deleting_collector(deleted=None)))
        assert DELETION_LIST_UNREADABLE in text

    def test_the_base_version_is_withheld_because_no_deletion_was_established(self):
        # Invariant pin: showing it would present a deletion this run never
        # established as the reviewable act.
        text = render(_assemble(collector=_deleting_collector(deleted=None)))
        assert DELETED_TEST_NAME not in text
        assert "DELETED BY THIS DIFF" not in text

    def test_gaudi_says_the_skip_reason_is_unknowable_rather_than_by_design(self):
        result = _assemble(collector=_deleting_collector(deleted=None))
        section = next(s for s in result.sections if s.name == GAUDI_SECTION)
        assert DELETION_LIST_UNREADABLE in section.body
        assert "skipped by design" not in section.body.lower()

    def test_gaudi_skips_by_design_only_when_the_list_was_actually_read(self):
        result = _assemble(collector=_deleting_collector())
        section = next(s for s in result.sections if s.name == GAUDI_SECTION)
        assert "Skipped by design" in section.body
        assert DELETION_LIST_UNREADABLE not in section.body


class TestAssemblyIsDeterministic:
    def test_two_runs_over_the_same_inputs_render_byte_identical(self):
        assert render(_assemble()) == render(_assemble())

    def test_changed_files_are_sorted_regardless_of_probe_order(self):
        # The bodies must be readable, or both renders collapse to COULD NOT
        # LOOK and the comparison passes without ever exercising the ordering.
        bodies = {
            "tests/test_a.py": "def test_a(): ...\n",
            "tests/test_b.py": "def test_b(): ...\n",
        }
        forward = _assemble(
            collector=_Collector(changed=["tests/test_b.py", "tests/test_a.py"], file_bodies=bodies)
        )
        backward = _assemble(
            collector=_Collector(changed=["tests/test_a.py", "tests/test_b.py"], file_bodies=bodies)
        )
        assert "test_a" in render(forward)
        assert render(forward) == render(backward)


class TestCouldNotLookNeverReadsAsMeasured:
    @pytest.mark.parametrize(
        ("kwarg", "section_name"),
        [
            ("issue", "issue"),
            ("claude_md", "repo-doctrine"),
            ("gaudi", "gaudi-warn"),
        ],
    )
    def test_an_unavailable_probe_marks_its_section_unmeasured(self, kwarg, section_name):
        result = _assemble(collector=_Collector(**{kwarg: None}))
        section = next(s for s in result.sections if s.name == section_name)
        assert not section.measured
        assert "COULD NOT LOOK" in section.body

    @pytest.mark.parametrize("kwarg", ["issue", "claude_md", "gaudi"])
    def test_an_unavailable_probe_exits_two_not_zero(self, kwarg):
        result = _assemble(collector=_Collector(**{kwarg: None}))
        assert exit_code_for(result) == EXIT_COULD_NOT_LOOK

    def test_a_missing_diff_is_fatal_because_there_is_nothing_to_review(self):
        with pytest.raises(CouldNotLookError):
            _assemble(collector=_Collector(diff=None))

    def test_an_empty_diff_is_fatal_rather_than_an_empty_review(self):
        with pytest.raises(CouldNotLookError):
            _assemble(collector=_Collector(diff="   \n"))

    def test_omitting_the_issue_requires_an_explicit_decision(self):
        result = _assemble(issue=None, no_issue=True)
        section = next(s for s in result.sections if s.name == "issue")
        assert section.measured
        assert "no issue" in section.body.lower()

    def test_omitting_the_issue_without_saying_so_is_refused(self):
        with pytest.raises(CouldNotLookError):
            _assemble(issue=None)


class TestRenderedDocumentIsSelfDescribing:
    def test_every_section_is_delimited_so_the_reviewer_cannot_confuse_them(self):
        text = render(_assemble())
        for name in ("diff", "issue", "changed-test-files", "repo-doctrine", "gaudi-warn"):
            assert f"<!-- review-input:{name} -->" in text

    def test_the_header_states_the_base_and_repo_the_diff_was_taken_against(self):
        text = render(_assemble())
        assert "origin/master" in text
        assert "NathanKrupa/OverSteward" in text

    def test_an_unmeasured_section_is_flagged_in_the_header_not_only_inline(self):
        text = render(_assemble(collector=_Collector(gaudi=None)))
        assert "UNMEASURED INPUTS: gaudi-warn" in text


class TestIsTestPath:
    @pytest.mark.parametrize(
        "path",
        ["tests/test_x.py", "tests/dev/test_y.py", "src/pkg/tests/test_z.py", "test_top.py"],
    )
    def test_recognises_a_test_module(self, path):
        assert is_test_path(path)

    @pytest.mark.parametrize("path", ["src/pkg/latest.py", "docs/testing.md", "src/x.py"])
    def test_does_not_claim_a_non_test_module(self, path):
        assert not is_test_path(path)

    def test_conftest_counts_because_it_carries_the_fixtures_a_test_leans_on(self):
        assert is_test_path("tests/conftest.py")


class TestSection:
    def test_a_section_body_is_never_empty_so_a_blank_never_reads_as_absent(self):
        section = Section(name="issue", body="", measured=True)
        assert section.rendered_body.strip()

    def test_an_unmeasured_section_states_its_reason_beside_could_not_look(self):
        # "This input is missing" and "this input is missing because the
        # deletion list could not be read" are different findings; only the
        # second is actionable.
        section = Section(name="x", body="", measured=False, reason="gaudi is not installed")
        assert COULD_NOT_LOOK in section.rendered_body
        assert "gaudi is not installed" in section.rendered_body

    def test_an_unmeasured_section_renders_could_not_look_even_carrying_a_body(self):
        # An unmeasured section can hold real text — the readable half of a
        # partly-unreadable file list. `measured` is the authority on whether
        # the reviewer may trust it, so the body must not be rendered as if it
        # were the whole answer.
        section = Section(name="changed-test-files", body="def test_x(): ...", measured=False)
        assert section.rendered_body == COULD_NOT_LOOK


_BLOCK_VERDICT = (
    "```reviewer-verdict\nverdict: BLOCK\nfindings: 2\ntokens: 1\n```\n1. [hole] x — y\n"
)
_PASS_VERDICT = "```reviewer-verdict\nverdict: PASS\nfindings: 0\ntokens: 1\n```\n"


class TestARoundIsBookkeptNotAssumed:
    """The loop's economy (a delta re-review, a round cap) lives in the input's header."""

    def test_round_one_reads_the_whole_change_and_says_so(self):
        rendered = render(_assemble())

        assert "round: 1 of 3" in rendered
        assert "since: (none — the diff below is the whole change from base)" in rendered
        assert "Round 1 — there is no previous verdict." in rendered

    def test_a_re_review_diffs_only_since_the_reviewed_commit(self):
        collector = _Collector()

        assembled = _assemble(
            collector=collector, round_number=2, since="abc123", previous_verdict=_BLOCK_VERDICT
        )

        assert collector.diff_calls == ["abc123"], "the diff is taken from the reviewed commit"
        assert "since: abc123" in render(assembled)

    def test_the_test_files_still_span_the_whole_branch_on_a_re_review(self):
        collector = _Collector()

        _assemble(
            collector=collector, round_number=2, since="abc123", previous_verdict=_BLOCK_VERDICT
        )

        assert collector.changed_files_calls == ["origin/master"], (
            "the changed-file list is taken from the branch base, not the re-review point"
        )
        assert collector.deleted_files_calls == ["origin/master"]

    def test_a_deleted_test_on_a_re_review_is_read_at_the_branch_base(self):
        collector = _Collector(
            changed=["tests/test_gone.py"],
            deleted=["tests/test_gone.py"],
            file_bodies={},
            base_bodies={"tests/test_gone.py": "def test_gone():\n    assert True\n"},
        )

        _assemble(
            collector=collector, round_number=2, since="abc123", previous_verdict=_BLOCK_VERDICT
        )

        assert collector.base_text_calls == ["origin/master"], (
            "a deleted test's base version comes from the branch base on a re-review too"
        )

    def test_the_previous_verdict_reaches_the_reviewer(self):
        rendered = render(_assemble(round_number=2, previous_verdict=_BLOCK_VERDICT))

        assert "## previous-verdict" in rendered
        assert "verdict: BLOCK\nfindings: 2" in rendered

    def test_a_previous_verdict_that_is_not_a_verdict_block_is_refused(self):
        with pytest.raises(CouldNotLookError, match="not a reviewer verdict"):
            _assemble(round_number=2, previous_verdict="The reviewer said it looked fine.")

    def test_a_previous_pass_earns_no_re_review(self):
        with pytest.raises(CouldNotLookError, match="only a BLOCK earns a re-review"):
            _assemble(round_number=2, previous_verdict=_PASS_VERDICT)

    def test_an_override_where_no_cap_is_in_play_is_refused(self):
        with pytest.raises(CouldNotLookError, match="cap is not in play"):
            _assemble(cap_override="no cap in play")

    def test_a_re_review_without_the_previous_verdict_is_refused(self):
        with pytest.raises(CouldNotLookError, match="needs --previous-verdict"):
            _assemble(round_number=2)

    def test_a_first_round_refuses_a_since_point(self):
        with pytest.raises(CouldNotLookError, match="round 1 reads the whole change"):
            _assemble(since="abc123")

    def test_a_previous_verdict_on_round_one_is_refused(self):
        with pytest.raises(CouldNotLookError, match="round 1 takes no --previous-verdict"):
            _assemble(previous_verdict=_BLOCK_VERDICT)

    def test_the_fourth_round_is_refused(self):
        with pytest.raises(RoundCapError, match="exceeds the 3-round cap"):
            _assemble(round_number=4, previous_verdict=_BLOCK_VERDICT)

    def test_the_cap_can_be_overridden_only_with_a_recorded_reason(self):
        with pytest.raises(RoundCapError):
            _assemble(round_number=4, previous_verdict=_BLOCK_VERDICT, cap_override="   ")

        rendered = render(
            _assemble(
                round_number=4, previous_verdict=_BLOCK_VERDICT, cap_override="Nathan: one more"
            )
        )

        assert "round: 4 of 3" in rendered
        assert "CAP OVERRIDDEN: Nathan: one more" in rendered

    def test_the_previous_verdict_section_keeps_the_fixed_order_last(self):
        assembled = _assemble()

        assert [section.name for section in assembled.sections] == list(SECTION_ORDER)
        assert SECTION_ORDER[-1] == PREVIOUS_VERDICT_SECTION


class TestTheRoundIsDerivedFromTheLedgerNotDeclared:
    """Dropping --round cannot turn a fourth round into a first: the ledger counts."""

    L1 = "round=1 base=origin/master base_sha=aaa since=-\n"
    L2 = "round=2 base=origin/master base_sha=aaa since=abc\n"
    L3 = "round=3 base=origin/master base_sha=aaa since=def\n"

    def test_no_ledger_is_round_one(self):
        assert derive_round(None, None) == 1
        assert derive_round("", 1) == 1

    def test_the_next_round_is_one_more_than_the_ledger_holds(self):
        assert derive_round(self.L1 + self.L2, None) == 3
        assert derive_round(self.L1 + self.L2, 3) == 3

    def test_a_declared_round_that_disagrees_with_the_ledger_is_refused(self):
        with pytest.raises(CouldNotLookError, match="already built"):
            derive_round(self.L1 + self.L2 + self.L3, 1)

    def test_a_restart_is_refused_while_the_base_has_not_moved(self):
        with pytest.raises(CouldNotLookError, match="has not moved"):
            derive_round(
                self.L1 + self.L2, None, base_ref="origin/master", base_sha="aaa", restart="why"
            )

    def test_a_restart_against_a_different_base_ref_is_refused(self):
        with pytest.raises(CouldNotLookError, match="belongs to base"):
            derive_round(self.L1, None, base_ref="origin/other", base_sha="bbb", restart="why")

    def test_a_restart_with_nothing_built_is_refused(self):
        with pytest.raises(CouldNotLookError, match="no rounds have been built"):
            derive_round(None, None, base_ref="origin/master", base_sha="bbb", restart="why")

    def test_a_restart_after_the_base_moved_begins_at_one_and_only_at_one(self):
        moved = {"base_ref": "origin/master", "base_sha": "bbb", "restart": "base advanced"}

        assert derive_round(self.L1 + self.L2, None, **moved) == 1
        with pytest.raises(CouldNotLookError, match="starts the count again at round 1"):
            derive_round(self.L1 + self.L2, 2, **moved)

    def test_the_count_runs_from_the_last_restart_line(self):
        ledger = self.L1 + self.L2 + "round=1 base=origin/master base_sha=bbb since=- restart\n"

        assert derive_round(ledger, None) == 2

    def test_the_ledger_line_records_what_reconstructs_the_count(self):
        assert (
            ledger_line(2, "abc123", "", base_ref="origin/master", base_sha="aaa")
            == "round=2 base=origin/master base_sha=aaa since=abc123"
        )
        assert (
            ledger_line(1, None, "base advanced", base_ref="origin/master", base_sha="bbb")
            == "round=1 base=origin/master base_sha=bbb since=- restart"
        )

    def test_a_restart_is_printed_in_the_header(self):
        rendered = render(_assemble(restart_reason="base advanced"))

        assert "ROUNDS RESTARTED: base advanced" in rendered
        assert "this round 1 is not the change's first review" in rendered

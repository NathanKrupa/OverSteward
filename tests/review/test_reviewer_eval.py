# ABOUTME: Tests the eval-set validator and grader, and validates the real fixtures on disk.
# ABOUTME: Validation is not recall — these tests pin that distinction so CI cannot blur it.

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oversteward.review_verdict import BLOCK, PASS, PASS_WITH_FINDINGS
from oversteward.reviewer_eval import (
    MIN_BLOCK_CASES,
    Case,
    EvalSetError,
    grade,
    grade_case,
    load_cases,
    validate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "tests" / "reviewer_eval"


def _expected(verdict: str = BLOCK, **overrides) -> dict:
    payload = {
        "verdict": verdict,
        "failure_class": "test-never-red",
        "catalogue_items": [2],
        "must_cite": ["tests/test_x.py"],
        "must_mention": [],
        "provenance": "synthetic",
        "reconstructed": True,
        "why": "the test passes against the unfixed tree",
    }
    if verdict == PASS:
        payload["must_cite"] = []
    payload.update(overrides)
    return payload


def _case(name: str = "c", diff: str = "tests/test_x.py changed\n", **overrides) -> Case:
    return Case(name=name, diff=diff, expected=_expected(**overrides))


def _full_set() -> list[Case]:
    blocks = [_case(f"b{i}") for i in range(MIN_BLOCK_CASES)]
    return [*blocks, _case("control", verdict=PASS)]


class TestLoading:
    def test_a_missing_directory_is_an_eval_set_error(self, tmp_path):
        with pytest.raises(EvalSetError):
            load_cases(tmp_path / "nope")

    def test_an_empty_directory_is_refused_rather_than_scoring_zero_cases(self, tmp_path):
        with pytest.raises(EvalSetError):
            load_cases(tmp_path)

    def test_a_case_missing_its_diff_is_refused(self, tmp_path):
        case = tmp_path / "broken"
        case.mkdir()
        (case / "expected.json").write_text("{}", encoding="utf-8")
        with pytest.raises(EvalSetError, match="input.diff"):
            load_cases(tmp_path)

    def test_unparseable_expected_json_is_refused(self, tmp_path):
        case = tmp_path / "broken"
        case.mkdir()
        (case / "input.diff").write_text("x\n", encoding="utf-8")
        (case / "expected.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(EvalSetError):
            load_cases(tmp_path)


class TestValidate:
    def test_a_well_formed_set_has_no_problems(self):
        assert validate(_full_set()) == []

    def test_a_set_with_too_few_blocks_is_refused(self):
        assert validate([_case("b0"), _case("control", verdict=PASS)])

    def test_a_set_with_no_pass_control_is_refused(self):
        problems = validate([_case(f"b{i}") for i in range(MIN_BLOCK_CASES)])
        assert any("PASS control" in p for p in problems)

    def test_a_must_cite_path_absent_from_the_diff_is_refused(self):
        broken = _case("b0", must_cite=["src/never/mentioned.py"])
        assert any("must_cite" in p for p in validate([broken]))

    def test_a_known_bad_case_citing_nothing_is_refused(self):
        assert any("must name the file" in p for p in validate([_case("b0", must_cite=[])]))

    def test_a_missing_required_key_is_refused(self):
        case = Case(name="b", diff="x", expected={"verdict": BLOCK})
        assert any("missing" in p for p in validate([case]))

    def test_an_empty_why_is_refused_because_nobody_could_grade_it(self):
        assert any("why" in p for p in validate([_case("b0", why="  ")]))


class TestGrading:
    def _output(self, verdict: str, findings: int, body: str = "tests/test_x.py") -> str:
        return (
            f"{body}\n\n```reviewer-verdict\nverdict: {verdict}\n"
            f"findings: {findings}\ntokens: 100\n```\n"
        )

    def test_a_block_citing_the_required_path_is_caught(self):
        assert grade_case(_case(), self._output(BLOCK, 1)).caught

    def test_a_block_that_never_cites_the_path_is_not_caught(self):
        result = grade_case(_case(), self._output(BLOCK, 1, body="some other file"))
        assert not result.caught
        assert "another reason" in result.note

    def test_a_pass_on_a_known_bad_case_is_a_miss(self):
        assert not grade_case(_case(), self._output(PASS, 0)).caught

    def test_pass_with_findings_on_a_known_bad_case_is_a_miss_not_a_partial_credit(self):
        result = grade_case(_case(), self._output(PASS_WITH_FINDINGS, 2))
        assert not result.caught

    def test_the_clean_control_must_pass_not_merely_avoid_blocking(self):
        control = _case("control", verdict=PASS)
        assert grade_case(control, self._output(PASS, 0)).caught
        assert not grade_case(control, self._output(PASS_WITH_FINDINGS, 1)).caught

    def test_blocking_the_clean_control_is_a_miss(self):
        control = _case("control", verdict=PASS)
        assert not grade_case(control, self._output(BLOCK, 3)).caught

    def test_a_missing_result_is_a_miss_not_a_skip(self):
        assert not grade_case(_case(), None).caught

    def test_an_unparseable_verdict_is_a_miss(self):
        assert not grade_case(_case(), "I think this looks fine to me").caught

    def test_grade_covers_every_case_even_those_with_no_result(self):
        graded = grade(_full_set(), {})
        assert len(graded) == len(_full_set())
        assert not any(g.caught for g in graded)


class TestTheRealFixturesOnDisk:
    """The shipped eval set must itself satisfy the validator."""

    def test_the_shipped_eval_set_is_well_formed(self):
        assert validate(load_cases(EVAL_DIR)) == []

    def test_the_shipped_set_carries_the_six_cases_os_428_names(self):
        names = {case.name for case in load_cases(EVAL_DIR)}
        assert names == {
            "ag-b677986a8-production-refusal-removed",
            "gs-b14cb9b4-ssrf-sink-deleted",
            "os-312-vacuous-regression-tests",
            "importerror-only-red",
            "ag-pr1763-gate-piped-to-tail",
            "clean-control",
        }

    def test_the_two_historical_diffs_are_verbatim_not_reconstructed(self):
        by_name = {case.name: case for case in load_cases(EVAL_DIR)}
        for name in (
            "ag-b677986a8-production-refusal-removed",
            "gs-b14cb9b4-ssrf-sink-deleted",
        ):
            assert by_name[name].expected["reconstructed"] is False

    def test_every_reconstructed_case_says_so_in_its_provenance(self):
        for case in load_cases(EVAL_DIR):
            if case.expected["reconstructed"]:
                assert case.expected["provenance"].strip()

    def test_the_readme_refuses_to_call_ci_validation_an_eval_pass(self):
        # The one claim this fixture set must never make. If the wording moves,
        # this test should be updated deliberately, not silently.
        readme = (EVAL_DIR / "README.md").read_text(encoding="utf-8")
        assert "does **not** run a reviewer" in readme

    def test_expected_json_files_are_stable_json_so_a_diff_shows_intent(self):
        for case in load_cases(EVAL_DIR):
            raw = (EVAL_DIR / case.name / "expected.json").read_text(encoding="utf-8")
            assert raw == json.dumps(case.expected, indent=2, sort_keys=True) + "\n"

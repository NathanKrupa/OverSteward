# ABOUTME: Tests the pairwise comparison — the seeker rubric, per-side groundedness, the frozen prompt.
# ABOUTME: The model is never called; a scripted FakeJudge or a scripted genai client answers.

"""What a head-to-head has to say to be worth running.

A single winner is the wrong shape for the question the data lane actually
asks. Under the seeker rubric the comparison answers *each* of the seeker's
questions, and when both sides arrive with ground truth it also reports what
each side invented — one list and one score per side, never a difference
between them, because the variant that answers better while inventing more is
the finding.

The design comparison is pinned byte-for-byte here. It is an **invariant pin**,
not a regression guard: it passes against the code that came before this change
by construction. It bites under mutation — change a word of the prompt and it
goes red — which is the point, since every round compared to date used exactly
those bytes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from oversteward.judge.gemini import GeminiJudge, compare_prompt
from oversteward.judge.ground_truth import resolve_ground_truth
from oversteward.judge.models import (
    JudgeReadError,
    Manifest,
    PageText,
    Rubric,
    Verdict,
    Winner,
    manifest_from_mapping,
)
from oversteward.judge.service import Budget, BudgetExceeded, compare_manifest
from oversteward.probe.models import ProbeResult
from tests.judge.fakes import FakeGenaiClient, FakeJudge, FakeResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_MANIFEST = REPO_ROOT / "reports" / "judge" / "manifests" / "example.yaml"

_EXIT_OK = 0
_EXIT_COULD_NOT_LOOK = 1

_A = "https://app.example.test/foundations/pa/sector/housing/"
_B = "https://app.example.test/grants-for/housing/"

_BODIES = {
    _A: "<html><head><title>A</title></head><body><h1>Housing hub</h1><p>Two funders.</p></body></html>",
    _B: "<html><head><title>B</title></head>"
    "<body><h1>Grants for housing</h1><p>Ten funders.</p></body></html>",
}
#: What the extractor leaves of each body — written out, so the pin below is on
#: bytes this file owns rather than on whatever the extractor does today.
_TEXTS = {_A: "A\nHousing hub\n\nTwo funders.", _B: "B\nGrants for housing\n\nTen funders."}

#: The compare prompt as it stood before the seeker rubric existed. Frozen.
#: The four %s are the first title, the first text, the second title, the second
#: text — the only things a comparison is allowed to vary.
_COMPARE_PROMPT_GOLDEN = """\
You are a search quality rater comparing two web pages that
compete for the same search intent. Judge which better serves a person searching
for it: intent match, evidence of expertise, unique substance over boilerplate,
readability, and whether it actually answers the question.

Answer with JSON only: {"winner": "first" | "second" | "tie", "reason": "one line, at most 25 words"}

=== FIRST PAGE ===
TITLE: %s
%s

=== SECOND PAGE ===
TITLE: %s
%s
"""


def _golden(first: PageText, second: PageText) -> str:
    return _COMPARE_PROMPT_GOLDEN % (first.title, first.text, second.title, second.text)


def _page(url: str) -> PageText:
    return PageText(url=url, title=url[-2], text=_TEXTS[url])


def _module():
    spec = importlib.util.spec_from_file_location(
        "page_judge", REPO_ROOT / "scripts" / "page_judge.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fetch(url: str, *_args, **_kwargs) -> ProbeResult:
    return ProbeResult(
        url=url, status=200, title=url[-2], challenged=False, body=_BODIES.get(url, _BODIES[_A])
    )


def _manifest_file(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(
        f"name: unit\nsamples: 1\npairs:\n  - [{_A}, {_B}]\n" + extra,
        encoding="utf-8",
    )
    return path


def _manifest(**kwargs) -> Manifest:
    base = {"name": "unit", "samples": 1, "page_types": {}, "pairs": ((_A, _B),)}
    base.update(kwargs)
    return Manifest(**base)


def _run(argv, tmp_path, judge):
    return _module().main(
        argv,
        judge_factory=lambda: judge,
        token_factory=lambda: "probe-token",
        fetcher=_fetch,
        reports_dir=tmp_path / "out",
    )


def _tally(tmp_path: Path) -> dict:
    payload = json.loads(next((tmp_path / "out").glob("*.json")).read_text(encoding="utf-8"))
    return payload["tallies"][0]


def _report(tmp_path: Path) -> dict:
    return json.loads(next((tmp_path / "out").glob("*.json")).read_text(encoding="utf-8"))


def _markdown(tmp_path: Path) -> str:
    return next((tmp_path / "out").glob("*.md")).read_text(encoding="utf-8")


def _seeker_payload(**overrides) -> dict:
    payload = {name: "first" for name in Rubric.SEEKER.dimensions}
    payload.update({"winner": "first", "reason": "r"})
    payload.update(overrides)
    return payload


class TestTheDesignComparisonIsUnchanged:
    """Invariant pin: a manifest that names no rubric compares exactly as before."""

    def test_the_design_compare_prompt_is_byte_identical_to_the_frozen_golden(self):
        first, second = _page(_A), _page(_B)

        assert compare_prompt(first, second) == _golden(first, second)

    def test_a_manifest_that_names_no_rubric_sends_the_frozen_prompt_in_both_orders(self, tmp_path):
        answer = json.dumps({"winner": "first", "reason": "r"})
        client = FakeGenaiClient([FakeResponse(answer), FakeResponse(answer)])
        judge = GeminiJudge(api_key="unused-because-client-is-injected", client=client)

        code = _run(["compare", str(_manifest_file(tmp_path))], tmp_path, judge)

        assert code == _EXIT_OK
        assert [call["contents"] for call in client.models.calls] == [
            _golden(_page(_A), _page(_B)),
            _golden(_page(_B), _page(_A)),
        ]

    def test_a_design_comparison_reports_no_per_question_preferences(self, tmp_path):
        _run(["compare", str(_manifest_file(tmp_path))], tmp_path, FakeJudge())

        assert "per_question" not in _tally(tmp_path)


class TestTheSeekerComparison:
    @pytest.mark.parametrize(
        "question",
        [
            "Can I apply?",
            "What do they typically give?",
            "Who do they fund, and are they like me?",
            "When?",
            "Where?",
            "non-expert reader",
        ],
    )
    def test_the_seeker_compare_prompt_asks_every_seeker_question(self, question):
        # Written out rather than read from SEEKER_QUESTIONS: a test that sources
        # its expectation from the constant it checks moves whenever the constant
        # does, and proves only that the prompt was built from something.
        prompt = compare_prompt(_page(_A), _page(_B), rubric=Rubric.SEEKER)

        assert question in prompt

    def test_a_seeker_pair_is_tallied_per_question_and_the_report_names_the_rubric(self, tmp_path):
        judge = FakeJudge()

        code = _run(["compare", str(_manifest_file(tmp_path, "rubric: seeker\n"))], tmp_path, judge)

        assert code == _EXIT_OK
        assert judge.compare_rubrics == [Rubric.SEEKER, Rubric.SEEKER]
        payload = _report(tmp_path)
        assert payload["rubric"] == "seeker"
        assert list(payload["tallies"][0]["per_question"]) == list(Rubric.SEEKER.dimensions)
        markdown = _markdown(tmp_path)
        assert "Rubric: **seeker**" in markdown
        assert "can_i_apply" in markdown

    def test_a_judge_that_always_names_the_page_shown_first_splits_every_question_evenly(self):
        """The position-bias guard, per question: a sweep means the swap is not mapped back."""
        judge = FakeJudge(winner=Winner.FIRST)

        report = compare_manifest(
            judge, _fetch, _manifest(samples=3, rubric=Rubric.SEEKER), Budget(limit_usd=10.0)
        )

        per_question = report.tallies[0].per_question
        assert list(per_question) == list(Rubric.SEEKER.dimensions)
        for name, question in per_question.items():
            assert (question.a_wins, question.b_wins, question.ties) == (3, 3, 0), name

    def test_an_answer_missing_one_question_is_a_read_error_not_a_tie(self):
        payload = _seeker_payload()
        del payload["when_to_apply"]

        with pytest.raises(JudgeReadError, match="when_to_apply"):
            Verdict.from_payload(payload, rubric=Rubric.SEEKER)


class TestPerSideGroundedness:
    _A_CLAIMS = ("Invents a 2027 deadline.",)
    _B_CLAIMS = (
        "Says it funds nationally; the facts say Pennsylvania.",
        "Invents a $5m housing fund.",
        "Names a program officer the facts do not carry.",
    )

    def _run_grounded(self, tmp_path):
        judge = FakeJudge(claims_by_url={_A: self._A_CLAIMS, _B: self._B_CLAIMS})
        extra = (
            "rubric: seeker\n"
            f"ground_truth:\n  {_A}:\n    state: PA\n  {_B}:\n    sector: housing\n"
        )
        code = _run(["compare", str(_manifest_file(tmp_path, extra))], tmp_path, judge)
        return code, judge

    def test_each_side_keeps_its_own_claims_and_its_own_score(self, tmp_path):
        code, judge = self._run_grounded(tmp_path)

        assert code == _EXIT_OK
        # Both orderings were judged against facts, each side against its own.
        assert judge.compare_grounded == [(_A, _B), (_B, _A)]
        assert _tally(tmp_path)["groundedness"] == [
            {"url": _A, "score": 4, "unsupported_claims": list(self._A_CLAIMS)},
            {"url": _B, "score": 2, "unsupported_claims": list(self._B_CLAIMS)},
        ]

    def test_the_report_prints_both_sides_claims_verbatim(self, tmp_path):
        self._run_grounded(tmp_path)

        markdown = _markdown(tmp_path)
        for claim in self._A_CLAIMS + self._B_CLAIMS:
            assert claim in markdown

    def test_a_pair_with_no_ground_truth_carries_no_groundedness_reading(self, tmp_path):
        judge = FakeJudge()

        _run(["compare", str(_manifest_file(tmp_path))], tmp_path, judge)

        assert judge.compare_grounded == []
        assert "groundedness" not in _tally(tmp_path)

    def test_an_answer_with_no_per_side_claim_lists_is_a_read_error(self):
        payload = {"winner": "tie", "reason": "r", "unsupported_claims_first": []}

        with pytest.raises(JudgeReadError, match="unsupported_claims_second"):
            Verdict.from_payload(payload, grounded=True)

    def test_both_sides_facts_count_toward_the_budget_estimate(self):
        facts = {"note": "y" * 100_000}

        # The pair alone clears this cap; the same pair carrying the facts does not.
        compare_manifest(FakeJudge(), _fetch, _manifest(), Budget(limit_usd=0.0025))
        with pytest.raises(BudgetExceeded):
            compare_manifest(
                FakeJudge(),
                _fetch,
                _manifest(),
                Budget(limit_usd=0.0025),
                ground_truth={_A: facts, _B: facts},
            )


class TestGroundTruthForOneSideOnly:
    def test_it_exits_one_before_any_call_is_issued(self, tmp_path, capsys):
        judge = FakeJudge()
        extra = f"ground_truth:\n  {_A}:\n    state: PA\n"

        code = _run(["compare", str(_manifest_file(tmp_path, extra))], tmp_path, judge)

        assert code == _EXIT_COULD_NOT_LOOK
        assert judge.calls == 0
        assert "one side only" in capsys.readouterr().err

    def test_a_pair_neither_side_of_which_has_facts_is_judged_without_them(self, tmp_path):
        """The refusal is about asymmetry, not about ground truth existing somewhere."""
        judge = FakeJudge()
        other = "https://app.example.test/foundations/oh/sector/education/"
        extra = f"ground_truth:\n  {other}:\n    state: OH\n"

        code = _run(["compare", str(_manifest_file(tmp_path, extra))], tmp_path, judge)

        assert code == _EXIT_OK
        assert judge.compare_grounded == []


class TestTheExampleManifest:
    """The example is documentation, so it has to survive being read as a manifest."""

    def _example(self) -> Manifest:
        data = yaml.safe_load(EXAMPLE_MANIFEST.read_text(encoding="utf-8"))
        return manifest_from_mapping(data)

    def test_it_parses_and_names_a_rubric(self):
        assert self._example().rubric is Rubric.DESIGN

    def test_it_documents_ground_truth_written_inline_and_as_a_path(self):
        entries = list(self._example().ground_truth.values())

        assert any(isinstance(entry, dict) for entry in entries)
        assert any(isinstance(entry, str) for entry in entries)

    def test_every_fixture_it_names_is_on_disk_and_readable(self):
        manifest = self._example()

        facts = resolve_ground_truth(manifest.ground_truth, EXAMPLE_MANIFEST.parent)

        assert set(facts) == set(manifest.ground_truth)

    def test_both_sides_of_its_pair_carry_ground_truth(self):
        """Anything else would be the misconfiguration the compare run refuses."""
        manifest = self._example()

        for a, b in manifest.pairs:
            assert a in manifest.ground_truth
            assert b in manifest.ground_truth

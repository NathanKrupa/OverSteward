# ABOUTME: Tests the seeker rubric, the groundedness dimension, and the frozen design prompt.
# ABOUTME: The model is never called — a scripted FakeJudge answers, so a rubric change is free to test.

"""Two instruments, one judge.

The design rubric asks whether this is a good page; the seeker rubric asks
whether it answers the questions a grant seeker arrives with. Groundedness is
neither: the model lists what the ground truth cannot support, and the score is
arithmetic over that list.

The design prompt is pinned byte-for-byte here. It is an **invariant pin**, not
a regression guard — it passes against the code that came before this change, by
construction. It bites under mutation: change a word of the prompt and it goes
red, which is the point, because every round judged to date used those bytes.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from oversteward.judge.gemini import score_prompt
from oversteward.judge.models import (
    GROUNDEDNESS,
    JudgeReadError,
    PageText,
    Rubric,
    RubricScore,
    groundedness_score,
    manifest_from_mapping,
)
from oversteward.judge.service import Budget, BudgetExceeded, score_manifest
from oversteward.probe.models import ProbeResult
from tests.judge.fakes import FakeJudge, dimension_payload

REPO_ROOT = Path(__file__).resolve().parents[2]

_EXIT_OK = 0
_EXIT_COULD_NOT_LOOK = 1

_URL = "https://app.example.test/foundations/pa/example/"
_BODY = "<html><head><title>T</title></head><body><h1>H</h1><p>Words.</p></body></html>"
_FACTS = {"name": "Example Foundation", "total_giving_usd": 125000}

#: The design prompt as it stood before the seeker rubric existed. Frozen.
_DESIGN_PROMPT_GOLDEN = """\
You are a search quality rater assessing one web page.

Score the page on each dimension from 1 to 5, where **5 is always best**:

- intent_match: Does the content above the fold match the search intent the title implies?
- eeat: Are there experience, expertise, authoritativeness and trust signals — named sources, figures, dates, an identifiable publisher?
- unique_ratio: How much of the page is unique substance rather than boilerplate, navigation and repeated template text?
- thin_smell: Freedom from thin/doorway smell: 5 = substantial original content, 1 = a keyword-stuffed doorway with nothing a reader could not guess from the title.
- readability: Is it clear, well structured and readable by a non-expert?
- answers_query: Does it actually answer the question its title promises, on the page, without requiring a signup or another click?

Answer with JSON only, in exactly this shape, with a one-line reason per
dimension (no more than 20 words each):

{"intent_match": {"score": 3, "reason": "..."}, "eeat": {"score": 3, "reason": "..."},
 "unique_ratio": {"score": 3, "reason": "..."}, "thin_smell": {"score": 3, "reason": "..."},
 "readability": {"score": 3, "reason": "..."}, "answers_query": {"score": 3, "reason": "..."}}

TITLE: T
URL: https://example.test/x/

PAGE TEXT:
Body words.
"""


def _module():
    spec = importlib.util.spec_from_file_location(
        "page_judge", REPO_ROOT / "scripts" / "page_judge.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fetch_ok(url, token, **_kwargs):
    return ProbeResult(url=url, status=200, title="T", challenged=False, body=_BODY)


def _manifest(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(
        "name: unit\nsamples: 1\npage_types:\n" f"  foundation: [{_URL}]\n" + extra,
        encoding="utf-8",
    )
    return path


def _run(argv, tmp_path, judge: FakeJudge):
    return _module().main(
        argv,
        judge_factory=lambda: judge,
        token_factory=lambda: "probe-token",
        fetcher=_fetch_ok,
        reports_dir=tmp_path / "out",
    )


def _report(tmp_path: Path) -> dict:
    return json.loads(next((tmp_path / "out").glob("*.json")).read_text(encoding="utf-8"))


def _markdown(tmp_path: Path) -> str:
    return next((tmp_path / "out").glob("*.md")).read_text(encoding="utf-8")


class TestTheDesignRubricIsUnchanged:
    """Invariant pin: a manifest that names no rubric judges exactly as before."""

    def test_the_design_score_prompt_is_byte_identical_to_the_frozen_golden(self):
        page = PageText(url="https://example.test/x/", title="T", text="Body words.")

        assert score_prompt(page) == _DESIGN_PROMPT_GOLDEN

    def test_a_manifest_that_names_no_rubric_is_the_design_rubric(self):
        manifest = manifest_from_mapping({"name": "unit"})

        assert manifest.rubric is Rubric.DESIGN

    def test_an_unknown_rubric_names_the_ones_that_exist(self):
        with pytest.raises(ValueError, match="design, seeker"):
            manifest_from_mapping({"rubric": "vibes"})


class TestTheSeekerRubric:
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
    def test_the_seeker_prompt_asks_every_seeker_question(self, question):
        # Written out rather than read from SEEKER_QUESTIONS: a test that sources
        # its expectation from the constant it checks moves whenever the constant
        # does, and proves only that the prompt was built from something.
        page = PageText(url=_URL, title="T", text="Body words.")

        assert question in score_prompt(page, rubric=Rubric.SEEKER)

    def test_the_seeker_prompt_names_every_seeker_dimension(self):
        page = PageText(url=_URL, title="T", text="Body words.")

        prompt = score_prompt(page, rubric=Rubric.SEEKER)

        for name in Rubric.SEEKER.dimensions:
            assert f"- {name}: " in prompt

    def test_a_seeker_manifest_scores_the_seeker_dimensions_and_the_report_names_the_rubric(
        self, tmp_path
    ):
        judge = FakeJudge()

        code = _run(["score", str(_manifest(tmp_path, "rubric: seeker\n"))], tmp_path, judge)

        assert code == _EXIT_OK
        assert judge.rubrics == [Rubric.SEEKER]
        payload = _report(tmp_path)
        assert payload["rubric"] == "seeker"
        assert list(payload["pages"][0]["scores"]) == list(Rubric.SEEKER.dimensions)
        markdown = _markdown(tmp_path)
        assert "Rubric: **seeker**" in markdown
        assert "can_i_apply" in markdown


class TestGroundedness:
    @pytest.mark.parametrize(
        ("claims", "expected"),
        [(0, 5), (1, 4), (2, 3), (3, 2), (4, 1), (9, 1)],
    )
    def test_the_score_is_a_deterministic_mapping_from_the_claim_count(self, claims, expected):
        assert groundedness_score(claims) == expected

    def test_two_unsupported_claims_score_three_and_the_report_prints_them_verbatim(self, tmp_path):
        claims = ("Says it funds nationally; ground truth is Pennsylvania only.", "Invents a 2027 deadline.")
        judge = FakeJudge(unsupported_claims=claims)
        extra = f"ground_truth:\n  {_URL}:\n    name: Example Foundation\n    state: PA\n"

        code = _run(["score", str(_manifest(tmp_path, extra))], tmp_path, judge)

        assert code == _EXIT_OK
        assert judge.grounded == [_URL]
        page = _report(tmp_path)["pages"][0]
        assert page["scores"][GROUNDEDNESS]["score"] == 3
        assert page["unsupported_claims"] == list(claims)
        markdown = _markdown(tmp_path)
        for claim in claims:
            assert claim in markdown

    def test_a_page_with_no_ground_truth_carries_no_groundedness_dimension(self, tmp_path):
        judge = FakeJudge()

        _run(["score", str(_manifest(tmp_path))], tmp_path, judge)

        assert judge.grounded == []
        assert GROUNDEDNESS not in _report(tmp_path)["pages"][0]["scores"]

    def test_an_answer_with_no_claims_list_is_a_read_error(self):
        with pytest.raises(JudgeReadError, match="unsupported_claims"):
            RubricScore.from_payload(_URL, dimension_payload(), grounded=True)

    def test_the_ground_truth_payload_counts_toward_the_budget_estimate(self):
        manifest = manifest_from_mapping({"name": "unit", "page_types": {"foundation": [_URL]}})
        facts = {"note": "y" * 100_000}

        def fetch(url):
            return ProbeResult(
                url=url, status=200, title="T", challenged=False, body=f"<p>{'x' * 400}</p>"
            )

        # The page alone clears this cap; the same page carrying the facts does not.
        score_manifest(FakeJudge(), fetch, manifest, Budget(limit_usd=0.002))
        with pytest.raises(BudgetExceeded):
            score_manifest(
                FakeJudge(), fetch, manifest, Budget(limit_usd=0.002), ground_truth={_URL: facts}
            )


class TestAGroundTruthPathThatDoesNotExist:
    def test_it_exits_one_before_any_call_is_issued(self, tmp_path, capsys):
        judge = FakeJudge()
        extra = f"ground_truth:\n  {_URL}: facts/missing.json\n"

        code = _run(["score", str(_manifest(tmp_path, extra))], tmp_path, judge)

        assert code == _EXIT_COULD_NOT_LOOK
        assert judge.calls == 0
        assert "does not exist" in capsys.readouterr().err

    def test_a_fixture_on_disk_is_read_and_judged_against(self, tmp_path):
        (tmp_path / "facts.json").write_text(json.dumps(_FACTS), encoding="utf-8")
        judge = FakeJudge(unsupported_claims=("One claim the facts do not carry.",))
        extra = f"ground_truth:\n  {_URL}: facts.json\n"

        code = _run(["score", str(_manifest(tmp_path, extra))], tmp_path, judge)

        assert code == _EXIT_OK
        assert _report(tmp_path)["pages"][0]["scores"][GROUNDEDNESS]["score"] == 4

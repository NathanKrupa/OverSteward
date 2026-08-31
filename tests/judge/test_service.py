# ABOUTME: Tests the judge orchestration — order-swapped pairwise tallies and the budget abort.
# ABOUTME: Both guards are about what must NOT happen: a position sweep, and a call past the cap.

from __future__ import annotations

import pytest

from oversteward.judge.models import JudgeReadError, Manifest, Usage, Winner
from oversteward.judge.service import Budget, BudgetExceeded, compare_manifest, score_manifest
from oversteward.probe.models import ProbeResult
from tests.judge.fakes import FakeJudge

_A = "https://app.example.test/a/"
_B = "https://app.example.test/b/"

_BODY = "<html><head><title>T</title></head><body><h1>Heading</h1><p>Some words.</p></body></html>"


def _fetch_ok(url: str) -> ProbeResult:
    return ProbeResult(url=url, status=200, title="T", challenged=False, body=_BODY)


def _fetch_challenged(url: str) -> ProbeResult:
    return ProbeResult(url=url, status=403, title="", challenged=True, body="")


def _manifest(**kwargs) -> Manifest:
    base = {
        "name": "round-1",
        "samples": 3,
        "page_types": {"foundation": (_A,)},
        "pairs": ((_A, _B),),
    }
    base.update(kwargs)
    return Manifest(**base)


class TestPairwiseOrderSwap:
    def test_every_pair_is_judged_in_both_orders(self):
        judge = FakeJudge()
        report = compare_manifest(judge, _fetch_ok, _manifest(), Budget(limit_usd=10.0))

        assert judge.compared == [(_A, _B), (_B, _A)] * 3
        assert report.tallies[0].samples == 6

    def test_a_judge_that_always_names_the_first_page_tallies_evenly(self):
        """The position-bias guard: an A sweep here would mean the swap is not mapped back."""
        judge = FakeJudge(winner=Winner.FIRST)
        report = compare_manifest(judge, _fetch_ok, _manifest(), Budget(limit_usd=10.0))

        tally = report.tallies[0]
        assert (tally.a_wins, tally.b_wins, tally.ties) == (3, 3, 0)

    def test_a_judge_that_always_names_the_second_page_also_tallies_evenly(self):
        judge = FakeJudge(winner=Winner.SECOND)
        report = compare_manifest(judge, _fetch_ok, _manifest(), Budget(limit_usd=10.0))

        tally = report.tallies[0]
        assert (tally.a_wins, tally.b_wins, tally.ties) == (3, 3, 0)


class TestBudget:
    def test_a_cap_below_the_first_estimate_issues_no_call_at_all(self):
        """The abort must precede the call, not follow it.

        This is the case that separates the two: with the check placed *after*
        the call, one request would already have been paid for before anything
        noticed. Nothing may be spent here.
        """
        judge = FakeJudge()
        budget = Budget(limit_usd=0.0000001)

        with pytest.raises(BudgetExceeded):
            score_manifest(judge, _fetch_ok, _manifest(), budget)

        assert judge.calls == 0
        assert budget.spent_usd == 0.0

    def test_the_over_budget_call_is_never_issued(self):
        # Each fake call costs 0.001125, so a 0.003 cap affords two. The third
        # is refused on the estimate, before the judge is ever asked.
        judge = FakeJudge(usage=Usage(1000, 100, 0.001125))
        budget = Budget(limit_usd=0.003)

        with pytest.raises(BudgetExceeded) as caught:
            compare_manifest(judge, _fetch_ok, _manifest(), budget)

        assert judge.calls == 2
        assert budget.spent_usd == pytest.approx(0.00225)
        assert "0.002250" in str(caught.value)

    def test_spend_is_the_sum_of_the_calls_that_completed(self):
        judge = FakeJudge(usage=Usage(1000, 100, 0.001125))
        budget = Budget(limit_usd=10.0)

        score_manifest(judge, _fetch_ok, _manifest(page_types={"foundation": (_A, _B)}), budget)

        assert judge.calls == 2
        assert budget.spent_usd == pytest.approx(0.00225)


class TestFetchFailures:
    def test_a_challenged_page_is_could_not_read_not_a_low_score(self):
        with pytest.raises(JudgeReadError, match="challenge"):
            score_manifest(FakeJudge(), _fetch_challenged, _manifest(), Budget(limit_usd=10.0))

    def test_a_non_200_page_is_could_not_read(self):
        def fetch(url: str) -> ProbeResult:
            return ProbeResult(url=url, status=404, title="", challenged=False, body="")

        with pytest.raises(JudgeReadError, match="404"):
            score_manifest(FakeJudge(), fetch, _manifest(), Budget(limit_usd=10.0))

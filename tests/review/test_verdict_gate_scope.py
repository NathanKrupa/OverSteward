# ABOUTME: Tests the verdict gate's non-retroactivity cutoff — who the gate governs, and who it cannot.
# ABOUTME: A cutoff that can be widened by a bad timestamp, or moved into the future, is a bypass.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from oversteward.review_verdict import (
    EXIT_COULD_NOT_LOOK,
    EXIT_NOT_APPLICABLE,
    EXIT_OK,
    EXIT_VIOLATIONS,
    GATE_LIVE_FROM,
    governs,
    judge_pull_request,
)

CUTOFF = datetime.fromisoformat(GATE_LIVE_FROM)


def _offset(**delta: float) -> str:
    """An ISO 8601 instant relative to the cutoff, in GitHub's `Z` spelling."""
    return (CUTOFF + timedelta(**delta)).isoformat().replace("+00:00", "Z")


class TestWhoTheGateGoverns:
    def test_a_pr_opened_after_the_cutoff_is_governed(self):
        assert governs(_offset(seconds=1)) is True

    def test_a_pr_opened_before_the_cutoff_is_not_governed(self):
        """It could not have carried a verdict for a gate that did not exist."""
        assert governs(_offset(days=-1)) is False

    def test_the_cutoff_instant_itself_is_not_governed(self):
        """The boundary is the gate's own PR — open before the gate existed."""
        assert governs(GATE_LIVE_FROM) is False


class TestTheCutoffCannotBecomeABypass:
    def test_a_pr_with_no_creation_time_is_governed(self):
        """Fail closed: 'I could not tell how old it is' is not an exemption."""
        assert governs(None) is True

    def test_an_unreadable_creation_time_is_governed(self):
        assert governs("last Tuesday") is True

    def test_an_empty_creation_time_is_governed(self):
        assert governs("") is True

    def test_the_cutoff_is_not_in_the_future(self):
        """A cutoff ahead of now exempts every PR ever opened — an inert gate."""
        assert CUTOFF <= datetime.now(UTC), (
            f"{GATE_LIVE_FROM} is in the future: every PR would predate the gate."
        )

    def test_not_applicable_never_shares_an_exit_code_with_another_outcome(self):
        """Predates-the-gate must not print or exit as a pass, or it is a skip."""
        assert EXIT_NOT_APPLICABLE not in {EXIT_OK, EXIT_VIOLATIONS, EXIT_COULD_NOT_LOOK}

    def test_the_cutoff_literal_is_pinned(self):
        """The future-value guard above misses the direction that matters.

        Every PR opened after the cutoff is governed, so the exempt set is
        `created_at <= GATE_LIVE_FROM` — and moving the literal *forward*, while
        staying comfortably in the past, widens that set by exactly the distance
        moved. The `<= now` assertion cannot see it: a cutoff moved from PR#443's
        creation instant to yesterday evening is still in the past and still
        passes, while silently exempting every PR opened in between (OS#444).

        So the value is pinned, not merely bounded. Changing it is a deliberate
        edit to this line, reviewed and recorded, which is the only property the
        comment in review_verdict.py claims for it.
        """
        assert GATE_LIVE_FROM == "2026-09-02T02:40:24+00:00", (
            "GATE_LIVE_FROM moved. It is PR#443's own created_at and nothing "
            "else; a forward move widens the set of PRs the gate never judges."
        )


class TestJudgingComesBeforeTheCutoff:
    """OS#444 — non-retroactivity excuses an absent verdict, not a present one."""

    def _body(self, verdict: str, findings: int) -> str:
        return (
            "Closes #444\n\n"
            "```reviewer-verdict\n"
            f"verdict: {verdict}\nfindings: {findings}\ntokens: 100\n"
            "```\n"
        )

    def test_a_predating_pr_with_a_block_verdict_is_still_a_violation(self):
        code, _ = judge_pull_request(self._body("BLOCK", 1), _offset(days=-1))
        assert code == EXIT_VIOLATIONS

    def test_a_predating_pr_with_a_pass_verdict_is_the_pass_it_is(self):
        code, _ = judge_pull_request(self._body("PASS", 0), _offset(days=-1))
        assert code == EXIT_OK

    def test_a_predating_pr_with_a_malformed_block_is_judged(self):
        """A block was written; only an absent one is excused."""
        code, _ = judge_pull_request(self._body("PASS", 3), _offset(days=-1))
        assert code == EXIT_VIOLATIONS

    def test_a_predating_pr_with_no_verdict_block_is_not_applicable(self):
        code, message = judge_pull_request("no verdict here", _offset(days=-1))
        assert code == EXIT_NOT_APPLICABLE
        assert "Nothing was judged" in message

    def test_a_governed_pr_with_no_verdict_block_is_a_violation(self):
        code, _ = judge_pull_request("no verdict here", _offset(seconds=1))
        assert code == EXIT_VIOLATIONS

    def test_an_unreadable_body_is_could_not_look_whatever_its_age(self):
        """Exit 2 outranks the exemption: a body nobody could read is not an
        excused absence, it is an unanswered question."""
        code, _ = judge_pull_request(None, _offset(days=-1))
        assert code == EXIT_COULD_NOT_LOOK

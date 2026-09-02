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

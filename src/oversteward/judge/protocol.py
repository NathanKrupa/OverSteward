# ABOUTME: The Judge seam — what the orchestration needs, independent of which model answers.
# ABOUTME: One implementation today (GeminiJudge); a second opinion plugs in here, not in the service.

from __future__ import annotations

from typing import Protocol

from oversteward.judge.models import PageText, RubricScore, Usage, Verdict


class Judge(Protocol):
    """Rates one page, or prefers one of two.

    Every method returns its :class:`Usage` alongside the answer: the budget is
    computed from what the model actually reported, never from an estimate the
    caller made up afterwards.
    """

    def score(self, page: PageText) -> tuple[RubricScore, Usage]:
        """Rate ``page`` on the six rubric dimensions."""
        ...

    def compare(self, a: PageText, b: PageText) -> tuple[Verdict, Usage]:
        """Prefer ``a`` or ``b`` *as presented* — the verdict is positional."""
        ...


__all__ = ["Judge"]

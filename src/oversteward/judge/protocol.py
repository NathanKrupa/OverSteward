# ABOUTME: The Judge seam — what the orchestration needs, independent of which model answers.
# ABOUTME: One implementation today (GeminiJudge); a second opinion plugs in here, not in the service.

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from oversteward.judge.models import PageText, Rubric, RubricScore, Usage, Verdict


class Judge(Protocol):
    """Rates one page, or prefers one of two.

    Every method returns its :class:`Usage` alongside the answer: the budget is
    computed from what the model actually reported, never from an estimate the
    caller made up afterwards.
    """

    def score(
        self,
        page: PageText,
        *,
        rubric: Rubric = Rubric.DESIGN,
        ground_truth: Mapping | None = None,
    ) -> tuple[RubricScore, Usage]:
        """Rate ``page`` on ``rubric``'s dimensions.

        ``ground_truth`` is the facts the page may be checked against. When it is
        supplied the answer also carries the claims those facts cannot support,
        and the groundedness score is derived from that list by the caller — the
        judge is asked what it saw, never how grounded it thinks the page is.
        """
        ...

    def compare(
        self,
        a: PageText,
        b: PageText,
        *,
        rubric: Rubric = Rubric.DESIGN,
        ground_truth: tuple[Mapping, Mapping] | None = None,
    ) -> tuple[Verdict, Usage]:
        """Prefer ``a`` or ``b`` *as presented* — the verdict is positional.

        ``rubric`` decides what is asked: one overall preference, or one per
        question. ``ground_truth`` is the facts for the two pages in the order
        presented, and is supplied only when BOTH sides have them — a comparison
        that checked one page and not the other would read as if the unchecked
        page had invented nothing.
        """
        ...


__all__ = ["Judge"]

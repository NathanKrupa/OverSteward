# ABOUTME: MIDDLE layer — fetch the manifest's pages, spend the budget, tally the pairwise verdicts.
# ABOUTME: Every decision lives here: order-swapping, the budget abort, what counts as unreadable.

"""Run a quality-rater pass over a manifest of live pages.

Two orchestrations, one budget:

* :func:`score_manifest` rates each URL on the rubric.
* :func:`compare_manifest` judges each pair **in both orders**, ``samples``
  times each, and maps the swapped verdict back before tallying. A model that
  simply prefers whatever it read first therefore produces an even split, not a
  sweep — which is the only reason a tally here can be read as a preference.

The budget is checked *before* each call. Overspending is not something to
notice afterwards: a cap that reports the overspend it allowed is not a cap.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from oversteward.judge.extract import visible_text
from oversteward.judge.models import (
    NO_USAGE,
    CompareTally,
    JudgeReadError,
    Manifest,
    PageText,
    RubricScore,
    Usage,
    Winner,
    usage_for,
)
from oversteward.judge.protocol import Judge
from oversteward.probe.models import ProbeResult

#: A fetcher already bound to its probe token: url in, ProbeResult out.
FetchPage = Callable[[str], ProbeResult]

#: Characters per token, for the first call's estimate only. Every later
#: estimate uses the mean of what the API actually reported.
_CHARS_PER_TOKEN = 4

#: Assumed output length for that same first estimate — six dimensions with a
#: one-line reason each. Deliberately generous: an estimate that runs low would
#: let the first call through a cap it should not have cleared.
_ASSUMED_OUTPUT_TOKENS = 400


class BudgetExceeded(RuntimeError):
    """The next call would cross the cap, so it was never issued."""


@dataclass
class Budget:
    """What may be spent, and what has been.

    ``check`` is called before each request and raises rather than returning a
    verdict the caller could ignore.
    """

    limit_usd: float
    usage: Usage = NO_USAGE
    calls: int = 0

    @property
    def spent_usd(self) -> float:
        """What has actually been billed — read off the usage, never tracked twice."""
        return self.usage.cost_usd

    def estimate(self, page_chars: int) -> float:
        """What the next call is expected to cost."""
        if self.calls:
            return self.spent_usd / self.calls
        prompt_tokens = page_chars // _CHARS_PER_TOKEN
        return usage_for(prompt_tokens, _ASSUMED_OUTPUT_TOKENS).cost_usd

    def check(self, page_chars: int) -> None:
        """Refuse the next call if it would cross the cap. Nothing is spent here."""
        projected = self.spent_usd + self.estimate(page_chars)
        if projected > self.limit_usd:
            raise BudgetExceeded(
                f"the next call is estimated at ${projected - self.spent_usd:.6f}, which would "
                f"cross the ${self.limit_usd:.2f} cap — spent ${self.spent_usd:.6f} over "
                f"{self.calls} call(s); the call was not issued"
            )

    def record(self, usage: Usage) -> None:
        self.usage = self.usage + usage
        self.calls += 1


@dataclass(frozen=True, slots=True)
class ScoredPage:
    """One page, its declared type, and how it rated."""

    page_type: str
    page: PageText
    score: RubricScore


@dataclass(frozen=True, slots=True)
class ScoreReport:
    name: str
    pages: tuple[ScoredPage, ...]
    usage: Usage


@dataclass(frozen=True, slots=True)
class CompareReport:
    name: str
    tallies: tuple[CompareTally, ...]
    usage: Usage


def score_manifest(
    judge: Judge,
    fetch_page: FetchPage,
    manifest: Manifest,
    budget: Budget,
) -> ScoreReport:
    """Rate every URL in the manifest, grouped by page type."""
    scored: list[ScoredPage] = []
    for page_type, urls in manifest.page_types.items():
        for url in urls:
            page = read_page(fetch_page, url)
            budget.check(len(page.text))
            score, usage = judge.score(page)
            budget.record(usage)
            scored.append(ScoredPage(page_type=page_type, page=page, score=score))
    return ScoreReport(name=manifest.name, pages=tuple(scored), usage=budget.usage)


def compare_manifest(
    judge: Judge,
    fetch_page: FetchPage,
    manifest: Manifest,
    budget: Budget,
) -> CompareReport:
    """Judge every pair in both orders, ``samples`` times each, and tally."""
    tallies = [
        _tally_pair(judge, read_page(fetch_page, a), read_page(fetch_page, b), manifest.samples, budget)
        for a, b in manifest.pairs
    ]
    return CompareReport(name=manifest.name, tallies=tuple(tallies), usage=budget.usage)


def _tally_pair(judge: Judge, a: PageText, b: PageText, samples: int, budget: Budget) -> CompareTally:
    wins = {Winner.FIRST: 0, Winner.SECOND: 0, Winner.TIE: 0}
    for _ in range(samples):
        for swapped in (False, True):
            first, second = (b, a) if swapped else (a, b)
            budget.check(len(first.text) + len(second.text))
            verdict, usage = judge.compare(first, second)
            budget.record(usage)
            # The judge answered about presentation order; map it back to the pair.
            wins[verdict.winner.flipped if swapped else verdict.winner] += 1
    return CompareTally(
        a=a.url,
        b=b.url,
        a_wins=wins[Winner.FIRST],
        b_wins=wins[Winner.SECOND],
        ties=wins[Winner.TIE],
        samples=sum(wins.values()),
    )


def read_page(fetch_page: FetchPage, url: str) -> PageText:
    """Fetch one page as the steward and reduce it to visible text.

    Anything short of a served 200 is a :class:`JudgeReadError`: a challenged
    or missing page must never reach the model and come back as a low score.
    """
    try:
        result = fetch_page(url)
    except OSError as exc:
        raise JudgeReadError(f"{url} could not be fetched: {exc}") from exc
    if result.challenged:
        raise JudgeReadError(
            f"{url} was met with a Cloudflare challenge — the probe token is not being honoured, "
            "so the challenge page, not the page, would have been judged"
        )
    if result.status != 200:
        raise JudgeReadError(f"{url} answered HTTP {result.status}")
    return PageText(url=url, title=result.title, text=visible_text(result.body))


__all__ = [
    "Budget",
    "BudgetExceeded",
    "CompareReport",
    "FetchPage",
    "ScoreReport",
    "ScoredPage",
    "compare_manifest",
    "read_page",
    "score_manifest",
]

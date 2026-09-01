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

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from oversteward.judge.extract import visible_text
from oversteward.judge.models import (
    NO_USAGE,
    CompareTally,
    JudgeReadError,
    Manifest,
    PageText,
    QuestionTally,
    Rubric,
    RubricScore,
    SideGroundedness,
    Usage,
    Verdict,
    Winner,
    facts_json,
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
    rubric: Rubric = Rubric.DESIGN


@dataclass(frozen=True, slots=True)
class CompareReport:
    name: str
    tallies: tuple[CompareTally, ...]
    usage: Usage
    rubric: Rubric = Rubric.DESIGN


def score_manifest(
    judge: Judge,
    fetch_page: FetchPage,
    manifest: Manifest,
    budget: Budget,
    ground_truth: Mapping[str, Mapping] | None = None,
) -> ScoreReport:
    """Rate every URL in the manifest, grouped by page type.

    ``ground_truth`` is already resolved — url to facts — because a fixture path
    that does not exist has to fail before the first call, not partway through a
    billed run. A URL the operator supplied no facts for is judged on the rubric
    alone; it never silently becomes a page with nothing to support it.
    """
    facts_by_url = ground_truth or {}
    scored: list[ScoredPage] = []
    for page_type, urls in manifest.page_types.items():
        for url in urls:
            page = read_page(fetch_page, url)
            facts = facts_by_url.get(url)
            budget.check(len(page.text) + _facts_chars(facts))
            score, usage = judge.score(page, rubric=manifest.rubric, ground_truth=facts)
            budget.record(usage)
            scored.append(ScoredPage(page_type=page_type, page=page, score=score))
    return ScoreReport(
        name=manifest.name,
        pages=tuple(scored),
        usage=budget.usage,
        rubric=manifest.rubric,
    )


def _facts_chars(facts: Mapping | None) -> int:
    """Ground truth rides in the same prompt, so it counts toward the estimate.

    Rendered exactly as the prompt renders it: an estimate that charged for less
    than the call actually sends would let a call through a cap it had not cleared.
    """
    return 0 if facts is None else len(facts_json(facts))


def compare_manifest(
    judge: Judge,
    fetch_page: FetchPage,
    manifest: Manifest,
    budget: Budget,
    ground_truth: Mapping[str, Mapping] | None = None,
) -> CompareReport:
    """Judge every pair in both orders, ``samples`` times each, and tally.

    ``ground_truth`` is already resolved — url to facts — for the same reason
    :func:`score_manifest` takes it resolved: a fixture path that does not exist
    has to fail before the first call, not partway through a billed run. A pair
    is judged against facts only when **both** its URLs have them.
    """
    facts_by_url = ground_truth or {}
    _refuse_asymmetric_truth(manifest.pairs, facts_by_url)
    tallies = [
        _tally_pair(
            judge,
            (read_page(fetch_page, a), read_page(fetch_page, b)),
            manifest,
            budget,
            _pair_facts(a, b, facts_by_url),
        )
        for a, b in manifest.pairs
    ]
    return CompareReport(
        name=manifest.name,
        tallies=tuple(tallies),
        usage=budget.usage,
        rubric=manifest.rubric,
    )


def _refuse_asymmetric_truth(
    pairs: tuple[tuple[str, str], ...],
    facts_by_url: Mapping[str, Mapping],
) -> None:
    """A pair with facts for one side only is a misconfiguration, not a run.

    Raised before the first page is fetched and long before the first call. The
    checked page's inventions would be listed and the unchecked page credited
    with none, so the variant that made things up could win the groundedness
    reading by having no ground truth at all.
    """
    for a, b in pairs:
        unchecked = [url for url in (a, b) if url not in facts_by_url]
        if len(unchecked) == 1:
            raise JudgeReadError(
                f"the pair {a} vs {b} carries ground truth for one side only — {unchecked[0]} has "
                "none. Supply facts for both sides or neither; no call was issued."
            )


def _pair_facts(a: str, b: str, facts_by_url: Mapping[str, Mapping]) -> tuple[Mapping, Mapping] | None:
    """Both sides' facts, in pair order — or nothing, when the pair carries none."""
    if a in facts_by_url and b in facts_by_url:
        return (facts_by_url[a], facts_by_url[b])
    return None


def _tally_pair(
    judge: Judge,
    pair: tuple[PageText, PageText],
    manifest: Manifest,
    budget: Budget,
    facts: tuple[Mapping, Mapping] | None,
) -> CompareTally:
    a, b = pair
    counts = _PairCounts()
    for _ in range(manifest.samples):
        for swapped in (False, True):
            first, second = (b, a) if swapped else (a, b)
            budget.check(len(first.text) + len(second.text) + _pair_facts_chars(facts))
            verdict, usage = judge.compare(
                first, second, rubric=manifest.rubric, ground_truth=_as_presented(facts, swapped)
            )
            budget.record(usage)
            # The judge answered about presentation order; map it back to the pair.
            counts.add(verdict.flipped if swapped else verdict)
    return counts.tally(a.url, b.url, grounded=facts is not None)


def _as_presented(
    facts: tuple[Mapping, Mapping] | None,
    swapped: bool,
) -> tuple[Mapping, Mapping] | None:
    """The pair's facts in the order the pages are shown, so each side keeps its own."""
    if facts is None:
        return None
    return (facts[1], facts[0]) if swapped else facts


def _pair_facts_chars(facts: tuple[Mapping, Mapping] | None) -> int:
    """Both sides' facts ride in the one prompt, so both count toward the estimate."""
    return 0 if facts is None else sum(_facts_chars(side) for side in facts)


@dataclass
class _PairCounts:
    """One pair's judgements, accumulated after each is mapped back to pair order."""

    wins: dict[Winner, int] = field(default_factory=lambda: dict.fromkeys(Winner, 0))
    per_question: dict[str, dict[Winner, int]] = field(default_factory=dict)
    a_claims: list[str] = field(default_factory=list)
    b_claims: list[str] = field(default_factory=list)

    def add(self, verdict: Verdict) -> None:
        self.wins[verdict.winner] += 1
        for name, pick in verdict.preferences.items():
            self.per_question.setdefault(name, dict.fromkeys(Winner, 0))[pick] += 1
        _merge_claims(self.a_claims, verdict.first_claims)
        _merge_claims(self.b_claims, verdict.second_claims)

    def tally(self, a_url: str, b_url: str, *, grounded: bool) -> CompareTally:
        return CompareTally(
            a=a_url,
            b=b_url,
            a_wins=self.wins[Winner.FIRST],
            b_wins=self.wins[Winner.SECOND],
            ties=self.wins[Winner.TIE],
            samples=sum(self.wins.values()),
            per_question={name: _question_tally(c) for name, c in self.per_question.items()},
            groundedness=(
                (
                    SideGroundedness(url=a_url, unsupported_claims=tuple(self.a_claims)),
                    SideGroundedness(url=b_url, unsupported_claims=tuple(self.b_claims)),
                )
                if grounded
                else ()
            ),
        )


def _question_tally(counts: Mapping[Winner, int]) -> QuestionTally:
    return QuestionTally(
        a_wins=counts[Winner.FIRST], b_wins=counts[Winner.SECOND], ties=counts[Winner.TIE]
    )


def _merge_claims(seen: list[str], claims: tuple[str, ...]) -> None:
    """Union across orderings and samples, in the order the claims were first raised.

    A claim the judge raised in one ordering and not the other is still a claim
    an operator has to look at, so the readings are unioned rather than
    intersected; a claim quoted identically twice is one finding, not two, or
    the score would fall for repetition.
    """
    seen.extend(claim for claim in claims if claim not in seen)


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

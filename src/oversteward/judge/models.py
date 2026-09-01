# ABOUTME: Shapes the judge speaks in — a page's text, a rubric score, a pairwise verdict, a spend.
# ABOUTME: Pure data and pricing arithmetic; no I/O, no network, no environment.

"""The vocabulary of the quality-rater pass.

Every dimension is scored **1-5 with higher being better**, including
``thin_smell`` — read it as "freedom from thin/doorway smell", so a doorway page
scores 1 and a substantial one scores 5. A rubric where some dimensions invert
is a rubric nobody can read a report from.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

#: The six dimensions, in the order a report renders them.
DIMENSIONS: tuple[str, ...] = (
    "intent_match",
    "eeat",
    "unique_ratio",
    "thin_smell",
    "readability",
    "answers_query",
)

#: What each dimension asks, verbatim, so the prompt and the report agree.
DIMENSION_QUESTIONS: Mapping[str, str] = {
    "intent_match": "Does the content above the fold match the search intent the title implies?",
    "eeat": "Are there experience, expertise, authoritativeness and trust signals — named sources, "
    "figures, dates, an identifiable publisher?",
    "unique_ratio": "How much of the page is unique substance rather than boilerplate, navigation "
    "and repeated template text?",
    "thin_smell": "Freedom from thin/doorway smell: 5 = substantial original content, "
    "1 = a keyword-stuffed doorway with nothing a reader could not guess from the title.",
    "readability": "Is it clear, well structured and readable by a non-expert?",
    "answers_query": "Does it actually answer the question its title promises, on the page, "
    "without requiring a signup or another click?",
}

#: The seeker rubric's dimensions, in the order a report renders them: the five
#: questions the demand research showed a grant seeker brings to Google, then
#: whether a non-expert can read the answers off the page.
SEEKER_DIMENSIONS: tuple[str, ...] = (
    "can_i_apply",
    "typical_giving",
    "who_they_fund",
    "when_to_apply",
    "where_to_apply",
    "clarity",
)

#: What each seeker dimension asks, verbatim, so the prompt and the report agree.
SEEKER_QUESTIONS: Mapping[str, str] = {
    "can_i_apply": "Can I apply? Does the page state plainly who is eligible, and whether "
    "unsolicited applications are accepted at all?",
    "typical_giving": "What do they typically give? Are grant sizes, total giving and what a "
    "realistic ask looks like on the page?",
    "who_they_fund": "Who do they fund, and are they like me? Are named grantees, causes and "
    "organization sizes shown, so a reader can tell whether they resemble them?",
    "when_to_apply": "When? Are deadlines, board meeting dates or the funder's own cycle stated, "
    "with the year they apply to?",
    "where_to_apply": "Where? Is the geography funded stated, and where an application actually "
    "goes — address, portal or contact?",
    "clarity": "Is all of that clear to a non-expert reader — someone running a small "
    "nonprofit, not a professional grant writer?",
}

#: The dimension added to whichever rubric ran, when the manifest supplied ground
#: truth. It is never in a rubric's own dimensions: the model does not score it.
GROUNDEDNESS = "groundedness"

_MIN_SCORE = 1
_MAX_SCORE = 5


class Rubric(StrEnum):
    """Which questions a page is scored against.

    ``design`` asks whether this is a good page. ``seeker`` asks whether it
    answers the questions a grant seeker actually arrives with. They are two
    instruments, not two settings, so every report names the one it ran.
    """

    DESIGN = "design"
    SEEKER = "seeker"

    @property
    def dimensions(self) -> tuple[str, ...]:
        """The dimensions this rubric scores, in render order."""
        return DIMENSIONS if self is Rubric.DESIGN else SEEKER_DIMENSIONS

    @property
    def questions(self) -> Mapping[str, str]:
        """What each of this rubric's dimensions asks."""
        return DIMENSION_QUESTIONS if self is Rubric.DESIGN else SEEKER_QUESTIONS


def groundedness_score(unsupported_claims: int) -> int:
    """Map a count of unsupported claims onto the 1-5 scale — code, never the model.

    An LLM asked "how grounded is this page" rewards the page that sounds most
    confident, which is precisely the failure an enrichment A/B has to be
    protected from. So the model is asked only to *list* what the ground truth
    cannot support, and the arithmetic below turns that list into a score: no
    unsupported claim is a 5, and each one costs a point down to the floor.
    """
    if unsupported_claims < 0:
        raise ValueError("a count of unsupported claims cannot be negative")
    return max(_MIN_SCORE, _MAX_SCORE - unsupported_claims)


def facts_json(facts: Mapping) -> str:
    """The one rendering of a ground-truth payload.

    Named once because two callers must agree on it: the prompt that carries the
    facts to the model, and the budget estimate that has to charge for them.
    """
    return json.dumps(facts, indent=2, sort_keys=True, default=str)

#: https://ai.google.dev/gemini-api/docs/pricing as of 2026-08-31. These rates
#: run through 2026-12-31 and double on 2027-01-01 — when that date passes,
#: these two constants are what must change.
INPUT_USD_PER_MTOK = 0.75
OUTPUT_USD_PER_MTOK = 3.75

_PER_MILLION = 1_000_000


class JudgeReadError(RuntimeError):
    """The judge, or a page it needed, could not be read.

    Deliberately distinct from "the page scored badly": a page that could not
    be fetched, and a page that was fetched and judged thin, must never render
    the same.
    """


class Winner(StrEnum):
    """Which of the two pages *as presented* the judge preferred.

    Positional on purpose. The judge never learns which URL is "A" — the
    service shows each pair in both orders and maps the answer back, so a model
    that simply favours whatever it read first cannot produce a sweep.
    """

    FIRST = "first"
    SECOND = "second"
    TIE = "tie"

    @property
    def flipped(self) -> Winner:
        """The same verdict, read against the opposite presentation order."""
        if self is Winner.FIRST:
            return Winner.SECOND
        if self is Winner.SECOND:
            return Winner.FIRST
        return Winner.TIE


@dataclass(frozen=True, slots=True)
class PageText:
    """A live page reduced to what a rater would actually read."""

    url: str
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class Dimension:
    """One rubric dimension: a 1-5 score and the one line that justifies it."""

    score: int
    reason: str


@dataclass(frozen=True, slots=True)
class RubricScore:
    """One page's scores, under whichever rubric asked the questions.

    ``scores`` is keyed and ordered as the rubric renders, so a prompt and a
    report walk the same sequence. ``unsupported_claims`` is empty for an
    ungrounded run; for a grounded one it is the *finding*, and the
    ``groundedness`` dimension is derived from its length rather than from the
    model's own opinion of how grounded it was.
    """

    url: str
    scores: Mapping[str, Dimension]
    rubric: Rubric = Rubric.DESIGN
    unsupported_claims: tuple[str, ...] = ()

    def __getattr__(self, name: str) -> Dimension:
        """Read one dimension by name — ``score.thin_smell`` reads ``scores``."""
        try:
            return object.__getattribute__(self, "scores")[name]
        except (AttributeError, KeyError):
            raise AttributeError(name) from None

    @property
    def dimensions(self) -> dict[str, Dimension]:
        return dict(self.scores)

    @property
    def mean(self) -> float:
        return sum(d.score for d in self.scores.values()) / len(self.scores)

    @classmethod
    def from_payload(
        cls,
        url: str,
        payload: object,
        *,
        rubric: Rubric = Rubric.DESIGN,
        grounded: bool = False,
    ) -> RubricScore:
        """Parse a judge's answer strictly — anything short of the full rubric is a read error."""
        if not isinstance(payload, Mapping):
            raise JudgeReadError(f"the judge answered {type(payload).__name__}, not a JSON object")
        scores = {name: _dimension(payload, name) for name in rubric.dimensions}
        claims: tuple[str, ...] = ()
        if grounded:
            claims = _unsupported_claims(payload)
            scores[GROUNDEDNESS] = Dimension(
                score=groundedness_score(len(claims)),
                reason=_groundedness_reason(len(claims)),
            )
        return cls(url=url, scores=scores, rubric=rubric, unsupported_claims=claims)


def _unsupported_claims(payload: Mapping) -> tuple[str, ...]:
    """The claims the ground truth could not support.

    A missing list is a read error, never an empty one. Ground truth was
    supplied, so "the judge found nothing" and "the judge said nothing" must not
    both come out as a perfect groundedness score — that is the shape of a
    check satisfied by doing nothing.
    """
    claims = payload.get("unsupported_claims")
    if isinstance(claims, str) or not isinstance(claims, Sequence):
        raise JudgeReadError(
            "the judge's answer carries no unsupported_claims list, but ground truth was supplied "
            "— an absent list cannot be read as a page whose every claim is supported"
        )
    return tuple(str(claim).strip() for claim in claims)


def _groundedness_reason(count: int) -> str:
    """The deterministic justification line — the claims themselves are the finding."""
    if not count:
        return "every factual claim on the page is supported by the ground truth"
    return f"{count} claim(s) the ground truth does not support"


def _dimension(payload: Mapping, name: str) -> Dimension:
    entry = payload.get(name)
    if not isinstance(entry, Mapping):
        raise JudgeReadError(f"the judge's answer is missing the {name} dimension")
    score = entry.get("score")
    if not isinstance(score, int) or isinstance(score, bool) or not _MIN_SCORE <= score <= _MAX_SCORE:
        raise JudgeReadError(f"{name} scored {score!r}, which is not an integer 1-5")
    return Dimension(score=score, reason=str(entry.get("reason", "")).strip())


@dataclass(frozen=True, slots=True)
class Verdict:
    """Which presented page won, and why, in one line."""

    winner: Winner
    reason: str

    @classmethod
    def from_payload(cls, payload: object) -> Verdict:
        if not isinstance(payload, Mapping):
            raise JudgeReadError(f"the judge answered {type(payload).__name__}, not a JSON object")
        raw = str(payload.get("winner", "")).strip().lower()
        try:
            winner = Winner(raw)
        except ValueError:
            raise JudgeReadError(
                f"the judge named winner {raw!r}; expected one of first, second, tie"
            ) from None
        return cls(winner=winner, reason=str(payload.get("reason", "")).strip())


@dataclass(frozen=True, slots=True)
class Usage:
    """What one call cost, from the token counts the API reported."""

    prompt_tokens: int
    output_tokens: int
    cost_usd: float

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


def usage_for(prompt_tokens: int, output_tokens: int) -> Usage:
    """Price a call at the published Gemini Flash rates."""
    cost = (prompt_tokens * INPUT_USD_PER_MTOK + output_tokens * OUTPUT_USD_PER_MTOK) / _PER_MILLION
    return Usage(prompt_tokens=prompt_tokens, output_tokens=output_tokens, cost_usd=cost)


NO_USAGE = Usage(prompt_tokens=0, output_tokens=0, cost_usd=0.0)


@dataclass(frozen=True, slots=True)
class CompareTally:
    """How one pair fared across every ordering and sample."""

    a: str
    b: str
    a_wins: int
    b_wins: int
    ties: int
    samples: int


@dataclass(frozen=True, slots=True)
class Manifest:
    """What the operator asked to be judged.

    ``samples`` is per ordering, so a pair costs ``2 * samples`` calls.
    """

    name: str
    samples: int
    page_types: Mapping[str, tuple[str, ...]]
    pairs: tuple[tuple[str, str], ...]
    rubric: Rubric = Rubric.DESIGN
    #: url -> the facts themselves, or a path to the JSON fixture holding them.
    #: Unresolved on purpose: reading a path is I/O, which this module does not do.
    ground_truth: Mapping[str, Mapping | str] = field(default_factory=dict)


DEFAULT_SAMPLES = 3


def manifest_from_mapping(data: Mapping, *, name: str = "") -> Manifest:
    """Read a parsed YAML document into a :class:`Manifest`.

    Every shape complaint is raised here, at the operator's file boundary, naming its key.
    """
    samples = int(data.get("samples", DEFAULT_SAMPLES))
    if samples < 1:
        raise ValueError("samples must be at least 1")
    page_types: dict[str, tuple[str, ...]] = {}
    for key, urls in (data.get("page_types") or {}).items():
        if isinstance(urls, str) or not isinstance(urls, Sequence):
            raise ValueError(f"page_types.{key} must be a list of URLs")
        page_types[str(key)] = tuple(str(url) for url in urls)
    ground_truth: dict[str, Mapping | str] = {}
    for url, entry in (data.get("ground_truth") or {}).items():
        if not isinstance(entry, Mapping | str):
            raise ValueError(f"ground_truth.{url} must be facts, or a path to a JSON file")
        ground_truth[str(url)] = entry
    raw_pairs = data.get("pairs") or []
    if isinstance(raw_pairs, str) or not isinstance(raw_pairs, Sequence):
        raise ValueError("pairs must be a list")
    pairs: list[tuple[str, str]] = []
    for item in raw_pairs:
        if isinstance(item, str) or not isinstance(item, Sequence) or len(item) != 2:
            raise ValueError("each entry of pairs must be exactly two URLs")
        pairs.append((str(item[0]), str(item[1])))
    return Manifest(
        name or str(data.get("name", "unnamed")), samples, page_types, tuple(pairs),
        rubric=_rubric_of(data), ground_truth=ground_truth,
    )


def _rubric_of(data: Mapping) -> Rubric:
    """The named rubric, defaulting to ``design`` so an old manifest is unchanged."""
    raw = str(data.get("rubric", Rubric.DESIGN.value)).strip().lower()
    try:
        return Rubric(raw)
    except ValueError:
        known = ", ".join(rubric.value for rubric in Rubric)
        raise ValueError(f"rubric must be one of {known}; got {raw!r}") from None


__all__ = [
    "DIMENSIONS",
    "DIMENSION_QUESTIONS",
    "GROUNDEDNESS",
    "INPUT_USD_PER_MTOK",
    "NO_USAGE",
    "OUTPUT_USD_PER_MTOK",
    "SEEKER_DIMENSIONS",
    "SEEKER_QUESTIONS",
    "CompareTally",
    "Dimension",
    "JudgeReadError",
    "Manifest",
    "PageText",
    "Rubric",
    "RubricScore",
    "Usage",
    "Verdict",
    "Winner",
    "facts_json",
    "groundedness_score",
    "manifest_from_mapping",
    "usage_for",
]

# ABOUTME: Shapes the judge speaks in — a page's text, a rubric score, a pairwise verdict, a spend.
# ABOUTME: Pure data and pricing arithmetic; no I/O, no network, no environment.

"""The vocabulary of the quality-rater pass.

Every dimension is scored **1-5 with higher being better**, including
``thin_smell`` — read it as "freedom from thin/doorway smell", so a doorway page
scores 1 and a substantial one scores 5. A rubric where some dimensions invert
is a rubric nobody can read a report from.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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

_MIN_SCORE = 1
_MAX_SCORE = 5

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
    """The six dimensions for one page."""

    url: str
    intent_match: Dimension
    eeat: Dimension
    unique_ratio: Dimension
    thin_smell: Dimension
    readability: Dimension
    answers_query: Dimension

    @property
    def dimensions(self) -> dict[str, Dimension]:
        return {name: getattr(self, name) for name in DIMENSIONS}

    @property
    def mean(self) -> float:
        return sum(d.score for d in self.dimensions.values()) / len(DIMENSIONS)

    @classmethod
    def from_payload(cls, url: str, payload: object) -> RubricScore:
        """Parse a judge's answer strictly — anything short of the full rubric is a read error."""
        if not isinstance(payload, Mapping):
            raise JudgeReadError(f"the judge answered {type(payload).__name__}, not a JSON object")
        return cls(url=url, **{name: _dimension(payload, name) for name in DIMENSIONS})


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


DEFAULT_SAMPLES = 3


def manifest_from_mapping(data: Mapping, *, name: str = "") -> Manifest:
    """Read a parsed YAML document into a :class:`Manifest`.

    Every shape complaint is raised here, at the boundary the operator's file
    crosses, so a malformed manifest names the key it came from.
    """
    samples = int(data.get("samples", DEFAULT_SAMPLES))
    if samples < 1:
        raise ValueError("samples must be at least 1")
    page_types: dict[str, tuple[str, ...]] = {}
    for key, urls in (data.get("page_types") or {}).items():
        if isinstance(urls, str) or not isinstance(urls, Sequence):
            raise ValueError(f"page_types.{key} must be a list of URLs")
        page_types[str(key)] = tuple(str(url) for url in urls)
    raw_pairs = data.get("pairs") or []
    if isinstance(raw_pairs, str) or not isinstance(raw_pairs, Sequence):
        raise ValueError("pairs must be a list")
    pairs: list[tuple[str, str]] = []
    for item in raw_pairs:
        if isinstance(item, str) or not isinstance(item, Sequence) or len(item) != 2:
            raise ValueError("each entry of pairs must be exactly two URLs")
        pairs.append((str(item[0]), str(item[1])))
    manifest_name = name or str(data.get("name", "unnamed"))
    return Manifest(manifest_name, samples, page_types, tuple(pairs))


__all__ = [
    "DIMENSIONS",
    "DIMENSION_QUESTIONS",
    "INPUT_USD_PER_MTOK",
    "NO_USAGE",
    "OUTPUT_USD_PER_MTOK",
    "CompareTally",
    "Dimension",
    "JudgeReadError",
    "Manifest",
    "PageText",
    "RubricScore",
    "Usage",
    "Verdict",
    "Winner",
    "manifest_from_mapping",
    "usage_for",
]

# ABOUTME: Fakes for the judge tests — a scripted Judge and a scripted google-genai client.
# ABOUTME: Never a mock asserted against; each fake records what it was asked and answers plainly.

from __future__ import annotations

import json
from dataclasses import dataclass, field

from collections.abc import Mapping

from oversteward.judge.models import (
    PageText,
    Rubric,
    RubricScore,
    Usage,
    Verdict,
    Winner,
)


def dimension_payload(
    value: int = 4,
    reason: str = "ok",
    rubric: Rubric = Rubric.DESIGN,
) -> dict:
    """The per-dimension mapping a rubric response carries."""
    return {name: {"score": value, "reason": reason} for name in rubric.dimensions}


@dataclass
class FakeJudge:
    """A judge with a fixed opinion, which records every page it was shown.

    ``compare`` always names the page shown *first*, on every question. A tally
    that reports a sweep for one URL is therefore reporting position bias, not
    quality. ``claims_by_url`` is keyed by URL rather than by position, as a
    real judge's reading is: a claim must follow its own page through the swap.
    """

    winner: Winner = Winner.FIRST
    usage: Usage = field(default_factory=lambda: Usage(1000, 100, 0.001125))
    score_value: int = 3
    #: What this judge reports it could not support, whenever it is handed facts.
    unsupported_claims: tuple[str, ...] = ()
    #: The same, per compared URL — what this judge says that page invented.
    claims_by_url: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    scored: list[str] = field(default_factory=list)
    rubrics: list[Rubric] = field(default_factory=list)
    grounded: list[str] = field(default_factory=list)
    compared: list[tuple[str, str]] = field(default_factory=list)
    compare_rubrics: list[Rubric] = field(default_factory=list)
    compare_grounded: list[tuple[str, str]] = field(default_factory=list)

    @property
    def calls(self) -> int:
        return len(self.scored) + len(self.compared)

    def score(
        self,
        page: PageText,
        *,
        rubric: Rubric = Rubric.DESIGN,
        ground_truth: Mapping | None = None,
    ) -> tuple[RubricScore, Usage]:
        self.scored.append(page.url)
        self.rubrics.append(rubric)
        payload = dimension_payload(self.score_value, "fixed", rubric)
        if ground_truth is not None:
            self.grounded.append(page.url)
            payload["unsupported_claims"] = list(self.unsupported_claims)
        score = RubricScore.from_payload(
            page.url, payload, rubric=rubric, grounded=ground_truth is not None
        )
        return score, self.usage

    def compare(
        self,
        a: PageText,
        b: PageText,
        *,
        rubric: Rubric = Rubric.DESIGN,
        ground_truth: tuple[Mapping, Mapping] | None = None,
    ) -> tuple[Verdict, Usage]:
        self.compared.append((a.url, b.url))
        self.compare_rubrics.append(rubric)
        preferences = {}
        if rubric is not Rubric.DESIGN:
            preferences = dict.fromkeys(rubric.dimensions, self.winner)
        if ground_truth is None:
            return Verdict(winner=self.winner, reason="fixed", preferences=preferences), self.usage
        self.compare_grounded.append((a.url, b.url))
        return Verdict(
            winner=self.winner,
            reason="fixed",
            preferences=preferences,
            first_claims=tuple(self.claims_by_url.get(a.url, ())),
            second_claims=tuple(self.claims_by_url.get(b.url, ())),
        ), self.usage


class FakeResponse:
    """The shape ``google.genai`` returns: ``.text`` plus ``.usage_metadata``."""

    def __init__(self, text: str, prompt_tokens: int = 1000, output_tokens: int = 100):
        self.text = text
        self.usage_metadata = FakeUsageMetadata(prompt_tokens, output_tokens)


@dataclass
class FakeUsageMetadata:
    prompt_token_count: int
    candidates_token_count: int


class FakeModels:
    def __init__(self, responses: list[FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if not self._responses:
            raise AssertionError("the fake client was called more times than it was scripted for")
        return self._responses.pop(0)


class FakeGenaiClient:
    """Stands in for ``google.genai.Client`` — one attribute, ``models``."""

    def __init__(self, responses: list[FakeResponse]):
        self.models = FakeModels(responses)


def rubric_json(value: int = 4, reason: str = "ok") -> str:
    return json.dumps(dimension_payload(value, reason))

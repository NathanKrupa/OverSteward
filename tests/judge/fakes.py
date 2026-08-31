# ABOUTME: Fakes for the judge tests — a scripted Judge and a scripted google-genai client.
# ABOUTME: Never a mock asserted against; each fake records what it was asked and answers plainly.

from __future__ import annotations

import json
from dataclasses import dataclass, field

from oversteward.judge.models import (
    DIMENSIONS,
    PageText,
    RubricScore,
    Usage,
    Verdict,
    Winner,
)


def dimension_payload(value: int = 4, reason: str = "ok") -> dict:
    """The six-dimension mapping a rubric response carries."""
    return {name: {"score": value, "reason": reason} for name in DIMENSIONS}


@dataclass
class FakeJudge:
    """A judge with a fixed opinion, which records every page it was shown.

    ``compare`` always names the page shown *first*. A tally that reports a
    sweep for one URL is therefore reporting position bias, not quality.
    """

    winner: Winner = Winner.FIRST
    usage: Usage = field(default_factory=lambda: Usage(1000, 100, 0.001125))
    score_value: int = 3
    scored: list[str] = field(default_factory=list)
    compared: list[tuple[str, str]] = field(default_factory=list)

    @property
    def calls(self) -> int:
        return len(self.scored) + len(self.compared)

    def score(self, page: PageText) -> tuple[RubricScore, Usage]:
        self.scored.append(page.url)
        return RubricScore.from_payload(page.url, dimension_payload(self.score_value, "fixed")), self.usage

    def compare(self, a: PageText, b: PageText) -> tuple[Verdict, Usage]:
        self.compared.append((a.url, b.url))
        return Verdict(winner=self.winner, reason="fixed"), self.usage


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

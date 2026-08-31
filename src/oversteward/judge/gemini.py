# ABOUTME: INNER connector for the Gemini API — one model call per rubric score or pairwise verdict.
# ABOUTME: Key injected via __init__; the client is injectable so tests never touch the network.

"""Ask Gemini to rate a page.

Gemini is the judge because it is the model most plausibly aligned with
Google's own helpful-content raters — this is a *pre-launch quality-rater
pass*, not a ranking predictor. The honest test is still Search Console after
launch.

Answers are requested as JSON (``response_mime_type``) and parsed strictly:
anything the rubric does not fully cover raises :class:`JudgeReadError`, so a
malformed answer can never be mistaken for a low score.
"""

from __future__ import annotations

import json
from typing import Any

from oversteward.judge.models import (
    DIMENSION_QUESTIONS,
    JudgeReadError,
    PageText,
    RubricScore,
    Usage,
    Verdict,
    usage_for,
)

#: The same anchor AG uses, so the two repos judge with one model.
DEFAULT_MODEL = "gemini-3.6-flash"

#: Page text is truncated before it is sent. A rater judges what is above and
#: just below the fold; the tail costs tokens and moves no verdict.
MAX_PAGE_CHARS = 12_000

_TEMPERATURE = 0.0

_RUBRIC_LINES = "\n".join(f"- {name}: {question}" for name, question in DIMENSION_QUESTIONS.items())

_SCORE_PROMPT = """You are a search quality rater assessing one web page.

Score the page on each dimension from 1 to 5, where **5 is always best**:

{rubric}

Answer with JSON only, in exactly this shape, with a one-line reason per
dimension (no more than 20 words each):

{{"intent_match": {{"score": 3, "reason": "..."}}, "eeat": {{"score": 3, "reason": "..."}},
 "unique_ratio": {{"score": 3, "reason": "..."}}, "thin_smell": {{"score": 3, "reason": "..."}},
 "readability": {{"score": 3, "reason": "..."}}, "answers_query": {{"score": 3, "reason": "..."}}}}

TITLE: {title}
URL: {url}

PAGE TEXT:
{text}
"""

_COMPARE_PROMPT = """You are a search quality rater comparing two web pages that
compete for the same search intent. Judge which better serves a person searching
for it: intent match, evidence of expertise, unique substance over boilerplate,
readability, and whether it actually answers the question.

Answer with JSON only: {{"winner": "first" | "second" | "tie", "reason": "one line, at most 25 words"}}

=== FIRST PAGE ===
TITLE: {first_title}
{first_text}

=== SECOND PAGE ===
TITLE: {second_title}
{second_text}
"""


def score_prompt(page: PageText) -> str:
    """The rubric prompt for one page, truncated to what a rater would read."""
    return _SCORE_PROMPT.format(
        rubric=_RUBRIC_LINES,
        title=page.title,
        url=page.url,
        text=page.text[:MAX_PAGE_CHARS],
    )


def compare_prompt(a: PageText, b: PageText) -> str:
    """The head-to-head prompt. Positional: neither page is told it is "A"."""
    return _COMPARE_PROMPT.format(
        first_title=a.title,
        first_text=a.text[:MAX_PAGE_CHARS],
        second_title=b.title,
        second_text=b.text[:MAX_PAGE_CHARS],
    )


def _default_client(api_key: str) -> Any:
    """Build the real google-genai client. Imported lazily so the unit tests,
    which inject a fake, never need the dependency present."""
    from google import genai  # noqa: PLC0415 — heavy optional import, only needed for a live call

    return genai.Client(api_key=api_key)


class GeminiJudge:
    """Talks to exactly one external system: the Gemini API.

    It holds no opinion about *which* pages to judge or what a tally means —
    that is the service's work. It turns one page (or one pair) into one call
    and one parsed answer.
    """

    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL, client: Any = None) -> None:
        if client is None and not api_key:
            raise ValueError("api_key must not be empty — build the judge via judge_from_env().")
        self._client = client if client is not None else _default_client(api_key)
        self._model = model

    def score(self, page: PageText) -> tuple[RubricScore, Usage]:
        """Rate one page on the six rubric dimensions."""
        payload, usage = _ask(self._client, self._model, score_prompt(page))
        return RubricScore.from_payload(page.url, payload), usage

    def compare(self, a: PageText, b: PageText) -> tuple[Verdict, Usage]:
        """Prefer one of two pages *as presented* — the caller owns the ordering."""
        payload, usage = _ask(self._client, self._model, compare_prompt(a, b))
        return Verdict.from_payload(payload), usage


def _ask(client: Any, model: str, prompt: str) -> tuple[object, Usage]:
    """One call, one parsed answer, priced. Anything else is a read error."""
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={"response_mime_type": "application/json", "temperature": _TEMPERATURE},
        )
    except Exception as exc:  # re-raised, never swallowed: the API's failure modes are many
        raise JudgeReadError(f"Gemini ({model}) could not be reached: {exc}") from exc
    return _parsed(response), _usage_of(response)


def _parsed(response: Any) -> object:
    """The JSON body of an answer, or a read error naming what came back instead."""
    text = getattr(response, "text", None)
    if not text:
        raise JudgeReadError("Gemini returned an empty answer")
    try:
        return json.loads(text)
    except ValueError as exc:
        raise JudgeReadError(f"Gemini's answer was not JSON: {text[:200]!r}") from exc


def _usage_of(response: Any) -> Usage:
    """Price the call from the counts the API reported, never from a guess."""
    metadata = getattr(response, "usage_metadata", None)
    prompt_tokens = int(getattr(metadata, "prompt_token_count", 0) or 0)
    output_tokens = int(getattr(metadata, "candidates_token_count", 0) or 0)
    return usage_for(prompt_tokens, output_tokens)


__all__ = ["DEFAULT_MODEL", "MAX_PAGE_CHARS", "GeminiJudge", "compare_prompt", "score_prompt"]

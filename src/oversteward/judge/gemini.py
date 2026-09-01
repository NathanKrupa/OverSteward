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
from collections.abc import Mapping
from typing import Any

from oversteward.judge.models import (
    FIRST_CLAIMS,
    SECOND_CLAIMS,
    JudgeReadError,
    PageText,
    Rubric,
    RubricScore,
    Usage,
    Verdict,
    facts_json,
    usage_for,
)

#: The same anchor AG uses, so the two repos judge with one model.
DEFAULT_MODEL = "gemini-3.6-flash"

#: Page text is truncated before it is sent. A rater judges what is above and
#: just below the fold; the tail costs tokens and moves no verdict.
MAX_PAGE_CHARS = 12_000

_TEMPERATURE = 0.0

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


_SEEKER_PROMPT = """You are assessing one web page on behalf of a grant seeker —
someone running a small nonprofit who found this page in a search and needs an
answer they can act on, not an impression.

Score the page on each dimension from 1 to 5, where **5 is always best**:

{rubric}

Answer with JSON only, in exactly this shape, with a one-line reason per
dimension (no more than 20 words each):

{shape}

TITLE: {title}
URL: {url}

PAGE TEXT:
{text}
"""

_SEEKER_COMPARE_PROMPT = """You are comparing two web pages on behalf of a grant
seeker — someone running a small nonprofit who found them in a search and needs
an answer they can act on, not an impression.

For each question below, say which page answers it better for that reader:

{rubric}

Answer with JSON only, in exactly this shape — "first", "second" or "tie" for
every question, then the overall preference and a one-line reason (at most 25
words):

{shape}

=== FIRST PAGE ===
TITLE: {first_title}
{first_text}

=== SECOND PAGE ===
TITLE: {second_title}
{second_text}
"""

#: Appended when the manifest supplied ground truth. It asks only for the list:
#: an LLM asked to score its own groundedness rewards the page that sounds most
#: confident, which is the fluent-fiction failure this dimension exists to catch.
_GROUND_TRUTH_BLOCK = """
GROUND TRUTH — the only facts about this subject you may treat as supported:

{facts}

In addition to the JSON keys above, include an "unsupported_claims" key: a list
of every factual claim the page makes that the ground truth above does not
support. Quote each claim in at most 15 words. If every claim is supported,
answer with an empty list. Do not score groundedness yourself — the list is the
finding.
"""

#: The pairwise form of the same block. The two sides carry their own facts and
#: their own list: a comparison that merged them would say which page invents
#: more without ever saying what either one invented.
_COMPARE_GROUND_TRUTH_BLOCK = """
GROUND TRUTH — the only facts about each page's subject you may treat as supported.

FOR THE FIRST PAGE:

{first_facts}

FOR THE SECOND PAGE:

{second_facts}

In addition to the JSON keys above, include "{first_key}" and "{second_key}":
for each page, the list of factual claims that page makes which its own ground
truth above does not support. Quote each claim in at most 15 words. If every
claim is supported, answer with an empty list. Keep the two lists separate and
do not score groundedness yourself — the lists are the finding.
"""


def score_prompt(
    page: PageText,
    *,
    rubric: Rubric = Rubric.DESIGN,
    ground_truth: Mapping | None = None,
) -> str:
    """The rubric prompt for one page, truncated to what a rater would read.

    The ``design`` prompt with no ground truth is frozen by a golden test: every
    round judged to date was scored against these exact bytes, so changing them
    changes the instrument rather than tweaking it.
    """
    template = _SCORE_PROMPT if rubric is Rubric.DESIGN else _SEEKER_PROMPT
    prompt = template.format(
        rubric=_rubric_lines(rubric),
        shape=_shape_line(rubric.dimensions),
        title=page.title,
        url=page.url,
        text=page.text[:MAX_PAGE_CHARS],
    )
    if ground_truth is None:
        return prompt
    return prompt + _GROUND_TRUTH_BLOCK.format(facts=facts_json(ground_truth))


def _rubric_lines(rubric: Rubric) -> str:
    """One line per dimension, verbatim from the rubric the report will render."""
    return "\n".join(f"- {name}: {question}" for name, question in rubric.questions.items())


def _shape_line(names: tuple[str, ...]) -> str:
    """The answer shape, generated from the dimensions rather than restated."""
    inner = ", ".join(f'"{name}": {{"score": 3, "reason": "..."}}' for name in names)
    return "{" + inner + "}"


def _preference_shape_line(names: tuple[str, ...]) -> str:
    """The comparison's answer shape — one preference per question, then the overall one."""
    inner = ", ".join(f'"{name}": "first"' for name in names)
    return "{" + inner + ', "winner": "first", "reason": "..."}'


def compare_prompt(
    a: PageText,
    b: PageText,
    *,
    rubric: Rubric = Rubric.DESIGN,
    ground_truth: tuple[Mapping, Mapping] | None = None,
) -> str:
    """The head-to-head prompt. Positional: neither page is told it is "A".

    The ``design`` prompt with no ground truth is frozen by a golden test — a
    manifest that names no rubric compares with exactly the bytes every round to
    date compared with. ``ground_truth`` is the facts for the two pages *in the
    order presented*, so the caller that swaps the pages swaps these too.
    """
    template = _COMPARE_PROMPT if rubric is Rubric.DESIGN else _SEEKER_COMPARE_PROMPT
    prompt = template.format(
        rubric=_rubric_lines(rubric),
        shape=_preference_shape_line(rubric.dimensions),
        first_title=a.title,
        first_text=a.text[:MAX_PAGE_CHARS],
        second_title=b.title,
        second_text=b.text[:MAX_PAGE_CHARS],
    )
    if ground_truth is None:
        return prompt
    first_facts, second_facts = ground_truth
    return prompt + _COMPARE_GROUND_TRUTH_BLOCK.format(
        first_facts=facts_json(first_facts),
        second_facts=facts_json(second_facts),
        first_key=FIRST_CLAIMS,
        second_key=SECOND_CLAIMS,
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

    def score(
        self,
        page: PageText,
        *,
        rubric: Rubric = Rubric.DESIGN,
        ground_truth: Mapping | None = None,
    ) -> tuple[RubricScore, Usage]:
        """Rate one page on ``rubric``'s dimensions, against ground truth if supplied."""
        prompt = score_prompt(page, rubric=rubric, ground_truth=ground_truth)
        payload, usage = _ask(self._client, self._model, prompt)
        score = RubricScore.from_payload(
            page.url, payload, rubric=rubric, grounded=ground_truth is not None
        )
        return score, usage

    def compare(
        self,
        a: PageText,
        b: PageText,
        *,
        rubric: Rubric = Rubric.DESIGN,
        ground_truth: tuple[Mapping, Mapping] | None = None,
    ) -> tuple[Verdict, Usage]:
        """Prefer one of two pages *as presented* — the caller owns the ordering.

        Under a rubric that asks per question the verdict carries one preference
        each; when both pages arrive with facts it also carries what neither
        page's own facts could support, one list per side.
        """
        prompt = compare_prompt(a, b, rubric=rubric, ground_truth=ground_truth)
        payload, usage = _ask(self._client, self._model, prompt)
        verdict = Verdict.from_payload(payload, rubric=rubric, grounded=ground_truth is not None)
        return verdict, usage


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

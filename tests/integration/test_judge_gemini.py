# ABOUTME: The negative fixture — the one test that proves the rubric can actually fail a page.
# ABOUTME: Key-gated and marked `integration`; a skip prints its reason and is never a pass.

"""Prove the judge can say *no*.

A rubric that has only ever been shown live pages measures the pages, not the
rubric (pr-workflow.md § False greens). This test hands the real
:class:`GeminiJudge` a deliberately thin, keyword-stuffed doorway page and
requires a low ``thin_smell`` — the dimension is scored 5 = substantial,
1 = doorway, so a judge that rated everything highly would fail here.

Run it deliberately, once, and read the cost line it prints::

    scripts/dev/with_test_env.py -- .venv/bin/pytest \\
        tests/integration/test_judge_gemini.py -m integration

The key is read from the **exported** environment only, never from ``.env``
behind your back — so an ordinary suite run cannot silently spend money.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from oversteward.judge.config import FALLBACK_KEY_VAR, GEMINI_KEY_VAR
from oversteward.judge.extract import visible_text
from oversteward.judge.gemini import GeminiJudge
from oversteward.judge.models import PageText

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "judge" / "thin_doorway.html"

#: A doorway page must land at or below this on ``thin_smell`` (5 = substantial).
_MAX_THIN_SMELL = 2

pytestmark = pytest.mark.integration


def _api_key() -> str:
    return os.environ.get(GEMINI_KEY_VAR, "") or os.environ.get(FALLBACK_KEY_VAR, "")


def test_a_keyword_stuffed_doorway_page_scores_low_on_thin_smell(capsys):
    key = _api_key()
    if not key:
        pytest.skip(
            f"SKIPPED, NOT PASSED: neither {GEMINI_KEY_VAR} nor {FALLBACK_KEY_VAR} is exported, "
            "so the rubric was never exercised against Gemini. Run via "
            "scripts/dev/with_test_env.py to supply it."
        )

    page = PageText(
        url="https://app.example.test/grants-for/housing-ohio/",
        title="Grants for Housing in Ohio | Apply Today",
        text=visible_text(FIXTURE.read_text(encoding="utf-8")),
    )
    judge = GeminiJudge(api_key=key)
    score, usage = judge.score(page)

    with capsys.disabled():
        print(
            f"\nthin_smell={score.thin_smell.score} ({score.thin_smell.reason})\n"
            f"cost=${usage.cost_usd:.6f} "
            f"prompt_tokens={usage.prompt_tokens} output_tokens={usage.output_tokens}"
        )

    assert score.thin_smell.score <= _MAX_THIN_SMELL, (
        f"the doorway fixture scored {score.thin_smell.score} on thin_smell — "
        "the rubric is not discriminating"
    )

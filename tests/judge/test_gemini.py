# ABOUTME: Tests the Gemini connector with an injected fake client — no network, no key.
# ABOUTME: A malformed answer is a read failure, never a silently-defaulted score.

from __future__ import annotations

import json

import pytest

from oversteward.judge.gemini import GeminiJudge
from oversteward.judge.models import JudgeReadError, PageText, Winner
from tests.judge.fakes import FakeGenaiClient, FakeResponse, dimension_payload, rubric_json

_PAGE = PageText(url="https://app.example.test/a/", title="A", text="Some page text.")
_OTHER = PageText(url="https://app.example.test/b/", title="B", text="Other page text.")


def _judge(responses):
    client = FakeGenaiClient(responses)
    return GeminiJudge(api_key="unused-because-client-is-injected", client=client), client


class TestScore:
    def test_six_dimensions_are_parsed_with_their_reasons(self):
        judge, _ = _judge([FakeResponse(rubric_json(value=4, reason="clear intent"))])
        score, _usage = judge.score(_PAGE)

        assert [d.score for d in score.dimensions.values()] == [4] * 6
        assert score.intent_match.reason == "clear intent"
        assert set(score.dimensions) == {
            "intent_match",
            "eeat",
            "unique_ratio",
            "thin_smell",
            "readability",
            "answers_query",
        }

    def test_json_mime_type_is_requested(self):
        judge, client = _judge([FakeResponse(rubric_json())])
        judge.score(_PAGE)
        assert client.models.calls[0]["config"]["response_mime_type"] == "application/json"

    def test_the_page_text_is_what_is_sent(self):
        judge, client = _judge([FakeResponse(rubric_json())])
        judge.score(_PAGE)
        assert "Some page text." in client.models.calls[0]["contents"]

    def test_usage_is_computed_from_the_reported_token_counts(self):
        judge, _ = _judge([FakeResponse(rubric_json(), prompt_tokens=2000, output_tokens=400)])
        _score, usage = judge.score(_PAGE)

        assert (usage.prompt_tokens, usage.output_tokens) == (2000, 400)
        # 2000 * $0.75/1M + 400 * $3.75/1M
        assert usage.cost_usd == pytest.approx(0.0015 + 0.0015)


class TestMalformedAnswers:
    def test_text_that_is_not_json_is_a_read_error(self):
        judge, _ = _judge([FakeResponse("I'm afraid I can't do that.")])
        with pytest.raises(JudgeReadError):
            judge.score(_PAGE)

    def test_a_missing_dimension_is_a_read_error(self):
        payload = dimension_payload()
        del payload["thin_smell"]
        judge, _ = _judge([FakeResponse(json.dumps(payload))])
        with pytest.raises(JudgeReadError, match="thin_smell"):
            judge.score(_PAGE)

    def test_a_score_outside_one_to_five_is_a_read_error(self):
        judge, _ = _judge([FakeResponse(rubric_json(value=9))])
        with pytest.raises(JudgeReadError, match="1-5"):
            judge.score(_PAGE)

    def test_an_unknown_winner_is_a_read_error(self):
        judge, _ = _judge([FakeResponse(json.dumps({"winner": "neither", "reason": "x"}))])
        with pytest.raises(JudgeReadError, match="winner"):
            judge.compare(_PAGE, _OTHER)


class TestCompare:
    def test_a_verdict_names_the_position_not_the_url(self):
        judge, client = _judge([FakeResponse(json.dumps({"winner": "second", "reason": "richer"}))])
        verdict, _usage = judge.compare(_PAGE, _OTHER)

        assert verdict.winner is Winner.SECOND
        assert verdict.reason == "richer"
        prompt = client.models.calls[0]["contents"]
        assert "Some page text." in prompt
        assert "Other page text." in prompt

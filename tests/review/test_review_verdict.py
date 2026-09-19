# ABOUTME: Tests for review_verdict — parsing and judging the reviewer's blocking verdict block.
# ABOUTME: A missing block, a malformed one, and a BLOCK must all be red; only a real PASS is green.

from __future__ import annotations

import pytest

from oversteward.review_verdict import (
    EXIT_COULD_NOT_LOOK,
    EXIT_OK,
    EXIT_VIOLATIONS,
    BLOCK,
    PASS,
    PASS_WITH_FINDINGS,
    MalformedVerdictError,
    MissingVerdictError,
    Verdict,
    judge,
    parse_verdict,
    render_template,
)


def _body(verdict: str = PASS, findings: int = 0, tokens: str = "41200", extra: str = "") -> str:
    return (
        "Closes #428\n\n## Summary\nSomething.\n\n"
        "## Adversarial review\n\n"
        "```reviewer-verdict\n"
        f"verdict: {verdict}\n"
        f"findings: {findings}\n"
        f"tokens: {tokens}\n"
        f"{extra}"
        "```\n\nmore prose\n"
    )


class TestParsing:
    def test_reads_the_three_required_keys(self):
        parsed = parse_verdict(_body(PASS_WITH_FINDINGS, 2, "1234"))
        assert parsed == Verdict(verdict=PASS_WITH_FINDINGS, findings=2, tokens=1234)

    def test_a_body_with_no_block_is_missing_not_malformed(self):
        with pytest.raises(MissingVerdictError):
            parse_verdict("Closes #428\n\nno review happened here\n")

    def test_prose_naming_the_verdict_words_is_not_a_verdict_block(self):
        # An author who writes "the reviewer said PASS" has not run the
        # reviewer. Only the fenced block counts.
        with pytest.raises(MissingVerdictError):
            parse_verdict("The adversarial reviewer returned PASS with 0 findings.\n")

    @pytest.mark.parametrize(
        "extra_removed",
        ["verdict", "findings", "tokens"],
    )
    def test_a_block_missing_a_required_key_is_malformed(self, extra_removed):
        body = _body()
        broken = "\n".join(
            line for line in body.splitlines() if not line.startswith(f"{extra_removed}:")
        )
        with pytest.raises(MalformedVerdictError):
            parse_verdict(broken)

    def test_an_unknown_verdict_word_is_malformed(self):
        with pytest.raises(MalformedVerdictError):
            parse_verdict(_body("LGTM"))

    def test_a_non_numeric_findings_count_is_malformed(self):
        with pytest.raises(MalformedVerdictError):
            parse_verdict(_body(PASS, "many"))

    def test_unknown_token_cost_is_allowed_because_it_is_not_always_reported(self):
        assert parse_verdict(_body(PASS, 0, "unknown")).tokens is None

    def test_a_second_block_is_refused_rather_than_the_first_silently_winning(self):
        doubled = _body(BLOCK, 3) + _body(PASS, 0)
        with pytest.raises(MalformedVerdictError):
            parse_verdict(doubled)


class TestInternalConsistency:
    def test_a_pass_claiming_findings_is_malformed(self):
        with pytest.raises(MalformedVerdictError):
            parse_verdict(_body(PASS, 2))

    def test_pass_with_findings_claiming_none_is_malformed(self):
        with pytest.raises(MalformedVerdictError):
            parse_verdict(_body(PASS_WITH_FINDINGS, 0))

    def test_a_block_must_name_at_least_one_finding(self):
        with pytest.raises(MalformedVerdictError):
            parse_verdict(_body(BLOCK, 0))


class TestJudge:
    def test_a_clean_pass_is_green(self):
        assert judge(_body(PASS, 0)) == (EXIT_OK, PASS)

    def test_pass_with_findings_is_green_because_findings_are_not_blockers(self):
        assert judge(_body(PASS_WITH_FINDINGS, 2))[0] == EXIT_OK

    def test_a_block_is_red(self):
        assert judge(_body(BLOCK, 1))[0] == EXIT_VIOLATIONS

    def test_a_missing_block_is_red_not_skipped(self):
        assert judge("no review block at all")[0] == EXIT_VIOLATIONS

    def test_a_malformed_block_is_red(self):
        assert judge(_body("LGTM"))[0] == EXIT_VIOLATIONS

    def test_an_unreadable_body_could_not_look_and_says_so_distinctly(self):
        assert judge(None)[0] == EXIT_COULD_NOT_LOOK

    def test_could_not_look_never_shares_an_exit_code_with_a_pass(self):
        assert EXIT_COULD_NOT_LOOK not in (EXIT_OK, EXIT_VIOLATIONS)


class TestTemplate:
    def test_the_rendered_template_is_itself_parseable(self):
        # A template the gate would reject teaches the wrong shape to every
        # author who copies it.
        parsed = parse_verdict(render_template(PASS_WITH_FINDINGS, findings=1, tokens=100))
        assert parsed.verdict == PASS_WITH_FINDINGS

    def test_the_template_placeholder_form_is_not_accepted_as_a_real_verdict(self):
        # A copy-pasted, unfilled template must not certify anything.
        with pytest.raises((MalformedVerdictError, MissingVerdictError)):
            parse_verdict(render_template(None, findings=None, tokens=None))

# ABOUTME: Tests for the stop-the-line rule — an open ci-red or dispatch-paused issue refuses dispatch.
# ABOUTME: Pure: IntakeIssues in, Allowed or Stopped out; the CLI's exit codes are tested in test_cli.

from __future__ import annotations

from oversteward.intake.line import Allowed, Stopped, declared_fixes, stop_line

from .conftest import issue

RED = issue(9, title="ci is red on PR #120", labels=("ci-red", "agent-finding"))
PLAIN = issue(4, title="tidy the settings page", labels=("ready-for-agent",))


def test_a_clear_line_allows_a_plain_issue():
    assert isinstance(stop_line(PLAIN, [PLAIN]), Allowed)


def test_an_open_ci_red_issue_stops_any_other_issue_and_names_itself():
    verdict = stop_line(PLAIN, [PLAIN, RED])
    assert isinstance(verdict, Stopped)
    assert any("aigranthelper#9" in reason for reason in verdict.reasons)


def test_the_ci_red_issue_itself_is_allowed():
    assert isinstance(stop_line(RED, [PLAIN, RED]), Allowed)


def test_an_issue_declaring_a_fix_of_the_open_ci_red_issue_is_allowed():
    fix = issue(4, labels=("ready-for-agent",), body="Restore the test.\n\nCloses #9\n")
    assert isinstance(stop_line(fix, [fix, RED]), Allowed)


def test_a_fix_declared_in_a_comment_is_allowed():
    assert isinstance(stop_line(PLAIN, [PLAIN, RED], comments=("Fixes #9 once merged",)), Allowed)


def test_a_fix_of_an_issue_that_is_not_ci_red_is_refused():
    other = issue(5, title="some other bug")
    false_fix = issue(4, labels=("ready-for-agent",), body="Resolves #5")
    verdict = stop_line(false_fix, [false_fix, other, RED])
    assert isinstance(verdict, Stopped)
    assert any("#9" in reason for reason in verdict.reasons)


def test_a_bare_mention_of_the_ci_red_issue_is_not_a_fix():
    mention = issue(4, body="Related to #9; see also #9.")
    assert isinstance(stop_line(mention, [mention, RED]), Stopped)


def test_dispatch_paused_stops_even_the_ci_red_issue():
    paused = issue(2, title="hold everything", labels=("dispatch-paused",))
    verdict = stop_line(RED, [RED, paused])
    assert isinstance(verdict, Stopped)
    assert any("aigranthelper#2" in reason and "dispatch-paused" in reason for reason in verdict.reasons)


def test_dispatch_paused_stops_a_declared_fix():
    paused = issue(2, labels=("dispatch-paused",))
    fix = issue(4, body="closes #9")
    assert isinstance(stop_line(fix, [fix, RED, paused]), Stopped)


def test_declared_fixes_reads_each_keyword_case_blind_and_ignores_cross_repo_refs():
    text = "CLOSES #1, fixes #2 and Resolves #3; closes NathanKrupa/grantspider#4; see #5"
    assert declared_fixes([text]) == frozenset({1, 2, 3})


def test_a_keyword_inside_another_word_is_not_a_fix():
    assert declared_fixes(["this prefixes #9 and encloses #9"]) == frozenset()

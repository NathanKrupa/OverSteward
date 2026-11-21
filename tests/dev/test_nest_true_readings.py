# ABOUTME: Every Bash guard carrying the nest-true scanner also decides under the nest-true reading.
# ABOUTME: Drives each guard's own decision on quotes nested in a substitution inside double quotes.

"""A guard holds if any of its readings holds, the nest-true reading among them.

``_ShellLexer`` toggles on every double quote, so it pairs the quotes of
``"$(echo "it's")"`` wrongly and reads the apostrophe as opening a quote the
shell never opens: a phantom quote, which can hide a later command. Every guard
also decides on ``_nest_true``'s text, where the scanner vouches for it, and
holds if that reading holds. Today's readings are untouched and decided first,
so nothing refused before passes. ``R`` is a command the guard refuses alone.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from tests.dev import test_guard_promote_cadence as cadence_tests
from tests.dev import test_guard_promote_ci_red as ci_red_tests
from tests.dev import test_lexer_comment_rule as comment_rule
from tests.dev import test_lexer_line_ends as line_ends
from tests.dev import test_nest_true as nest_true_tests

gate_pipe = comment_rule.gate_pipe

# The shell reads this as one word. The toggle lexer closes the outer string at
# the first inner quote and opens a phantom single quote at the apostrophe.
MIS = 'echo "$(echo "it\'s")"'
# A construct the scanner does not model (an ANSI-C quote), so it vouches for
# nothing in the text that holds it.
UNMODELLED = "echo $'z'"

# Each guard's stand-in and decider: the line-ends table (the worktree guard
# through its entry point, where all its readings are decided) and the
# comment-rule table's pipe and substitution guards.
GUARDS = MappingProxyType(
    {
        **line_ends.GUARDS,
        "gate-pipe": comment_rule.GUARDS["gate-pipe"],
        "endless": comment_rule.GUARDS["endless"],
    }
)
# The guards built on the shared lexer block, which read a line-true reading.
BLOCK_GUARDS = tuple(line_ends.GUARDS)
# The guards that read a script handed to a shell.
SCRIPT_GUARDS = ("gate-deny", "gate-ask", "promote-cadence", "promote-ci-red")


@pytest.fixture(autouse=True)
def _no_overrides(monkeypatch):
    """A session's own override must not decide a fixture."""
    for name in (*line_ends._OVERRIDES, "CLAUDE_ALLOW_GATE_PIPE", "CLAUDE_ALLOW_ENDLESS_SUBSTITUTION"):
        monkeypatch.delenv(name, raising=False)


def _decide(guard: str, template: str, tmp_path) -> bool:
    spec = GUARDS[guard]
    return spec.decide(template.format(R=spec.refused, MIS=MIS, U=UNMODELLED), tmp_path)


@pytest.mark.parametrize("guard", GUARDS)
def test_each_refused_command_is_refused_alone(guard, tmp_path):
    """The stand-in for each guard bites, so a pass below is never an inert decider."""
    assert _decide(guard, "{R}", tmp_path) is True


# --- row 1: a command after a phantom quote ---------------------------------


@pytest.mark.parametrize("guard", GUARDS)
def test_a_command_after_a_phantom_quote_is_refused(guard, tmp_path):
    """The phantom quote opened in the first word closes in the last, around ``R``.

    Today's readings read ``R`` as quoted text. The shell runs it, and the
    nest-true reading reads it as the shell does.
    """
    assert _decide(guard, "{MIS} ; {R} ; {MIS}", tmp_path) is True


@pytest.mark.parametrize("guard", BLOCK_GUARDS)
def test_a_later_line_after_a_phantom_quote_is_refused(guard, tmp_path):
    """Only the line-true reading of the nest-true text sees ``R`` start its own command.

    A real quote spans the first line end, so the nest-true text is lexed as one
    unit and ``R`` is glued onto the ``echo`` before it; the toggle lexer's
    phantom quote covers it in both of today's readings.
    """
    assert _decide(guard, '{MIS} "a\nb"\n{R} ; {MIS}', tmp_path) is True


# --- row 2: today's readings stay, and are decided first --------------------


@pytest.mark.parametrize("guard", GUARDS)
def test_what_only_todays_reading_holds_is_still_refused(guard, tmp_path):
    """``R`` is quoted data to the shell, but the toggle lexer reads it unquoted.

    The nest-true reading alone would pass it; today's reading holds it, and a
    reading is only ever added.
    """
    assert _decide(guard, 'echo "$(echo "x ; {R} ; y")"', tmp_path) is True


# --- row 3: no vouch, no extra reading --------------------------------------


@pytest.mark.parametrize("guard", GUARDS)
def test_text_the_scanner_does_not_vouch_for_gets_todays_verdict(guard, tmp_path):
    """Row 1's text with an unmodelled construct after it: today's verdict, which passes it.

    An accepted gap: without a vouch there is no nest-true reading.
    """
    assert _decide(guard, "{MIS} ; {R} ; {MIS} ; {U}", tmp_path) is False


# --- row 4: a script handed to a shell --------------------------------------


@pytest.mark.parametrize("guard", SCRIPT_GUARDS)
def test_a_script_handed_to_a_shell_is_read_under_the_nest_true_reading(guard, tmp_path):
    """The outer text has no nested quote; the script it hands to bash is row 1's text.

    ``'"'"'`` closes the single-quoted script, adds an apostrophe and reopens it.
    """
    apostrophe = "'\"'\"'"
    script = MIS.replace("'", apostrophe)
    assert _decide(guard, f"bash -c '{script} ; {{R}} ; {script}'", tmp_path) is True


# --- the promote guards: text the toggle lexer rejects ----------------------


@pytest.mark.parametrize("template", ["{MIS} ; {R}", '{MIS} "a\nb"\n{R}'])
@pytest.mark.parametrize("guard", ["promote-cadence", "promote-ci-red"])
def test_text_the_lexer_rejects_is_read_as_parsed_nest_true_text(guard, template, tmp_path):
    """The phantom quote never closes, so today's lexer rejects the text.

    The promote parser's reading of rejected text finds calls only in tokens
    the lexer completed; the nest-true text parses and holds ``R``. In the
    second text only its line-true reading does, which is made because the
    nest-true text lexes, whatever today's text does.
    """
    assert _decide(guard, template, tmp_path) is True


@pytest.mark.parametrize(
    ("tests", "refusal"),
    [(cadence_tests, cadence_tests.TOO_SOON), (ci_red_tests, ci_red_tests.RED)],
)
def test_an_override_on_the_promote_only_the_nest_true_reading_sees_is_honoured(tests, refusal):
    """The nest-true reading reads the override on the call it finds, as any reading does."""
    override = "GS_PROMOTE_HOTFIX=why " if tests is cadence_tests else "PROMOTE_OVER_CI_RED=why "
    code, message = tests.run(f"{MIS} ; {override}{tests.GS_PROMOTE} ; {MIS}")
    assert code == 0 and refusal not in message
    assert "why" in message


# --- row 5: the drafts' constructs stay refused by the pipe guard -----------

# The construct the review of the first draft found: a phantom pair on one line,
# a real quote opened just after it, and a gate pipeline on the next line.
_MIS_LINE_HOLE = f"{MIS} 'start\nx' ; pytest -q | tail -5 ; echo 'y'\n{MIS}"
_MIS_LINE_HOLE_QUOTE_FIRST = (
    f"git commit -m 'one\ntwo'\n{MIS} 'start\nx' ; pytest -q | tail -5 ; echo 'y' {MIS}"
)
# The construct the second draft stopped on: a newline inside the nested quote.
_NEWLINE_IN_NESTED_QUOTE = 'pytest -k "$(echo "a\nb")" | tail -5'


@pytest.mark.parametrize(
    "text", [_MIS_LINE_HOLE, _MIS_LINE_HOLE_QUOTE_FIRST, _NEWLINE_IN_NESTED_QUOTE]
)
def test_the_drafts_constructs_are_refused_on_the_nest_true_text_alone(text):
    """A pin, and the ground the redone drafts stand on: the nest-true text holds each.

    The guard refuses each today; its readings run on the nest-true text refuse
    each as well, so dropping a toggle reading there would lose nothing.
    """
    assert gate_pipe.should_block(text) is True
    vouched = gate_pipe._nest_true(text)
    assert vouched is not None and vouched != text
    assert gate_pipe._line_offenders(vouched) or gate_pipe._offenders(
        gate_pipe._lex_or_degrade(vouched)
    )


# --- the readings not made: no double quote, or no dollar sign or backtick --

_BLOCK_STEMS = line_ends._BLOCK_STEMS


def _could_nest(text: str) -> bool:
    return '"' in text and ("$" in text or "`" in text)


@pytest.mark.parametrize("stem", _BLOCK_STEMS)
def test_a_text_that_cannot_nest_a_quote_gets_todays_readings_alone(stem):
    """No double quote, or neither a dollar sign nor a backtick: no nest-true reading."""
    module = comment_rule._load(stem)
    assert module._reading_pairs("git checkout feature") == ((False, False),)
    assert module._reading_pairs("echo 'a\nb'") == ((False, False), (True, False))
    assert module._reading_pairs('echo "$HOME"') == ((False, False), (False, True))
    assert module._reading_pairs(f"{MIS} ; {UNMODELLED}") == ((False, False),)


def test_the_readings_not_made_would_repeat_todays():
    """The claim behind leaving them out, on every string in the guards' test tables:
    the scanner returns such a text unchanged, and every script it hands a shell is
    built of the text's own characters, so holds no nested quote either."""
    gate = comment_rule._load("check_destructive_command")
    texts = [text for text in nest_true_tests._test_table_texts() if not _could_nest(text)]
    scripts = 0
    for text in texts:
        assert gate._nest_true(text) in (None, text), text
        for argv in gate._all_argvs(text):
            script = gate._shell_script(argv)
            if script is not None:
                scripts += 1
                assert set(script) <= set(text) and not _could_nest(script), text
    assert len(texts) > 1000 and scripts > 10, (len(texts), scripts)

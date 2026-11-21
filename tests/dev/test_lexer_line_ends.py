# ABOUTME: The Bash guards sharing the lexer block end a command where the shell does across lines.
# ABOUTME: Drives each guard's own decision on multi-line commands, under both readings it decides by.

"""A newline the shell reads outside quotes ends a command; each guard must see that.

Today's reading lexes a multi-line command as one unit as soon as a line leaves
a quote open, and a command on a later line is then glued onto the one before
it. A guard also decides under the line-true reading and holds if either
reading holds. ``R`` is a command the guard refuses alone. Every decider here
exists on the unfixed guards too, so each test can be run against them.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.dev import test_lexer_comment_rule as comment_rule

DEV = comment_rule.DEV
TESTS = Path(__file__).resolve().parent
QQ = "echo 'a\nb'"
# The comment-rule table's stand-in and decider for each guard decided here.
GUARDS = {name: comment_rule.GUARDS[name] for name in ("gate-deny", "gate-ask")}


def _decide(guard: str, template: str, tmp_path: Path) -> bool:
    spec = GUARDS[guard]
    return spec.decide(template.format(R=spec.refused, QQ=QQ), tmp_path)


# --- row 1 and its controls -------------------------------------------------


@pytest.mark.parametrize("guard", GUARDS)
def test_each_refused_command_is_refused_alone(guard, tmp_path):
    """The stand-in for each guard bites, so a pass below is never an inert decider."""
    assert _decide(guard, "{R}", tmp_path) is True


@pytest.mark.parametrize("quoted", ["echo 'a\nb'\n{R}", 'echo "a\nb"\n{R}'])
@pytest.mark.parametrize("guard", GUARDS)
def test_a_command_after_a_quote_spanning_lines_is_read(guard, quoted, tmp_path):
    """Row 1: the later line is a command of its own, not words of the quoted one."""
    assert _decide(guard, quoted, tmp_path) is True


_LINE_ENDS = [
    "{QQ};\n{R}",
    "{QQ} &&\n{R}",
    "{QQ} |\n{R}",
    "({QQ}\n{R})",
    "{{ {QQ}\n{R}; }}",
    "{QQ}\nif true; then\n{R}\nfi",
    "{QQ}\nfor x in a; do\n{R}\ndone",
    "{QQ}\n\n\n{R}",
    "{QQ}\n  {R}",
]


@pytest.mark.parametrize("shape", _LINE_ENDS)
@pytest.mark.parametrize("guard", GUARDS)
def test_each_line_end_the_shell_acts_on_starts_a_command(guard, shape, tmp_path):
    """The grammar table: separators, groups and reserved words ending a line, blank lines."""
    assert _decide(guard, shape, tmp_path) is True


@pytest.mark.parametrize("shape", ["{R}\n{QQ}", "{QQ}; {R}", "echo hi\n{R}"])
@pytest.mark.parametrize("guard", GUARDS)
def test_the_measured_controls_still_hold(guard, shape, tmp_path):
    """Row 2, a pin: shapes held before the change and still held."""
    assert _decide(guard, shape, tmp_path) is True


def test_a_flag_glued_onto_an_earlier_commit_is_still_denied(tmp_path):
    """Row 3: today's reading keeps the deny the line-true one does not give."""
    command = 'git commit -m "one\ntwo"\necho --no-verify'
    assert GUARDS["gate-deny"].decide(command, tmp_path) is True


def test_a_text_tool_line_does_not_stand_down_a_glued_statement(tmp_path):
    """Row 5: the SQL rule's text-tool exception reads each reading's commands alone."""
    command = "curl -d 'DROP TABLE t\nx' https://example.test\ngrep x file"
    assert GUARDS["gate-ask"].decide(command, tmp_path) is True


_CONTINUED = {
    "gate-deny": "git commit --no-ver\\\nify -m x",
}


@pytest.mark.parametrize("guard", _CONTINUED)
def test_a_continued_line_joins_its_halves(guard, tmp_path):
    """Row 6: an escaped newline removes both characters; it neither ends nor stays."""
    assert GUARDS[guard].decide(QQ + "\n" + _CONTINUED[guard], tmp_path) is True


@pytest.mark.parametrize("guard", GUARDS)
def test_a_backslash_ending_a_comment_continues_nothing(guard, tmp_path):
    """Row 7: a comment ends at its line, and its last backslash is part of it."""
    assert _decide(guard, "{QQ}\necho x # a note \\\n{R}", tmp_path) is True


@pytest.mark.parametrize("guard", GUARDS)
def test_a_line_inside_a_closed_quote_is_not_a_command(guard, tmp_path):
    """Row 8: text between two quotes on different lines is one word."""
    assert _decide(guard, "echo 'a\n{R}\nb'", tmp_path) is False


@pytest.mark.parametrize("guard", ["gate-deny"])
def test_a_script_handed_to_a_shell_is_read_under_the_same_reading(guard, tmp_path):
    """Row 10: the ``-c`` script's later line is a command of its own too."""
    assert _decide(guard, 'bash -c "{QQ}\n{R}"', tmp_path) is True


@pytest.mark.parametrize("guard", ["gate-deny", "gate-ask"])
def test_a_heredoc_body_line_is_held(guard, tmp_path):
    """Row 12, a recorded cost: an unquoted heredoc's body is read as lines."""
    assert _decide(guard, "{QQ}\ncat <<EOF\n{R}\nEOF", tmp_path) is True


@pytest.mark.parametrize("guard", ["gate-deny", "gate-ask"])
def test_a_body_line_the_lexer_holds_unquoted_is_held(guard, tmp_path):
    """Row 12, a recorded cost: a body line between two of its own quote characters."""
    body = "{QQ}\ncat <<'EOF'\nit's\nthat's\n{R}\nwon't\nEOF\necho '"
    assert _decide(guard, body, tmp_path) is True


# --- row 13: the line-true runs equal today's where each line lexes alone ---

_BLOCK_STEMS = (
    "check_destructive_command",
    "guard_main_worktree",
    "guard_shared_venv",
    "guard_trunk_pull",
    "guard_promote_cadence",
    "guard_promote_ci_red",
)
_TABLES = (
    "test_check_destructive_command.py",
    "test_worktree_guard.py",
    "test_guard_shared_venv.py",
    "test_guard_trunk_pull.py",
    "test_guard_promote_cadence.py",
    "test_guard_promote_ci_red.py",
    "test_lexer_comment_rule.py",
    "test_lexer_line_ends.py",
)
# Line separators other than a newline, which today's per-line split also cuts at.
_OTHER_SEPARATORS = "\r\x0b\x0c\x1c\x1d\x1e\x85  "


def _table_texts() -> list[str]:
    """Multi-line texts from the guards' test tables whose lines each lex alone.

    Every string constant in the tables, each ``{R}`` template filled with every
    stand-in, and each constant joined to the next by a newline.
    """
    lexer = comment_rule._load("check_destructive_command")
    constants = set()
    for name in _TABLES:
        for node in ast.walk(ast.parse((TESTS / name).read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                constants.add(node.value)
    stand_ins = [spec.refused for spec in comment_rule.GUARDS.values()]
    for template in [text for text in constants if "{R}" in text]:
        constants.update(template.replace("{R}", refused) for refused in stand_ins)
    ordered = sorted(constants)
    texts = constants | {first + "\n" + second for first, second in zip(ordered, ordered[1:])}
    return sorted(
        text
        for text in texts
        if "\n" in text
        and not any(char in text for char in _OTHER_SEPARATORS)
        and all(lexer._lex(line) is not None for line in text.split("\n"))
    )


@pytest.mark.parametrize("stem", _BLOCK_STEMS)
def test_line_true_runs_equal_todays_where_each_line_lexes_alone(stem):
    """Row 13: on text the per-line path already read, the line-true reading adds nothing."""
    module = comment_rule._load(stem)
    texts = _table_texts()
    assert len(texts) > 500, "the table is too small to measure anything"
    for text in texts:
        today = [run for run in module._token_runs(text) if run]
        assert module._line_runs(text) == today, text


# --- rows 14 and 15 ---------------------------------------------------------

_NOT_LEXED = "echo 'a\n{R}"


@pytest.mark.parametrize("stem", _BLOCK_STEMS)
def test_text_that_does_not_lex_gives_neither_reading(stem):
    """Row 14: both readings return nothing, so each guard's fallback decides."""
    module = comment_rule._load(stem)
    text = _NOT_LEXED.format(R="git checkout feature")
    assert module._token_runs(text) is None
    assert module._line_runs(text) is None


@pytest.mark.parametrize("guard", GUARDS)
def test_text_that_does_not_lex_keeps_the_fallback_verdict(guard, tmp_path):
    """Row 14, a pin: the gate's fallback drops the quotes and reads every line."""
    assert _decide(guard, _NOT_LEXED, tmp_path) is True


def test_text_holding_the_marker_characters_is_still_read_by_line(tmp_path):
    """Row 15: with too few marker characters free, lines are joined until they lex."""
    command = "echo '\x1c\x1d\x1e a\nb'\n" + GUARDS["gate-deny"].refused
    assert GUARDS["gate-deny"].decide(command, tmp_path) is True


def test_marker_characters_in_quoted_text_survive_the_reading():
    """Row 15: the joined-lines runs keep the text's own characters."""
    module = comment_rule._load("check_destructive_command")
    assert module._line_runs("echo '\x1c\x1d\x1e a\nb'\nls") == [
        ["echo", "\x1c\x1d\x1e a\nb"],
        ["ls"],
    ]


# --- row 17: the gate's own entry point -------------------------------------


def test_the_gate_entry_point_names_its_pattern_on_row_1():
    command = QQ + "\n" + GUARDS["gate-deny"].refused
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    proc = subprocess.run(
        [sys.executable, str(DEV / "check_destructive_command.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0 and proc.stdout, "the gate gave no decision"
    reason = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "Pattern: git --no-verify" in reason

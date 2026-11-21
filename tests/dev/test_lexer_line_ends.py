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
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from tests.dev import test_guard_promote_cadence as cadence_tests
from tests.dev import test_guard_promote_ci_red as ci_red_tests
from tests.dev import test_lexer_comment_rule as comment_rule

DEV = comment_rule.DEV
TESTS = Path(__file__).resolve().parent
QQ = "echo 'a\nb'"
_OVERRIDES = (
    "CLAUDE_ALLOW_MAIN_GIT",
    "GS_ALLOW_MAIN_GIT",
    "CLAUDE_ALLOW_SHARED_VENV_MUTATION",
    "UV_NO_SYNC",
    "CLAUDE_CODE_REMOTE_ENVIRONMENT_TYPE",
)
# Each guard's own override prefix, for the rows that put one on a later line.
OVERRIDE = {
    "main-worktree": "CLAUDE_ALLOW_MAIN_GIT=1 ",
    "shared-venv": "CLAUDE_ALLOW_SHARED_VENV_MUTATION=1 ",
    "trunk-pull": "CLAUDE_ALLOW_MAIN_GIT=1 ",
}
_SWITCH_REFUSED = "BLOCKED — branch checkout/switch in the shared main worktree"


@pytest.fixture(autouse=True)
def _no_overrides(monkeypatch):
    """A session's own override must not decide a fixture."""
    for name in _OVERRIDES:
        monkeypatch.delenv(name, raising=False)


def _clean_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in _OVERRIDES}


def _git_repo(root: Path, *, venv_outside: bool = False) -> Path:
    """A primary checkout on ``main`` with one commit; optionally a borrowed ``.venv``."""
    repo = root / "repo"
    if repo.exists():
        return repo
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.test"]
    subprocess.run([*git, "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    if venv_outside:
        (root / "primary-venv").mkdir()
        (repo / ".venv").symlink_to(root / "primary-venv")
    return repo


def _hook(stem: str, command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """The guard run as Claude Code runs it, on ``command`` from ``cwd``."""
    event = {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}
    proc = subprocess.run(
        [sys.executable, str(DEV / f"{stem}.py")],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        cwd=cwd,
        env=_clean_env(),
    )
    assert "Traceback" not in proc.stderr
    return proc


def _worktree_refuses(command: str, tmp_path: Path) -> bool:
    """The worktree guard end to end, from a primary checkout."""
    proc = _hook("guard_main_worktree", command, _git_repo(tmp_path))
    assert proc.returncode in (0, 2)
    return proc.returncode == 2 and _SWITCH_REFUSED in proc.stderr


# The comment-rule table's stand-in and decider for each guard; the worktree
# guard is driven through its entry point, where its two readings are decided.
GUARDS = {
    name: comment_rule.GUARDS[name]
    for name in (
        "gate-deny",
        "gate-ask",
        "shared-venv",
        "trunk-pull",
        "promote-cadence",
        "promote-ci-red",
    )
}
GUARDS["main-worktree"] = comment_rule.Guard("git checkout feature", _worktree_refuses)


def _decide(guard: str, template: str, tmp_path: Path) -> bool:
    spec = GUARDS[guard]
    filled = template.format(R=spec.refused, O=OVERRIDE.get(guard, ""), QQ=QQ)
    return spec.decide(filled, tmp_path)


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
    "main-worktree": "git check\\\nout feature",
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


@pytest.mark.parametrize("guard", ["gate-deny", "promote-cadence", "promote-ci-red"])
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


# --- rows 4, 9 and 11: overrides and directories, reading by reading --------


@pytest.mark.parametrize("guard", ["main-worktree", "trunk-pull", "shared-venv"])
def test_an_override_on_a_later_line_does_not_clear_a_glued_command(guard, tmp_path):
    """Row 4: the readings are decided apart, so a visible override clears only its own."""
    assert _decide(guard, "{R} --note='a\nb'\n{O}{R}", tmp_path) is True


@pytest.mark.parametrize(
    ("tests", "refusal"),
    [(cadence_tests, cadence_tests.TOO_SOON), (ci_red_tests, ci_red_tests.RED)],
)
def test_a_directory_change_on_its_own_line_is_followed(tests, refusal):
    """Row 9: the line-true reading follows a ``cd`` from the hook's own directory."""
    checkouts = tests.FakeCheckouts(
        {"/home/natha/grantspider": tests.g.Checkout(tests.GS_ORIGIN, "staging")}
    )
    command = QQ + "\ncd ../grantspider\ngh pr create --base main --head staging --title t"
    code, message = tests.run(command, checkouts=checkouts, cwd="/home/natha/OverSteward")
    assert code == 2 and refusal in message
    assert checkouts.asked == ["/home/natha/grantspider"]


@pytest.mark.parametrize("guard", ["main-worktree", "shared-venv", "trunk-pull"])
def test_a_later_line_with_its_own_override_is_allowed(guard, tmp_path):
    """Row 11: the line-true reading honours an override on the command it reads."""
    assert _decide(guard, "{QQ}\n{O}{R}", tmp_path) is False


def test_a_later_line_promote_with_its_override_is_allowed_and_said():
    """Row 11, cadence: seen and overridden, and the reason is printed."""
    code, message = cadence_tests.run(QQ + "\nGS_PROMOTE_HOTFIX=why " + cadence_tests.GS_PROMOTE)
    assert code == 0
    assert "allowed by GS_PROMOTE_HOTFIX — reason: why" in message


def test_a_later_line_promote_with_its_override_is_recorded_once():
    """Row 11, ci-red: the override is commented on the red issue, once."""
    comments = ci_red_tests.FakeComments()
    command = QQ + "\nPROMOTE_OVER_CI_RED=why " + ci_red_tests.GS_PROMOTE
    code, message = ci_red_tests.run(command, comments=comments)
    assert code == 0 and "BLOCKED" not in message
    assert [(repo, number) for repo, number, _ in comments.posted] == [(ci_red_tests.GS, 3530)]


def test_a_plain_promote_one_reading_finds_first_refuses_and_records_nothing():
    """Each reading's first promote is decided: today's is overridden, the other's is not."""
    comments = ci_red_tests.FakeComments()
    promote = ci_red_tests.GS_PROMOTE
    command = QQ + "\n" + promote + " && PROMOTE_OVER_CI_RED=why " + promote
    code, message = ci_red_tests.run(command, comments=comments)
    assert code == 2 and ci_red_tests.RED in message
    assert comments.attempted == []


def test_a_promote_both_readings_find_is_looked_up_once():
    """The readings' promotes are distinct, so one allowed promote asks GitHub once."""
    github = cadence_tests.FakeGitHub(ago=timedelta(days=7))
    code, _ = cadence_tests.run(cadence_tests.GS_PROMOTE + "\necho done", github=github)
    assert code == 0
    assert github.calls == 1


def test_an_allowed_plain_promote_does_not_silence_the_other_readings_override():
    """ci-red: the plain promote passes, so the overridden one still records its reason."""
    comments = ci_red_tests.FakeComments()
    command = (
        QQ + "\n" + ci_red_tests.AG_PROMOTE + " && PROMOTE_OVER_CI_RED=why "
        + ci_red_tests.GS_PROMOTE
    )
    code, message = ci_red_tests.run(command, comments=comments)
    assert code == 0 and "BLOCKED" not in message
    assert [(repo, number) for repo, number, _ in comments.posted] == [(ci_red_tests.GS, 3530)]


def test_an_allowed_plain_promote_does_not_silence_the_other_readings_reason():
    """cadence: past the window the plain promote passes, and the override is still said."""
    github = cadence_tests.FakeGitHub(ago=timedelta(days=7))
    promote = cadence_tests.GS_PROMOTE
    command = QQ + "\n" + promote + " && GS_PROMOTE_HOTFIX=why " + promote
    code, message = cadence_tests.run(command, github=github)
    assert code == 0
    assert "allowed by GS_PROMOTE_HOTFIX — reason: why" in message


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


@pytest.mark.parametrize(
    ("guard", "held"),
    [(name, not name.startswith("promote-")) for name in GUARDS],
)
def test_text_that_does_not_lex_keeps_the_fallback_verdict(guard, held, tmp_path):
    """Row 14, a pin: each guard's fallback verdict; the promote guards read nothing."""
    assert _decide(guard, _NOT_LEXED, tmp_path) is held


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


_ENTRY = {
    "main-worktree": ("guard_main_worktree", {}, _SWITCH_REFUSED),
    "shared-venv": (
        "guard_shared_venv",
        {"venv_outside": True},
        "BLOCKED — `uv sync` in a tree whose .venv is not its own",
    ),
    "trunk-pull": ("guard_trunk_pull", {}, "BLOCKED — this pull would rewrite a protected branch"),
}


@pytest.mark.parametrize("guard", _ENTRY)
def test_each_entry_point_refuses_row_1_with_its_own_message(guard, tmp_path):
    stem, repo_kwargs, message = _ENTRY[guard]
    command = QQ + "\n" + GUARDS[guard].refused
    proc = _hook(stem, command, _git_repo(tmp_path, **repo_kwargs))
    assert proc.returncode == 2
    assert message in proc.stderr


@pytest.mark.parametrize("guard", _ENTRY)
def test_each_entry_point_is_silent_on_row_8(guard, tmp_path):
    stem, repo_kwargs, _ = _ENTRY[guard]
    command = "echo 'a\n" + GUARDS[guard].refused + "\nb'"
    proc = _hook(stem, command, _git_repo(tmp_path, **repo_kwargs))
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")

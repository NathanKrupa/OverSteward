# ABOUTME: Every Bash guard reads a hash as the shell does: a comment only where a word starts.
# ABOUTME: Drives each guard's own decision on commands that share a line with a hash-bearing word.

"""A hash starts a comment only at the start of a word, outside quotes.

Anywhere else the shell reads it as part of its word and runs the rest of the
line, so a guard must read that rest too. Each test drives a guard's own
decision function (the destructive-command gate end to end), loaded by path
from ``shared/scripts/dev/``. ``REFUSED`` is a command the guard refuses alone.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

import pytest

from tests.dev import test_guard_promote_cadence as cadence_tests
from tests.dev import test_guard_promote_ci_red as ci_red_tests

DEV = Path(__file__).resolve().parents[2] / "shared" / "scripts" / "dev"


def _load(stem: str):
    path = DEV / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(f"lexer_comment_rule_{stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


main_worktree = _load("guard_main_worktree")
shared_venv = _load("guard_shared_venv")
trunk_pull = _load("guard_trunk_pull")
gate_pipe = _load("guard_gate_pipe")
endless = _load("guard_endless_substitution")

_OVERRIDES = (
    "CLAUDE_ALLOW_MAIN_GIT",
    "GS_ALLOW_MAIN_GIT",
    "CLAUDE_ALLOW_SHARED_VENV_MUTATION",
    "UV_NO_SYNC",
    "CLAUDE_ALLOW_GATE_PIPE",
    "CLAUDE_ALLOW_ENDLESS_SUBSTITUTION",
)


@pytest.fixture(autouse=True)
def _no_overrides(monkeypatch):
    """A session's own override must not decide a fixture."""
    for name in _OVERRIDES:
        monkeypatch.delenv(name, raising=False)


def _gate_decision(command: str) -> str | None:
    """The destructive-command gate's decision, run as Claude Code runs it."""
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    proc = subprocess.run(
        [sys.executable, str(DEV / "check_destructive_command.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stderr
    if not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]


def _borrowing_tree(tmp_path: Path) -> str:
    """A tree whose ``.venv`` is a symlink to a venv outside it."""
    tree, venv = tmp_path / "tree", tmp_path / "primary-venv"
    if not tree.exists():
        tree.mkdir()
        venv.mkdir()
        (tree / ".venv").symlink_to(venv)
    return str(tree)


def _cadence_refuses(command: str) -> bool:
    code, message = cadence_tests.run(command)
    assert "Traceback" not in message
    return code == 2 and cadence_tests.TOO_SOON in message


def _ci_red_refuses(command: str) -> bool:
    code, message = ci_red_tests.run(command)
    assert "Traceback" not in message
    return code == 2 and ci_red_tests.RED in message


def _endless_found(command: str) -> bool:
    """The command placed as the body of a process substitution."""
    return bool(endless.endless_substitutions("cat <(" + command + "\n)"))


class Guard(NamedTuple):
    refused: str
    decide: Callable[[str, Path], bool]


GUARDS = {
    "gate-deny": Guard(
        "git commit --no-verify -m x", lambda cmd, _: _gate_decision(cmd) == "deny"
    ),
    "gate-ask": Guard(
        "rm -rf /home/natha/scratch-dir", lambda cmd, _: _gate_decision(cmd) == "ask"
    ),
    "main-worktree": Guard(
        "git checkout feature", lambda cmd, _: main_worktree.is_branch_switch(cmd)
    ),
    "shared-venv": Guard(
        "uv sync",
        lambda cmd, tmp: shared_venv.blocked_venv(cmd, _borrowing_tree(tmp)) is not None,
    ),
    "trunk-pull": Guard(
        "git pull origin staging",
        lambda cmd, _: trunk_pull.should_block(cmd, current_branch="main"),
    ),
    "promote-cadence": Guard(cadence_tests.GS_PROMOTE, lambda cmd, _: _cadence_refuses(cmd)),
    "promote-ci-red": Guard(ci_red_tests.GS_PROMOTE, lambda cmd, _: _ci_red_refuses(cmd)),
    "gate-pipe": Guard("pytest -q | tail -5", lambda cmd, _: gate_pipe.should_block(cmd)),
    "endless": Guard("yes", lambda cmd, _: _endless_found(cmd)),
}


def _decide(guard: str, template: str, tmp_path: Path) -> bool:
    spec = GUARDS[guard]
    return spec.decide(template.format(R=spec.refused), tmp_path)


@pytest.mark.parametrize("guard", GUARDS)
def test_each_refused_command_is_refused_alone(guard, tmp_path):
    """The stand-in for each guard bites, so a pass below is never an inert decider."""
    assert _decide(guard, "{R}", tmp_path) is True


@pytest.mark.parametrize("guard", GUARDS)
def test_a_hash_inside_a_word_hides_nothing(guard, tmp_path):
    assert _decide(guard, "echo a#b; {R}", tmp_path) is True


SHAPES = [
    "echo a#b && {R}",
    "echo a#b || {R}",
    "echo a#b | {R}",
    "echo a#b $({R})",
    "echo https://example.test/page#frag; {R}",
    "echo $#; {R}",
    "echo ${{x#y}}; {R}",
    'echo "a"#b; {R}',
    "echo a\\ #b; {R}",
]


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("guard", GUARDS)
def test_no_separator_or_word_shape_hides_the_command(guard, shape, tmp_path):
    assert _decide(guard, shape, tmp_path) is True


# A separator follows each hash, so were the hash not a comment the command
# would sit in command position and be refused: each row can fail.
@pytest.mark.parametrize("comment", ["echo a #b; {R}", "echo a;#; {R}", "(#; {R}"])
@pytest.mark.parametrize("guard", GUARDS)
def test_a_hash_at_the_start_of_a_word_still_ends_its_line(guard, comment, tmp_path):
    assert _decide(guard, comment, tmp_path) is False


@pytest.mark.parametrize("quoted", ['echo "a #b"; {R}', "echo 'a #b'; {R}"])
@pytest.mark.parametrize("guard", GUARDS)
def test_a_quoted_hash_is_literal(guard, quoted, tmp_path):
    """A pin: quotes protected a hash before the change and still do."""
    assert _decide(guard, quoted, tmp_path) is True


@pytest.mark.parametrize("guard", GUARDS)
def test_a_comment_cannot_open_a_quote(guard, tmp_path):
    """Apostrophes inside two real comments must not pair up across the command."""
    assert _decide(guard, "# it's a note\n{R}\n# that's all", tmp_path) is True


@pytest.mark.parametrize("guard", GUARDS)
def test_the_next_line_is_read(guard, tmp_path):
    """The loss was only ever the rest of one line."""
    assert _decide(guard, "echo a#b\n{R}", tmp_path) is True


_WITH_FALLBACK = [name for name in GUARDS if not name.startswith("promote-")]


@pytest.mark.parametrize("guard", _WITH_FALLBACK)
def test_the_unlexable_fallback_reads_past_the_hash(guard, tmp_path):
    """An unbalanced quote sends the text to each guard's fallback, which sees it all."""
    assert _decide(guard, "echo 'a#b; {R}", tmp_path) is True


# The promote guards' fallback reads rejected text by the lexer's own rules, so
# text inside a quote the lexer cannot close is not a command and the fallback
# above is not theirs. A text rejected after the command keeps the comment rule.
_REJECTED_AFTER = "\ncat <<EOF\nit's\nEOF"
_PROMOTE_GUARDS = [name for name in GUARDS if name.startswith("promote-")]


@pytest.mark.parametrize(
    ("template", "refused"),
    [("echo a#b; {R}" + _REJECTED_AFTER, True), ("echo a #b; {R}" + _REJECTED_AFTER, False)],
)
@pytest.mark.parametrize("guard", _PROMOTE_GUARDS)
def test_the_promote_fallback_keeps_the_comment_rule(guard, template, refused, tmp_path):
    assert _decide(guard, template, tmp_path) is refused


def test_a_comment_in_a_substitution_body_ends_at_its_own_line():
    """The body's lines are joined before lexing; a comment must not run past its line."""
    assert endless.endless_substitutions("cat <(echo x #note\nyes)")

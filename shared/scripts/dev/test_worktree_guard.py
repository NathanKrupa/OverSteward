# ABOUTME: Tests for the session-per-worktree guard hook (.claude/hooks/guard_main_worktree.py).
# ABOUTME: Pure decision logic — branch-op detection, command anchoring, primary-vs-linked.

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_guard():
    """Load the deployed hook by file path (no package install needed).

    Walks up from this test file to the repo root (the dir containing
    ``.claude/hooks/guard_main_worktree.py``), so it works regardless of how
    deep ``tests/dev/`` sits.
    """
    rel = Path(".claude") / "hooks" / "guard_main_worktree.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("guard_main_worktree", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError(f"could not locate {rel} above {__file__}")


@pytest.fixture(scope="module")
def guard():
    return _load_guard()


# Fixture data reused across the suite, named once so the intent is the label
# rather than the literal.
_PRIMARY_GIT_DIR = "/repo/.git"
_LINKED_GIT_DIR = "/repo/.git/worktrees/foo"
_OVERRIDE_VARS = ("CLAUDE_ALLOW_MAIN_GIT", "GS_ALLOW_MAIN_GIT")
_REMOTE_ENV_VAR = "CLAUDE_CODE_REMOTE_ENVIRONMENT_TYPE"
_STAND_DOWN_VARS = (*_OVERRIDE_VARS, _REMOTE_ENV_VAR)


def _clear_overrides(monkeypatch) -> None:
    """Drop every ambient stand-down so the command under test is what decides.

    Covers the overrides and the remote-container environment type: a session
    that happens to carry either would otherwise turn a blocking assertion
    green for a reason the test never named.
    """
    for var in _STAND_DOWN_VARS:
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# is_branch_switch — detects branch checkout/switch, exempts file restores
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "git checkout main",
        "git checkout -b feat/x",
        "git switch staging",
        "git switch -c session/foo",
        "git fetch && git checkout main",
        "git status; git checkout -b y",
        "  git checkout dev",
        # env-assignment prefix must not slip past command-position anchoring
        "FOO=bar git checkout main",
        "FOO=bar BAZ=qux git switch staging",
        "git fetch && DEBUG=1 git checkout -b feat/x",
        # command substitution is a command position too — backtick, $(...)
        # and a plain subshell all reach a real git invocation
        "`git checkout main`",
        "echo `git switch main`",
        "$(git checkout main)",
        "X=$(git checkout -b feat/x)",
        "(git checkout main)",
        "(cd /repo && git switch staging)",
    ],
)
def test_branch_switch_detected(guard, cmd):
    assert guard.is_branch_switch(cmd) is True


@pytest.mark.parametrize(
    "cmd",
    [
        "git checkout -- file.py",
        "git checkout -- .",
        "git restore src/app.py",
        "git restore --staged file",
        "git status",
        "git fetch origin",
        "git worktree add /tmp/wt -b session/x origin/main",
        "git log --oneline",
        "echo 'git checkout main'",
        'echo "git checkout main"',
        "printf 'run git switch foo'",
        "grep -r 'git checkout' docs/",
        'grep "git checkout" file',
        "git checkout origin/master -- scripts/dev/",
        "git stash",
        "git stash pop",
        "git branch -d feat/x",
        # a substitution that reaches no branch op stays clean
        "echo $(git rev-parse HEAD)",
        "(git status)",
    ],
)
def test_non_branch_switch_ignored(guard, cmd):
    assert guard.is_branch_switch(cmd) is False


def test_file_restore_with_path_after_double_dash(guard):
    assert guard.is_branch_switch("git checkout HEAD -- path/to/file") is False


def test_quoted_separator_char_is_not_a_command(guard):
    """A separator inside quotes is text the shell hands on as one argument.

    The command is lexed rather than pattern-matched, so a quoted ``;`` or
    ``(`` stays inside its token instead of opening a command position. This
    is the shape that refused a ``gh issue`` body three times on 2026-08-28.
    """
    assert guard.is_branch_switch('echo "; git checkout main"') is False
    assert guard.is_branch_switch('echo "(git checkout main)"') is False


# ---------------------------------------------------------------------------
# in_main_worktree — primary vs linked classification
# ---------------------------------------------------------------------------


def test_primary_worktree(guard):
    assert guard.in_main_worktree("/home/u/repo/.git") is True


def test_linked_worktree(guard):
    assert guard.in_main_worktree("/home/u/repo/.git/worktrees/session-foo") is False


def test_empty_git_dir_not_main(guard):
    assert guard.in_main_worktree("") is False


# ---------------------------------------------------------------------------
# has_override — standard var + back-compat alias, env or inline
# ---------------------------------------------------------------------------


def test_override_inline_standard(guard, monkeypatch):
    _clear_overrides(monkeypatch)
    assert guard.has_override("CLAUDE_ALLOW_MAIN_GIT=1 git checkout main") is True


def test_override_inline_alias(guard, monkeypatch):
    _clear_overrides(monkeypatch)
    assert guard.has_override("GS_ALLOW_MAIN_GIT=1 git switch x") is True


def test_override_inline_among_other_assignments(guard, monkeypatch):
    _clear_overrides(monkeypatch)
    assert guard.has_override("FOO=1 CLAUDE_ALLOW_MAIN_GIT=1 git checkout main") is True


def test_override_env_standard(guard, monkeypatch):
    monkeypatch.setenv("CLAUDE_ALLOW_MAIN_GIT", "1")
    assert guard.has_override("git checkout main") is True


def test_no_override(guard, monkeypatch):
    _clear_overrides(monkeypatch)
    assert guard.has_override("git checkout main") is False


def test_override_substring_in_string_rejected(guard, monkeypatch):
    """A quoted mention or a token before another command is NOT an override."""
    _clear_overrides(monkeypatch)
    assert guard.has_override('echo "CLAUDE_ALLOW_MAIN_GIT=1" && git checkout main') is False
    assert guard.has_override("CLAUDE_ALLOW_MAIN_GIT=1 echo hi; git checkout main") is False


def test_override_not_set_to_one_rejected(guard, monkeypatch):
    _clear_overrides(monkeypatch)
    assert guard.has_override("CLAUDE_ALLOW_MAIN_GIT=0 git checkout main") is False


# ---------------------------------------------------------------------------
# main() — end-to-end block/allow via stdin event (no real git needed for the
# non-blocking paths; the blocking path is exercised where git-dir is primary)
# ---------------------------------------------------------------------------


def _run_main(guard, monkeypatch, command, git_dir):
    import io
    import json

    event = {"tool_name": "Bash", "cwd": "/x", "tool_input": {"command": command}}
    monkeypatch.setattr(guard, "_git_dir", lambda _cwd: git_dir)
    monkeypatch.setattr(guard.sys, "stdin", io.StringIO(json.dumps(event)))
    return guard.main()


def test_main_blocks_env_prefixed_switch_in_main(guard, monkeypatch):
    _clear_overrides(monkeypatch)
    assert _run_main(guard, monkeypatch, "FOO=bar git checkout main", _PRIMARY_GIT_DIR) == 2


def test_main_blocks_echoed_override_in_main(guard, monkeypatch):
    _clear_overrides(monkeypatch)
    cmd = 'echo "CLAUDE_ALLOW_MAIN_GIT=1" && git checkout main'
    assert _run_main(guard, monkeypatch, cmd, _PRIMARY_GIT_DIR) == 2


def test_main_allows_genuine_inline_override_in_main(guard, monkeypatch):
    _clear_overrides(monkeypatch)
    cmd = "CLAUDE_ALLOW_MAIN_GIT=1 git checkout main"
    assert _run_main(guard, monkeypatch, cmd, _PRIMARY_GIT_DIR) == 0


@pytest.mark.parametrize(
    "cmd",
    [
        "`git checkout main`",
        "$(git checkout main)",
        "(git checkout main)",
        "echo `git switch main`",
    ],
)
def test_main_blocks_substitution_forms_in_main(guard, monkeypatch, cmd):
    _clear_overrides(monkeypatch)
    assert _run_main(guard, monkeypatch, cmd, _PRIMARY_GIT_DIR) == 2


def test_main_allows_override_inside_a_subshell(guard, monkeypatch):
    _clear_overrides(monkeypatch)
    cmd = "(CLAUDE_ALLOW_MAIN_GIT=1 git checkout main)"
    assert _run_main(guard, monkeypatch, cmd, _PRIMARY_GIT_DIR) == 0


def test_main_allows_file_restore_in_main(guard, monkeypatch):
    assert _run_main(guard, monkeypatch, "git checkout -- path", _PRIMARY_GIT_DIR) == 0
    assert _run_main(guard, monkeypatch, "git restore src/app.py", _PRIMARY_GIT_DIR) == 0


def test_main_allows_worktree_add_in_main(guard, monkeypatch):
    cmd = "git worktree add /tmp/wt -b session/x origin/main"
    assert _run_main(guard, monkeypatch, cmd, _PRIMARY_GIT_DIR) == 0


def test_main_allows_status_and_commit_in_main(guard, monkeypatch):
    assert _run_main(guard, monkeypatch, "git status", _PRIMARY_GIT_DIR) == 0
    assert _run_main(guard, monkeypatch, "git commit -m x", _PRIMARY_GIT_DIR) == 0


def test_main_allows_switch_in_linked_worktree(guard, monkeypatch):
    cmd = "git checkout main"
    assert _run_main(guard, monkeypatch, cmd, _LINKED_GIT_DIR) == 0


# ---------------------------------------------------------------------------
# Command position — a git verb inside quoted text is data, not an invocation
# (OS#401). The command is lexed, so a verb counts only where the shell would
# run it. Each fixture below was seen red against the pre-tokenising guard.
# ---------------------------------------------------------------------------

# The exact shape refused three times on 2026-08-28 while filing OS#401: a
# ``gh issue create`` whose heredoc BODY discusses the guard. No git command
# runs, or could run — the verbs are prose inside a quoted command substitution.
_HEREDOC_BODY_ABOUT_THE_GUARD = (
    'gh issue create --title "guard false positive" --body "$(cat <<\'EOF\'\n'
    "The guard scans the raw command string, so every `git checkout` /\n"
    "`git switch` mentioned in a body is refused. Reproduction:\n"
    "\n"
    "git checkout -b feat/x\n"
    "EOF\n"
    ')"'
)


def test_heredoc_body_mentioning_a_git_verb_is_not_a_command(guard):
    """(d) The heredoc-body false positive this issue exists to remove."""
    assert guard.is_branch_switch(_HEREDOC_BODY_ABOUT_THE_GUARD) is False


def test_main_allows_a_heredoc_body_mentioning_a_git_verb(guard, monkeypatch):
    """(d) End to end — the operator's ``gh issue create`` must not be refused."""
    _clear_overrides(monkeypatch)
    assert _run_main(guard, monkeypatch, _HEREDOC_BODY_ABOUT_THE_GUARD, _PRIMARY_GIT_DIR) == 0


@pytest.mark.parametrize(
    "cmd",
    [
        # A message, a PR body, a doc line — the verb is an argument, never argv[0].
        "git commit -m 'do not git checkout main here'",
        'gh pr create --body "first git switch main, then rebase"',
        'printf "%s\\n" "git checkout -b feat/x"',
        # The red ones: a shell separator *inside* the quoted argument used to
        # read as a real command position, so the message text refused itself.
        "git commit -m 'fetch first; git checkout main'",
        'gh pr create --body "steps: (git switch main) then merge"',
    ],
)
def test_git_verb_inside_an_argument_is_not_a_command(guard, cmd):
    assert guard.is_branch_switch(cmd) is False


def test_bare_switch_is_still_refused(guard, monkeypatch):
    """(c) Tokenising must not loosen the control — a real switch still blocks.

    The unquoted form is a non-regression assertion (green before and after).
    The quoted-verb form is the red one: the pre-tokenising regex required the
    verb to follow ``git`` literally, so ``git "switch" x`` slipped past it
    while the shell runs it exactly like the bare form.
    """
    _clear_overrides(monkeypatch)
    assert guard.is_branch_switch("git switch x") is True
    assert guard.is_branch_switch('git "switch" x') is True
    assert _run_main(guard, monkeypatch, "git switch x", _PRIMARY_GIT_DIR) == 2
    assert _run_main(guard, monkeypatch, 'git "switch" x', _PRIMARY_GIT_DIR) == 2


def test_unlexable_command_still_refuses(guard):
    """An unbalanced quote cannot be lexed — err toward refusing, never allowing."""
    assert guard.is_branch_switch('git checkout main "unclosed') is True


# ---------------------------------------------------------------------------
# Remote-container stand-down (OS#401 problem 1)
#
# A Claude Code web container is a plain ``.git`` clone with the branch already
# checked out, so ``in_main_worktree`` classifies it as the primary checkout and
# refuses every switch. The hazard the guard exists for — parallel sessions
# sharing one local tree — does not exist there: the container IS the isolation.
# The stand-down keys on the harness-set environment type and nothing else.
# ---------------------------------------------------------------------------


def test_remote_container_recognised_by_its_exact_value(guard):
    """(b) The one value that stands the guard down."""
    assert guard.in_remote_container({_REMOTE_ENV_VAR: "cloud_default"}) is True


@pytest.mark.parametrize(
    "value",
    ["", "local", "cloud", "CLOUD_DEFAULT", "cloud_default_x", " cloud_default", "1"],
)
def test_other_environment_type_values_stay_armed(guard, value):
    """(b) Anything but the exact remote value leaves the guard fully armed."""
    assert guard.in_remote_container({_REMOTE_ENV_VAR: value}) is False


def test_absent_environment_type_stays_armed(guard):
    """(a) The variable unset is the local case — fully armed."""
    assert guard.in_remote_container({}) is False


def test_stand_down_never_keys_on_the_override_var(guard):
    """The remote stand-down must not be reachable through CLAUDE_ALLOW_MAIN_GIT."""
    assert guard.in_remote_container({"CLAUDE_ALLOW_MAIN_GIT": "1"}) is False
    assert guard.in_remote_container({"CLAUDE_ALLOW_MAIN_GIT": "cloud_default"}) is False
    assert guard.in_remote_container({"GS_ALLOW_MAIN_GIT": "cloud_default"}) is False


def test_main_still_blocks_locally_with_the_variable_unset(guard, monkeypatch):
    """(a) The local refusal is unchanged when the remote variable is absent."""
    _clear_overrides(monkeypatch)
    assert _run_main(guard, monkeypatch, "git checkout main", _PRIMARY_GIT_DIR) == 2


def test_main_still_blocks_locally_on_a_foreign_variable_value(guard, monkeypatch):
    """(b) A non-remote value must not buy a stand-down."""
    _clear_overrides(monkeypatch)
    monkeypatch.setenv(_REMOTE_ENV_VAR, "local")
    assert _run_main(guard, monkeypatch, "git checkout main", _PRIMARY_GIT_DIR) == 2


def test_main_stands_down_in_a_remote_container(guard, monkeypatch):
    """(b) In the container the plain ``.git`` clone is no longer refused."""
    _clear_overrides(monkeypatch)
    monkeypatch.setenv(_REMOTE_ENV_VAR, "cloud_default")
    assert _run_main(guard, monkeypatch, "git checkout main", _PRIMARY_GIT_DIR) == 0

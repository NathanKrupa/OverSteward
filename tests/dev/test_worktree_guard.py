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
        "printf 'run git switch foo'",
        "grep -r 'git checkout' docs/",
    ],
)
def test_non_branch_switch_ignored(guard, cmd):
    assert guard.is_branch_switch(cmd) is False


def test_file_restore_with_path_after_double_dash(guard):
    assert guard.is_branch_switch("git checkout HEAD -- path/to/file") is False


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


def test_override_inline_standard(guard):
    assert guard.has_override("CLAUDE_ALLOW_MAIN_GIT=1 git checkout main") is True


def test_override_inline_alias(guard):
    assert guard.has_override("GS_ALLOW_MAIN_GIT=1 git switch x") is True


def test_override_env_standard(guard, monkeypatch):
    monkeypatch.setenv("CLAUDE_ALLOW_MAIN_GIT", "1")
    assert guard.has_override("git checkout main") is True


def test_no_override(guard, monkeypatch):
    monkeypatch.delenv("CLAUDE_ALLOW_MAIN_GIT", raising=False)
    monkeypatch.delenv("GS_ALLOW_MAIN_GIT", raising=False)
    assert guard.has_override("git checkout main") is False

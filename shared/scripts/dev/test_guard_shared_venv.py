# ABOUTME: Tests for the shared-venv mutation guard (.claude/hooks/guard_shared_venv.py).
# ABOUTME: Pure decision logic — env-mutating uv detection, symlinked-venv detection, override.

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_guard():
    """Load the deployed hook by file path (no package install needed).

    Walks up from this test file to the repo root (the dir containing
    ``.claude/hooks/guard_shared_venv.py``), so it works regardless of how
    deep ``tests/dev/`` sits.
    """
    rel = Path(".claude") / "hooks" / "guard_shared_venv.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("guard_shared_venv", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise FileNotFoundError(f"could not locate {rel} above {__file__}")


@pytest.fixture(scope="module")
def guard():
    return _load_guard()


# ---------------------------------------------------------------------------
# is_env_mutating — the uv verbs that rewrite a venv in place
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "uv sync",
        "uv sync --extra dev",
        "uv pip install -e .",
        "uv pip uninstall grantspider",
        "uv add httpx",
        "uv remove httpx",
        "uv lock --upgrade",
        "uv venv",
        "uv venv .venv",
        "cd /tmp/x && uv sync",
        "make clean; uv add ruff",
        "  uv sync --frozen",
        "FOO=bar uv sync",
    ],
)
def test_env_mutating_detected(guard, cmd):
    assert guard.is_env_mutating(cmd) is True


@pytest.mark.parametrize(
    "cmd",
    [
        "uv run pytest",
        "uv run python -m pytest",
        "uv pip list",
        "uv pip show httpx",
        "uv pip freeze",
        "uv lock",
        "uv lock --check",
        "uv tree",
        "uv --version",
        "pytest",
        "git status",
        "echo 'uv sync'",
        "grep -r 'uv pip install' docs/",
        "printf 'run uv add x'",
        "cat uv_sync_notes.md",
    ],
)
def test_non_mutating_ignored(guard, cmd):
    assert guard.is_env_mutating(cmd) is False


def test_mutating_verb_named(guard):
    assert guard.mutating_verb("cd /tmp && uv pip install -e .") == "uv pip install"
    assert guard.mutating_verb("uv sync --extra dev") == "uv sync"
    assert guard.mutating_verb("uv run pytest") is None


# ---------------------------------------------------------------------------
# venv_is_shared — a .venv symlink resolving outside the tree
# ---------------------------------------------------------------------------


def test_outward_symlink_is_shared(guard, tmp_path):
    primary = tmp_path / "primary"
    (primary / ".venv").mkdir(parents=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".venv").symlink_to(primary / ".venv")
    assert guard.venv_is_shared(str(worktree)) is True


def test_real_venv_directory_not_shared(guard, tmp_path):
    tree = tmp_path / "primary"
    (tree / ".venv").mkdir(parents=True)
    assert guard.venv_is_shared(str(tree)) is False


def test_inward_symlink_not_shared(guard, tmp_path):
    tree = tmp_path / "tree"
    (tree / "envs" / "real").mkdir(parents=True)
    (tree / ".venv").symlink_to(tree / "envs" / "real")
    assert guard.venv_is_shared(str(tree)) is False


def test_missing_venv_not_shared(guard, tmp_path):
    tree = tmp_path / "bare"
    tree.mkdir()
    assert guard.venv_is_shared(str(tree)) is False


def test_empty_tree_root_not_shared(guard):
    assert guard.venv_is_shared("") is False


def test_shared_venv_target_reported(guard, tmp_path):
    primary = tmp_path / "primary"
    (primary / ".venv").mkdir(parents=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".venv").symlink_to(primary / ".venv")
    assert guard.shared_venv_target(str(worktree)) == str((primary / ".venv").resolve())
    assert guard.shared_venv_target(str(primary)) is None


# ---------------------------------------------------------------------------
# has_override — env export or genuine leading assignment
# ---------------------------------------------------------------------------


def test_override_inline(guard, monkeypatch):
    monkeypatch.delenv("CLAUDE_ALLOW_SHARED_VENV_MUTATION", raising=False)
    assert guard.has_override("CLAUDE_ALLOW_SHARED_VENV_MUTATION=1 uv sync") is True


def test_override_env(guard, monkeypatch):
    monkeypatch.setenv("CLAUDE_ALLOW_SHARED_VENV_MUTATION", "1")
    assert guard.has_override("uv sync") is True


def test_no_override(guard, monkeypatch):
    monkeypatch.delenv("CLAUDE_ALLOW_SHARED_VENV_MUTATION", raising=False)
    assert guard.has_override("uv sync") is False


def test_quoted_override_mention_does_not_count(guard, monkeypatch):
    monkeypatch.delenv("CLAUDE_ALLOW_SHARED_VENV_MUTATION", raising=False)
    cmd = "echo 'CLAUDE_ALLOW_SHARED_VENV_MUTATION=1' && uv sync"
    assert guard.has_override(cmd) is False


def test_main_git_override_does_not_wave_this_guard_through(guard, monkeypatch):
    monkeypatch.delenv("CLAUDE_ALLOW_SHARED_VENV_MUTATION", raising=False)
    monkeypatch.setenv("CLAUDE_ALLOW_MAIN_GIT", "1")
    assert guard.has_override("uv sync") is False


# ---------------------------------------------------------------------------
# refusal_message — names the consequence, not just the rule
# ---------------------------------------------------------------------------


def test_refusal_message_names_verb_target_and_override(guard):
    message = guard.refusal_message("uv sync", "/home/u/repo/.venv")
    assert "uv sync" in message
    assert "/home/u/repo/.venv" in message
    assert "CLAUDE_ALLOW_SHARED_VENV_MUTATION=1" in message
    assert "removed" in message


# ---------------------------------------------------------------------------
# blocked_venv — the glued decision, naming the venv that would be damaged
# ---------------------------------------------------------------------------


@pytest.fixture
def shared_tree(tmp_path):
    primary = tmp_path / "primary"
    (primary / ".venv").mkdir(parents=True)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".venv").symlink_to(primary / ".venv")
    return str(worktree)


@pytest.fixture(autouse=True)
def _no_ambient_override(monkeypatch):
    monkeypatch.delenv("CLAUDE_ALLOW_SHARED_VENV_MUTATION", raising=False)


def test_blocks_mutation_in_shared_venv_tree(guard, shared_tree, tmp_path):
    expected = str((tmp_path / "primary" / ".venv").resolve())
    assert guard.blocked_venv("uv sync", shared_tree) == expected


def test_allows_read_only_command_in_shared_venv_tree(guard, shared_tree):
    assert guard.blocked_venv("uv run pytest", shared_tree) is None


def test_allows_mutation_with_override(guard, shared_tree):
    assert guard.blocked_venv("CLAUDE_ALLOW_SHARED_VENV_MUTATION=1 uv sync", shared_tree) is None


def test_allows_mutation_in_primary_checkout(guard, tmp_path):
    primary = tmp_path / "primary"
    (primary / ".venv").mkdir(parents=True)
    assert guard.blocked_venv("uv sync", str(primary)) is None


def test_allows_mutation_outside_a_git_tree(guard):
    assert guard.blocked_venv("uv sync", "") is None

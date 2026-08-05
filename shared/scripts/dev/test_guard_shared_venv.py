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
        # `uv run` syncs the project environment first, so it rebinds too.
        "uv run pytest",
        "uv run python -m pytest",
        "uv run --extra dev pytest",
    ],
)
def test_env_mutating_detected(guard, cmd):
    assert guard.is_env_mutating(cmd) is True


@pytest.mark.parametrize(
    "cmd",
    [
        "uv pip list",
        "uv pip show httpx",
        "uv pip freeze",
        "uv lock",
        "uv lock --check",
        "uv tree",
        "uv --version",
        # `uv tool run` / uvx use an ephemeral env, never the project's.
        "uv tool run ruff check .",
        "uvx ruff check .",
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
    assert guard.mutating_verb("uv run pytest") == "uv run"
    assert guard.mutating_verb("uv run --no-sync pytest") is None


# ---------------------------------------------------------------------------
# `uv run` — the sync it performs before running the command is the mutation,
# so only an explicit opt-out stands it down.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cmd",
    [
        "uv run --no-sync pytest",
        "uv run --no-sync python -m pytest",
        "UV_NO_SYNC=1 uv run pytest",
        "UV_NO_SYNC=true uv run pytest",
        "UV_NO_SYNC=yes uv run pytest",
        "cd /tmp/x && UV_NO_SYNC=1 uv run pytest",
    ],
)
def test_uv_run_with_the_sync_disabled_is_allowed(guard, cmd):
    assert guard.is_env_mutating(cmd) is False


@pytest.mark.parametrize(
    "cmd",
    [
        # A value uv does not read as true leaves the sync on.
        "UV_NO_SYNC=0 uv run pytest",
        "UV_NO_SYNC=false uv run pytest",
        "UV_NO_SYNC= uv run pytest",
        # The opt-out has to be this command's own, not a quoted mention.
        "echo 'UV_NO_SYNC=1' && uv run pytest",
        # Command position, not raw text.
        "foo && uv run pytest",
        "$(uv run pytest)",
    ],
)
def test_uv_run_without_a_real_opt_out_is_refused(guard, cmd):
    assert guard.mutating_verb(cmd) == "uv run"


def test_uv_run_is_allowed_when_no_sync_is_exported(guard, monkeypatch):
    """What ``new-session.sh`` writes into a shared-venv worktree's .envrc."""
    monkeypatch.setenv("UV_NO_SYNC", "1")
    assert guard.is_env_mutating("uv run pytest") is False


def test_exported_no_sync_is_overridden_by_the_command_s_own_assignment(guard, monkeypatch):
    """A ``VAR=value`` prefix wins over the export, exactly as the shell does."""
    monkeypatch.setenv("UV_NO_SYNC", "1")
    assert guard.mutating_verb("UV_NO_SYNC=0 uv run pytest") == "uv run"


def test_no_sync_does_not_excuse_the_other_verbs(guard):
    """``uv sync --no-sync`` is not a thing; the flag must not become a skeleton key."""
    assert guard.mutating_verb("UV_NO_SYNC=1 uv sync") == "uv sync"
    assert guard.mutating_verb("uv pip install --no-sync -e .") == "uv pip install"


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


def test_uv_run_refusal_names_both_opt_outs_and_the_direct_entry_point(guard):
    """A guard that blocks without naming the remedy just trains the override."""
    message = guard.refusal_message("uv run", "/home/u/repo/.venv")
    assert "uv run --no-sync" in message
    assert "UV_NO_SYNC=1 uv run" in message
    assert ".venv/bin/<tool>" in message


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
def _no_ambient_variables(monkeypatch):
    """Both switches start unset, so a session that exports one cannot green a test."""
    monkeypatch.delenv("CLAUDE_ALLOW_SHARED_VENV_MUTATION", raising=False)
    monkeypatch.delenv("UV_NO_SYNC", raising=False)


def test_blocks_mutation_in_shared_venv_tree(guard, shared_tree, tmp_path):
    expected = str((tmp_path / "primary" / ".venv").resolve())
    assert guard.blocked_venv("uv sync", shared_tree) == expected


def test_allows_read_only_command_in_shared_venv_tree(guard, shared_tree):
    assert guard.blocked_venv("uv pip list", shared_tree) is None


def test_blocks_bare_uv_run_in_shared_venv_tree(guard, shared_tree, tmp_path):
    expected = str((tmp_path / "primary" / ".venv").resolve())
    assert guard.blocked_venv("uv run pytest", shared_tree) == expected


@pytest.mark.parametrize(
    "cmd",
    [
        "uv run --no-sync pytest",
        "UV_NO_SYNC=1 uv run pytest",
        ".venv/bin/pytest",
        "CLAUDE_ALLOW_SHARED_VENV_MUTATION=1 uv run pytest",
    ],
)
def test_allows_the_sanctioned_ways_to_run_a_tool_in_shared_venv_tree(guard, shared_tree, cmd):
    assert guard.blocked_venv(cmd, shared_tree) is None


def test_allows_bare_uv_run_in_primary_checkout(guard, tmp_path):
    """A tree owning its venv rebinds nothing — the guard must stay out of the way."""
    primary = tmp_path / "primary"
    (primary / ".venv").mkdir(parents=True)
    assert guard.blocked_venv("uv run pytest", str(primary)) is None


def test_allows_mutation_with_override(guard, shared_tree):
    assert guard.blocked_venv("CLAUDE_ALLOW_SHARED_VENV_MUTATION=1 uv sync", shared_tree) is None


def test_allows_mutation_in_primary_checkout(guard, tmp_path):
    primary = tmp_path / "primary"
    (primary / ".venv").mkdir(parents=True)
    assert guard.blocked_venv("uv sync", str(primary)) is None


def test_allows_mutation_outside_a_git_tree(guard):
    assert guard.blocked_venv("uv sync", "") is None

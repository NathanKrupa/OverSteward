# ABOUTME: Tests for the per-worktree test database name (scripts/dev/worktree_db.py).
# ABOUTME: Primary vs worktree, slug folding, the 63-byte limit, collisions, the CLI.

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _locate(*relatives: str) -> Path:
    """Find the first of ``relatives`` that exists above this test file."""
    for parent in Path(__file__).resolve().parents:
        for relative in relatives:
            candidate = parent / relative
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(f"could not locate any of {relatives} above {__file__}")


SCRIPT = _locate("scripts/dev/worktree_db.py", "shared/scripts/dev/worktree_db.py")


@pytest.fixture(scope="module")
def wdb():
    spec = importlib.util.spec_from_file_location("worktree_db", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(tree: Path, *args: str) -> None:
    # Scrub GIT_* from the environment: these tests run under git hooks too
    # (pre-push exports GIT_DIR), and an inherited GIT_DIR would point every
    # scratch-repo command at the *hook's* repository instead of tmp_path.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    subprocess.run(["git", "-C", str(tree), *args], check=True, capture_output=True, env=env)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A real git repo with one commit — worktrees need a commit to branch from."""
    root = tmp_path / "grantspider"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("x")
    _git(root, "add", "README.md")
    _git(root, "commit", "-qm", "init")
    return root


# --- slug folding ---------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("gs-2043-ci-lock", "gs_2043_ci_lock"),
        ("GS-2043", "gs_2043"),
        ("feat.some/thing", "feat_some_thing"),
        ("__leading__", "leading"),
        ("a---b", "a_b"),
        ("2043-fix", "_2043_fix"),  # a bare leading digit is not a legal identifier
        ("", ""),
        ("///", ""),
    ],
)
def test_sanitize_folds_to_the_identifier_alphabet(wdb, raw: str, expected: str) -> None:
    assert wdb.sanitize(raw) == expected


def test_separator_runs_collapse_so_variants_agree(wdb) -> None:
    """``GS-2043.ci lock`` and ``gs_2043_ci_lock`` must not be two databases."""
    assert wdb.sanitize("GS-2043.ci lock") == wdb.sanitize("gs_2043_ci_lock")


# --- derivation -----------------------------------------------------------


def test_primary_checkout_keeps_the_unsuffixed_name(wdb) -> None:
    """Anything predating the split — docs, shell history — still resolves."""
    assert wdb.derive("grantspider_test", None) == "grantspider_test"


def test_worktree_gets_its_own_name(wdb) -> None:
    assert wdb.derive("grantspider_test", "gs-2043-ci-lock") == (
        "grantspider_test_gs_2043_ci_lock"
    )


def test_long_name_is_hashed_not_truncated(wdb) -> None:
    long_slug = "a" * 80
    name = wdb.derive("grantspider_test", long_slug, key="/one/path")
    assert len(name) <= wdb.MAX_IDENTIFIER
    assert name.startswith("grantspider_test_")


def test_names_sharing_a_long_prefix_do_not_collide(wdb) -> None:
    """Postgres would truncate both to the same identifier; the digest must not."""
    shared = "b" * 80
    first = wdb.derive("grantspider_test", shared, key="/trees/one")
    second = wdb.derive("grantspider_test", shared, key="/trees/two")
    assert first != second
    assert len(first) <= wdb.MAX_IDENTIFIER
    assert len(second) <= wdb.MAX_IDENTIFIER


def test_digest_survives_a_stem_that_fills_the_limit(wdb) -> None:
    """With no room for a slug the digest still has to fit — it carries uniqueness."""
    stem = "x" * 60
    first = wdb.derive(stem, "worktree", key="/trees/one")
    second = wdb.derive(stem, "worktree", key="/trees/two")
    assert first != second
    assert len(first) <= wdb.MAX_IDENTIFIER


def test_derivation_is_stable_across_calls(wdb) -> None:
    args = ("grantspider_test", "c" * 80)
    assert wdb.derive(*args, key="/trees/one") == wdb.derive(*args, key="/trees/one")


# --- against real checkouts ----------------------------------------------


def test_base_name_comes_from_the_repository_directory(wdb, checkout: Path) -> None:
    assert wdb.base_name(checkout) == "grantspider_test"


def test_primary_checkout_is_not_a_linked_worktree(wdb, checkout: Path) -> None:
    assert wdb.is_linked_worktree(checkout) is False
    assert wdb.database_name(checkout) == "grantspider_test"


def test_worktree_resolves_to_its_own_database(wdb, checkout: Path) -> None:
    worktree = checkout / ".claude" / "worktrees" / "gs-2043-ci-lock"
    worktree.parent.mkdir(parents=True)
    _git(checkout, "worktree", "add", "-q", "-b", "session/x", str(worktree))

    assert wdb.is_linked_worktree(worktree) is True
    assert wdb.database_name(worktree) == "grantspider_test_gs_2043_ci_lock"
    # The worktree must not answer with the primary's database — that shared
    # name is the whole defect.
    assert wdb.database_name(worktree) != wdb.database_name(checkout)


def test_two_worktrees_of_one_repo_get_two_databases(wdb, checkout: Path) -> None:
    names = []
    for slug in ("alpha", "beta"):
        worktree = checkout / ".claude" / "worktrees" / slug
        worktree.parent.mkdir(parents=True, exist_ok=True)
        _git(checkout, "worktree", "add", "-q", "-b", f"session/{slug}", str(worktree))
        names.append(wdb.database_name(worktree))
    assert len(set(names)) == 2


def test_base_override_wins(wdb, checkout: Path) -> None:
    assert wdb.database_name(checkout, base="other_test") == "other_test"


def test_outside_a_checkout_is_an_error_not_a_guess(wdb, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        wdb.database_name(tmp_path / "nowhere")


# --- CLI ------------------------------------------------------------------


def test_cli_prints_only_the_name(checkout: Path) -> None:
    """The Makefile captures this with ``$(shell …)`` — stray output becomes the URL."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--tree", str(checkout)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "grantspider_test\n"


def test_cli_reports_a_non_checkout_on_stderr(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--tree", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "not inside a git checkout" in result.stderr

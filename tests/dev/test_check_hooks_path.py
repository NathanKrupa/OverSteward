# ABOUTME: Tests check_hooks_path, and asserts THIS checkout's hooks path is not dangling (OS#379).
# ABOUTME: The negative fixture is a throwaway repo pointed at a directory that does not exist.

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load():
    path = REPO_ROOT / "scripts" / "dev" / "check_hooks_path.py"
    spec = importlib.util.spec_from_file_location("check_hooks_path", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


chp = _load()

# Assembled, not literal — see the note in the script under test.
HOOKS_PATH_KEY = "core." + "hooks" + "Path"


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    return root


def _set_hooks_path(root: Path, value: str) -> None:
    """Scoped with -C so it can never leak into the checkout running the test.

    An unscoped `git config` run from a cwd inside this repo is exactly how
    OverSteward acquired a hooks path pointing at a deleted pytest tmp dir
    (OS#379), so the fixture that reproduces the bug must not be able to cause it.
    """
    subprocess.run(["git", "-C", str(root), "config", HOOKS_PATH_KEY, value], check=True)


class TestCheck:
    def test_an_unset_hooks_path_is_a_measured_pass(self, tmp_path):
        code, message = chp.check(_repo(tmp_path))
        assert code == chp.EXIT_OK
        assert "unset" in message

    def test_a_hooks_path_that_exists_passes(self, tmp_path):
        root = _repo(tmp_path)
        (root / ".githooks").mkdir()
        _set_hooks_path(root, ".githooks")
        assert chp.check(root)[0] == chp.EXIT_OK

    def test_a_dangling_hooks_path_is_red(self, tmp_path):
        """The negative fixture: the exact OS#379 state."""
        root = _repo(tmp_path)
        _set_hooks_path(root, str(tmp_path / "pytest-of-nobody" / "gone" / ".no-hooks"))
        code, message = chp.check(root)
        assert code == chp.EXIT_DANGLING
        assert "does not exist" in message

    def test_a_dangling_relative_path_is_red_too(self, tmp_path):
        root = _repo(tmp_path)
        _set_hooks_path(root, ".hooks-that-were-never-created")
        assert chp.check(root)[0] == chp.EXIT_DANGLING

    def test_a_relative_path_resolves_against_the_worktree_top_not_the_cwd(self, tmp_path):
        root = _repo(tmp_path)
        (root / ".githooks").mkdir()
        _set_hooks_path(root, ".githooks")
        nested = root / "deep" / "nested"
        nested.mkdir(parents=True)
        assert chp.check(nested)[0] == chp.EXIT_OK

    def test_a_non_repo_is_could_not_look_not_a_pass(self, tmp_path):
        assert chp.check(tmp_path)[0] == chp.EXIT_COULD_NOT_LOOK

    def test_could_not_look_never_shares_a_code_with_ok_or_dangling(self):
        assert len({chp.EXIT_OK, chp.EXIT_DANGLING, chp.EXIT_COULD_NOT_LOOK}) == 3


class TestCli:
    def _run(self, root: Path):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "dev" / "check_hooks_path.py"),
             "--root", str(root)],
            capture_output=True, text=True, check=False,
        )

    def test_the_dangling_case_names_the_repair_command(self, tmp_path):
        root = _repo(tmp_path)
        _set_hooks_path(root, ".nope")
        result = self._run(root)
        assert result.returncode == chp.EXIT_DANGLING
        assert "install_hooks.sh" in result.stderr


class TestThisCheckout:
    """The live assertion — this is what would have caught OS#379 at any pytest run."""

    def test_this_checkouts_commit_gates_can_actually_run(self):
        code, message = chp.check(REPO_ROOT)
        assert code == chp.EXIT_OK, (
            f"this checkout's git hooks are not runnable: {message}\n"
            "Every commit-time gate here is silently off (OS#379)."
        )

    def test_the_repo_ships_the_hooks_directory_its_installer_points_at(self):
        assert (REPO_ROOT / ".githooks" / "pre-commit").is_file()

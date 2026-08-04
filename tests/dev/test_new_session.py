# ABOUTME: Tests for the session worktree bootstrapper (scripts/dev/new-session.sh).
# ABOUTME: Pins the two PYTHONPATH forms — deferred literal in .envrc, resolved path in the printout.

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "registry.yaml").is_file():
            return parent
    raise FileNotFoundError(f"could not locate repo root above {__file__}")


REPO_ROOT = _repo_root()
CANONICAL = REPO_ROOT / "shared" / "scripts" / "dev" / "new-session.sh"
DEPLOYED = REPO_ROOT / "scripts" / "dev" / "new-session.sh"

GIT_IDENTITY = (
    "-c",
    "user.email=test@example.invalid",
    "-c",
    "user.name=Test",
    "-c",
    "commit.gpgsign=false",
)


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *GIT_IDENTITY, *args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _make_repo(tmp_path: Path, *, with_src: bool) -> Path:
    """A throwaway repo with a real `origin`, mirroring what the script expects."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "--initial-branch=main", ".")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main", ".")
    if with_src:
        (repo / "src").mkdir()
        (repo / "src" / "mod.py").write_text("", encoding="utf-8")
    else:
        (repo / "manage.py").write_text("", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    return repo


def _run_new_session(script: Path, repo: Path, name: str) -> str:
    result = subprocess.run(
        ["bash", str(script), name, "origin/main"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.fixture(params=[CANONICAL, DEPLOYED], ids=["canonical", "deployed"])
def script(request: pytest.FixtureRequest) -> Path:
    return request.param


def test_printed_pythonpath_names_the_worktree_not_the_primary_checkout(
    script: Path, tmp_path: Path
) -> None:
    """The bug in #249: `$PWD` expanded at script-run time, naming the primary tree."""
    repo = _make_repo(tmp_path, with_src=True)
    stdout = _run_new_session(script, repo, "demo")

    worktree = repo / ".claude" / "worktrees" / "demo"
    assert f'export PYTHONPATH="{worktree / "src"}"' in stdout
    assert f'export PYTHONPATH="{repo / "src"}"' not in stdout


def test_printed_pythonpath_is_the_worktree_root_when_there_is_no_src_dir(
    script: Path, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path, with_src=False)
    stdout = _run_new_session(script, repo, "flat")

    worktree = repo / ".claude" / "worktrees" / "flat"
    assert f'export PYTHONPATH="{worktree}"' in stdout


def test_envrc_keeps_the_deferred_literal_for_direnv(script: Path, tmp_path: Path) -> None:
    """direnv expands `$PWD` inside the worktree, so the literal must survive verbatim."""
    repo = _make_repo(tmp_path, with_src=True)
    _run_new_session(script, repo, "demo")

    envrc = repo / ".claude" / "worktrees" / "demo" / ".envrc"
    assert envrc.read_text(encoding="utf-8") == 'export PYTHONPATH="$PWD/src"\n'


def test_envrc_deferred_literal_is_the_worktree_root_when_there_is_no_src_dir(
    script: Path, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path, with_src=False)
    _run_new_session(script, repo, "flat")

    envrc = repo / ".claude" / "worktrees" / "flat" / ".envrc"
    assert envrc.read_text(encoding="utf-8") == 'export PYTHONPATH="$PWD"\n'


def test_teardown_instruction_routes_through_the_worktree_doctor(
    script: Path, tmp_path: Path
) -> None:
    """#263: removing a captured worktree breaks every checkout on the shared venv.

    One verb, not a two-step: teardown also drops the worktree's test database,
    which a bare ``git worktree remove`` leaves behind on the shared container.
    """
    repo = _make_repo(tmp_path, with_src=True)
    stdout = _run_new_session(script, repo, "demo")

    worktree = repo / ".claude" / "worktrees" / "demo"
    assert f'scripts/dev/worktree_doctor.py teardown "{worktree}"' in stdout
    assert "git worktree remove" not in stdout


def test_deployed_copy_is_byte_identical_to_canonical() -> None:
    """new-session.sh is a canonical byte-copy; drift here is drift estate-wide."""
    assert DEPLOYED.read_bytes() == CANONICAL.read_bytes()


def _instructed_scripts() -> list[str]:
    """Repo-relative `scripts/dev/...` paths the printed instructions tell the user to run."""
    text = CANONICAL.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"\bscripts/dev/[\w.-]+", text)))


@pytest.mark.parametrize("relpath", _instructed_scripts())
def test_every_instructed_script_is_deployed_and_canonical(relpath: str) -> None:
    """The #255 gap: the printout named a file this repo had never deployed."""
    deployed = REPO_ROOT / relpath
    canonical = REPO_ROOT / "shared" / relpath
    assert deployed.is_file(), f"new-session.sh instructs `{relpath}`, which does not exist here"
    assert deployed.read_bytes() == canonical.read_bytes()


@pytest.mark.parametrize("stray", [".envrc", ".venv"])
def test_worktree_bootstrap_artifacts_are_ignored(stray: str) -> None:
    """new-session.sh writes both into every worktree; untracked strays invite `git add -A`."""
    ignored = subprocess.run(
        ("git", "check-ignore", "--quiet", stray),
        cwd=REPO_ROOT,
        capture_output=True,
    )
    assert ignored.returncode == 0, f"`{stray}` is not gitignored"

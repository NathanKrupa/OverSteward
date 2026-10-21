# ABOUTME: Tests for the session worktree bootstrapper (scripts/dev/new-session.sh).
# ABOUTME: Pins the two PYTHONPATH forms — deferred literal in .envrc, resolved path in the printout.

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
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
DOCTOR = REPO_ROOT / "shared" / "scripts" / "dev" / "worktree_doctor.py"

#: A hand-written direnv file of the kind ai-assistants commits — the content
#: new-session.sh replaced there (OS#608).
REPO_ENVRC = "# the repository's own direnv setup\nsource .venv/bin/activate\ndotenv_if_exists\n"
TRACKED_NOTE = "this repo tracks its own .envrc"

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


def _make_repo(
    tmp_path: Path,
    *,
    with_src: bool,
    with_venv: bool = False,
    tracked_envrc: str | None = None,
) -> Path:
    """A throwaway repo with a real `origin`, mirroring what the script expects.

    ``tracked_envrc`` commits a ``.envrc`` with that content, as ai-assistants
    and grantspider do (OS#608).
    """
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
    if tracked_envrc is not None:
        (repo / ".envrc").write_text(tracked_envrc, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    if with_venv:
        # Untracked, exactly as a real checkout's venv is — the script symlinks
        # the worktree's .venv at it, which is what makes the venv shared.
        (repo / ".venv" / "bin").mkdir(parents=True)
    return repo


def _run_new_session(
    script: Path, repo: Path, name: str, env: dict[str, str] | None = None
) -> str:
    result = subprocess.run(
        ["bash", str(script), name, "origin/main"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=env,
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


def test_envrc_disables_the_implicit_sync_when_the_venv_is_shared(
    script: Path, tmp_path: Path
) -> None:
    """#294: bare `uv run` syncs, and the sync rebinds the borrowed venv here."""
    repo = _make_repo(tmp_path, with_src=True, with_venv=True)
    _run_new_session(script, repo, "demo")

    envrc = repo / ".claude" / "worktrees" / "demo" / ".envrc"
    assert envrc.read_text(encoding="utf-8") == (
        'export PYTHONPATH="$PWD/src"\nexport UV_NO_SYNC=1\n'
    )


def test_banner_explains_the_shared_venv_when_there_is_one(script: Path, tmp_path: Path) -> None:
    """Enforcement without the ergonomic path just teaches people the override."""
    repo = _make_repo(tmp_path, with_src=True, with_venv=True)
    stdout = _run_new_session(script, repo, "demo")

    assert "UV_NO_SYNC=1" in stdout
    assert ".venv/bin/<tool>" in stdout


def test_banner_stays_silent_about_uv_when_the_worktree_owns_no_venv(
    script: Path, tmp_path: Path
) -> None:
    """A repo with no venv to borrow gets no advice about one."""
    repo = _make_repo(tmp_path, with_src=True)
    stdout = _run_new_session(script, repo, "demo")

    assert "UV_NO_SYNC" not in stdout


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


# ---------------------------------------------------------------------------
# a repository that tracks its own .envrc (OS#608)
# ---------------------------------------------------------------------------


def _lines(stdout: str) -> list[str]:
    return [line.strip() for line in stdout.splitlines()]


def test_a_tracked_envrc_is_left_byte_identical_to_head(script: Path, tmp_path: Path) -> None:
    """ai-assistants #108: the script replaced 18 lines of the repo's own file."""
    repo = _make_repo(tmp_path, with_src=True, with_venv=True, tracked_envrc=REPO_ENVRC)
    _run_new_session(script, repo, "demo")

    worktree = repo / ".claude" / "worktrees" / "demo"
    assert ".envrc" not in _git(worktree, "status", "--porcelain")
    assert (worktree / ".envrc").read_bytes() == REPO_ENVRC.encode("utf-8")
    assert _git(worktree, "show", "HEAD:.envrc") == REPO_ENVRC


def test_a_tracked_envrc_moves_the_exports_into_the_banner(script: Path, tmp_path: Path) -> None:
    """What the script declined to write, the human is told to export themselves."""
    repo = _make_repo(tmp_path, with_src=True, with_venv=True, tracked_envrc=REPO_ENVRC)
    stdout = _run_new_session(script, repo, "demo")

    worktree = repo / ".claude" / "worktrees" / "demo"
    lines = _lines(stdout)
    assert TRACKED_NOTE in stdout
    assert f'export PYTHONPATH="{worktree / "src"}"' in lines
    assert "export UV_NO_SYNC=1" in lines
    assert "a .envrc was written" not in stdout


def test_a_tracked_envrc_without_a_shared_venv_asks_for_no_uv_export(
    script: Path, tmp_path: Path
) -> None:
    """UV_NO_SYNC guards a borrowed venv; with none to borrow there is nothing to guard."""
    repo = _make_repo(tmp_path, with_src=False, tracked_envrc=REPO_ENVRC)
    stdout = _run_new_session(script, repo, "flat")

    worktree = repo / ".claude" / "worktrees" / "flat"
    assert TRACKED_NOTE in stdout
    assert f'export PYTHONPATH="{worktree}"' in _lines(stdout)
    assert "UV_NO_SYNC" not in stdout
    assert (worktree / ".envrc").read_bytes() == REPO_ENVRC.encode("utf-8")


def _git_that_cannot_answer_ls_files(tmp_path: Path) -> dict[str, str]:
    """A PATH whose ``git`` fails ``ls-files`` the way a broken index does (exit 128)."""
    real_git = shutil.which("git")
    assert real_git, "git is not on PATH"
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text(
        "#!/bin/sh\n"
        'case " $* " in *" ls-files "*) echo "fatal: index file corrupt" >&2; exit 128;; esac\n'
        f'exec "{real_git}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return {**os.environ, "PATH": f"{shim_dir}{os.pathsep}{os.environ['PATH']}"}


def test_a_git_that_cannot_answer_reads_as_tracked(script: Path, tmp_path: Path) -> None:
    """Only git's own "did not match" (exit 1) licenses the write; any other failure does not.

    The repo tracks no ``.envrc``, so the write would have been safe here — but
    the script cannot know that, and keeping its hands off costs one export.
    """
    repo = _make_repo(tmp_path, with_src=True, with_venv=True)
    stdout = _run_new_session(script, repo, "demo", env=_git_that_cannot_answer_ls_files(tmp_path))

    worktree = repo / ".claude" / "worktrees" / "demo"
    assert not (worktree / ".envrc").exists()
    assert TRACKED_NOTE in stdout
    assert "export UV_NO_SYNC=1" in _lines(stdout)


def test_a_tracked_envrc_worktree_tears_down_through_the_doctor(
    script: Path, tmp_path: Path
) -> None:
    """ai-assistants #108 end to end: teardown refused until a manual ``git restore``.

    ``--no-docker`` because the removal is the step under test and the fixture
    owns no database; the docker leg runs after the removal and cannot change it.
    """
    repo = _make_repo(tmp_path, with_src=True, with_venv=True, tracked_envrc=REPO_ENVRC)
    _run_new_session(script, repo, "demo")
    worktree = repo / ".claude" / "worktrees" / "demo"

    result = subprocess.run(
        [sys.executable, str(DOCTOR), "teardown", str(worktree), "--no-docker"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not worktree.exists()
    assert (repo / ".envrc").read_bytes() == REPO_ENVRC.encode("utf-8")

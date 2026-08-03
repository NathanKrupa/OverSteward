# ABOUTME: Tests for the worktree doctor (scripts/dev/worktree_doctor.py).
# ABOUTME: Captured shebangs, captured editable .pth, docker capture, clean tree, idempotent repair.

from __future__ import annotations

import importlib.util
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


SCRIPT = _locate("scripts/dev/worktree_doctor.py", "shared/scripts/dev/worktree_doctor.py")
CANONICAL = _locate("shared/scripts/dev/worktree_doctor.py")


@pytest.fixture(scope="module")
def doctor():
    spec = importlib.util.spec_from_file_location("worktree_doctor", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves annotations through
    # sys.modules[cls.__module__], which is None for an unregistered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeDocker:
    """A docker seam under test control — records every argv, returns canned stdout."""

    def __init__(self, output: str = "") -> None:
        self.output = output
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str | None:
        self.calls.append(args)
        return self.output


def _make_repo(tmp_path: Path, *, captured: bool) -> tuple[Path, Path]:
    """A checkout with a venv, plus a session worktree that borrows it.

    ``captured`` decides whether the venv's console script and editable pointer
    name the worktree (the bug) or the checkout itself (healthy).
    """
    repo = tmp_path / "repo"
    worktree = repo / ".claude" / "worktrees" / "demo"
    (worktree / "src").mkdir(parents=True)
    (repo / "src").mkdir()

    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").write_text("", encoding="utf-8")
    (worktree / ".venv").symlink_to(repo / ".venv")

    owner = worktree if captured else repo
    (venv_bin / "alembic").write_text(
        f"#!{owner}/.venv/bin/python\n# -*- coding: utf-8 -*-\nimport alembic\n", encoding="utf-8"
    )
    site = repo / ".venv" / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (site / "__editable__.demo-0.1.0.pth").write_text(f"{owner}/src\n", encoding="utf-8")
    return repo, worktree


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )


# ---------------------------------------------------------------------------
# uncapture_path — the one path rewrite both repairs are built on
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("captured", "expected"),
    [
        ("/home/n/Repo/.claude/worktrees/wt/.venv/bin/python", "/home/n/Repo/.venv/bin/python"),
        ("/home/n/Repo/.claude/worktrees/wt/src", "/home/n/Repo/src"),
        ("/home/n/Repo/.claude/worktrees/wt", "/home/n/Repo"),
    ],
)
def test_uncapture_path_rewrites_through_the_worktree(doctor, captured, expected):
    assert doctor.uncapture_path(captured) == expected


@pytest.mark.parametrize(
    "path",
    ["/home/n/Repo/.venv/bin/python", "/usr/bin/python3", "", "/home/n/Repo/src"],
)
def test_uncapture_path_leaves_uncaptured_paths_alone(doctor, path):
    assert doctor.uncapture_path(path) is None


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def test_check_detects_a_captured_console_script_shebang(tmp_path):
    repo, worktree = _make_repo(tmp_path, captured=True)
    result = _run("check", str(worktree), "--repo", str(repo), "--no-docker")

    assert result.returncode != 0
    assert "alembic" in result.stdout
    assert "shebang" in result.stdout.lower()


def test_check_detects_a_captured_editable_pth(tmp_path):
    repo, worktree = _make_repo(tmp_path, captured=True)
    result = _run("check", str(worktree), "--repo", str(repo), "--no-docker")

    assert result.returncode != 0
    assert "__editable__.demo-0.1.0.pth" in result.stdout


def test_check_is_silent_and_clean_for_an_uncaptured_worktree(tmp_path):
    repo, worktree = _make_repo(tmp_path, captured=False)
    result = _run("check", str(worktree), "--repo", str(repo), "--no-docker")

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_check_detects_a_compose_project_stamped_on_a_container(doctor, tmp_path):
    repo, worktree = _make_repo(tmp_path, captured=False)
    docker = FakeDocker("9fa1c0de\tdemo-db-1\n")

    hits = doctor.check_worktree(worktree, [repo / ".venv"], docker=docker)

    assert [hit.kind for hit in hits] == [doctor.DOCKER_CAPTURE]
    assert "demo-db-1" in hits[0].where
    assert f"label=com.docker.compose.project.working_dir={worktree}" in " ".join(docker.calls[0])


def test_check_survives_a_machine_without_docker(doctor, tmp_path):
    repo, worktree = _make_repo(tmp_path, captured=False)

    assert doctor.check_worktree(worktree, [repo / ".venv"], docker=lambda args: None) == []


# ---------------------------------------------------------------------------
# repair
# ---------------------------------------------------------------------------


def test_repair_repoints_shebang_and_editable_pth_at_the_primary_checkout(tmp_path):
    repo, _ = _make_repo(tmp_path, captured=True)
    result = _run("repair", "--repo", str(repo), "--no-docker")

    assert result.returncode == 0
    script = repo / ".venv" / "bin" / "alembic"
    assert script.read_text(encoding="utf-8").splitlines()[0] == f"#!{repo}/.venv/bin/python"
    pth = repo / ".venv" / "lib" / "python3.12" / "site-packages" / "__editable__.demo-0.1.0.pth"
    assert pth.read_text(encoding="utf-8") == f"{repo}/src\n"


def test_repair_leaves_the_rest_of_a_console_script_untouched(tmp_path):
    repo, _ = _make_repo(tmp_path, captured=True)
    _run("repair", "--repo", str(repo), "--no-docker")

    body = (repo / ".venv" / "bin" / "alembic").read_text(encoding="utf-8").splitlines()[1:]
    assert body == ["# -*- coding: utf-8 -*-", "import alembic"]


def test_repair_leaves_an_uncaptured_pth_byte_for_byte_alone(doctor, tmp_path):
    """Not even a normalising rewrite: a write to shared state must mean a real fix."""
    repo, _ = _make_repo(tmp_path, captured=False)
    site = repo / ".venv" / "lib" / "python3.12" / "site-packages"
    other = site / "_virtualenv.pth"
    other.write_bytes(b"import _virtualenv")  # no trailing newline, as venv ships it

    assert doctor.repair_venv(repo / ".venv") == []
    assert other.read_bytes() == b"import _virtualenv"


def test_repair_is_idempotent(tmp_path):
    repo, _ = _make_repo(tmp_path, captured=True)
    first = _run("repair", "--repo", str(repo), "--no-docker")
    after_first = (repo / ".venv" / "bin" / "alembic").read_bytes()

    second = _run("repair", "--repo", str(repo), "--no-docker")

    assert first.returncode == second.returncode == 0
    assert (repo / ".venv" / "bin" / "alembic").read_bytes() == after_first
    assert "nothing to repair" in second.stdout.lower()


def test_repair_reports_a_stale_container_without_removing_it(doctor, tmp_path):
    repo, _ = _make_repo(tmp_path, captured=False)
    gone = tmp_path / "repo" / ".claude" / "worktrees" / "deleted"
    docker = FakeDocker(f"9fa1c0de\tdemo-db-1\t{gone}\n")

    report = doctor.stale_container_report(docker=docker)

    assert any("docker rm -f 9fa1c0de" in line for line in report)
    assert docker.calls[0][0] == "ps"
    assert "rm" not in docker.calls[0]


def test_repair_never_shells_out_to_sudo(tmp_path):
    """Privilege escalation is the human's call — the doctor only prints the line."""
    repo, _ = _make_repo(tmp_path, captured=True)
    _run("repair", "--repo", str(repo), "--no-docker")

    source = CANONICAL.read_text(encoding="utf-8")
    for line in source.splitlines():
        code = line.split("#", 1)[0]
        assert "subprocess" not in code or "sudo" not in code


def test_repair_emits_a_sudo_line_for_a_root_owned_skeleton(doctor, tmp_path):
    repo, _ = _make_repo(tmp_path, captured=False)
    skeleton = repo / ".claude" / "worktrees" / "deleted"
    skeleton.mkdir()

    report = doctor.skeleton_report(repo, is_root_owned=lambda path: True)

    assert any(f"sudo rm -rf {skeleton}" in line for line in report)


def test_a_live_worktree_is_not_reported_as_a_skeleton(doctor, tmp_path):
    repo, worktree = _make_repo(tmp_path, captured=False)
    (worktree / ".git").write_text(f"gitdir: {repo}/.git/worktrees/demo\n", encoding="utf-8")

    assert doctor.skeleton_report(repo, is_root_owned=lambda path: True) == []


# ---------------------------------------------------------------------------
# byte-copy family discipline
# ---------------------------------------------------------------------------


def test_deployed_copy_is_byte_identical_to_canonical() -> None:
    assert SCRIPT.read_bytes() == CANONICAL.read_bytes()

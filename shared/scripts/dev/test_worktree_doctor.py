# ABOUTME: Tests for the worktree doctor (scripts/dev/worktree_doctor.py).
# ABOUTME: Captured shebangs, captured editable .pth, docker capture, clean tree, idempotent repair.

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


def _find(*relatives: str) -> Path | None:
    """The first of ``relatives`` that exists above this test file, or None."""
    for parent in Path(__file__).resolve().parents:
        for relative in relatives:
            candidate = parent / relative
            if candidate.is_file():
                return candidate
    return None


def _locate(*relatives: str) -> Path:
    found = _find(*relatives)
    if found is None:
        raise FileNotFoundError(f"could not locate any of {relatives} above {__file__}")
    return found


SCRIPT = _locate("scripts/dev/worktree_doctor.py", "shared/scripts/dev/worktree_doctor.py")

#: Only OverSteward holds the canonical source; a pickup repo has the deployed
#: copy and no ``shared/`` tree at all. Absence must skip the byte-identity
#: assertion, not raise at import — a module-scope raise fails COLLECTION, which
#: takes every other test in this file down with it in exactly the repos the
#: family exists to serve.
CANONICAL = _find("shared/scripts/dev/worktree_doctor.py")


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
    docker = ScriptedDocker(
        {
            "ps -a": "9fa1c0de\tdemo-db-1\n",
            "range .Mounts": f"{worktree}/data\n",
        }
    )

    hits = doctor.check_worktree(worktree, [repo / ".venv"], docker=docker)

    assert [hit.kind for hit in hits] == [doctor.DOCKER_CAPTURE]
    assert "demo-db-1" in hits[0].where
    # The label is still the cheap candidate filter, even though the bind mount
    # is what decides.
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
    """Privilege escalation is the human's call — the doctor only prints the line.

    Asserted against ``SCRIPT``, the copy that actually ran above. ``CANONICAL``
    is absent in a pickup repo, and the file whose behaviour is in question is
    the deployed one anyway.
    """
    repo, _ = _make_repo(tmp_path, captured=True)
    _run("repair", "--repo", str(repo), "--no-docker")

    source = SCRIPT.read_text(encoding="utf-8")
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


@pytest.mark.skipif(CANONICAL is None, reason="no shared/ tree — this is a pickup repo")
def test_deployed_copy_is_byte_identical_to_canonical() -> None:
    assert CANONICAL is not None
    assert SCRIPT.read_bytes() == CANONICAL.read_bytes()


# ---------------------------------------------------------------------------
# the worktree's database on the shared test container
# ---------------------------------------------------------------------------


class ScriptedDocker:
    """A docker seam that answers per-argv, so a query can be told apart from a drop.

    ``psql``/``dropdb`` calls are modelled the way libpq actually behaves: with no
    ``-d``, the client connects to a database named after the *user*, and a
    connection to a database that does not exist fails outright. A fake that
    answered on the SQL text alone would pass a probe that can never connect —
    which is exactly the defect this models (OS#278).
    """

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        *,
        databases: frozenset[str] = frozenset(),
        user: str = "grantspider",
    ) -> None:
        self.responses = responses or {}
        self.databases = databases
        self.user = user
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str | None:
        self.calls.append(args)
        if args[:1] == ["exec"] and ("psql" in args or "dropdb" in args):
            flag = "-d" if "psql" in args else "--maintenance-db"
            target = args[args.index(flag) + 1] if flag in args else self.user
            if target not in self.databases:
                return None  # FATAL: database "<target>" does not exist
        for marker, output in self.responses.items():
            if marker in " ".join(args):
                return output
        return ""


def _bench_docker(database: str, *, container: str = "grantspider-test-pg") -> ScriptedDocker:
    """A container running postgres that holds ``database``.

    ``grantspider`` — the superuser's name — is deliberately NOT a database here,
    because it is not one on any estate container: ``POSTGRES_DB`` is
    ``<project>_test``, never ``<project>``.
    """
    return ScriptedDocker(
        {
            "ps --format": f"{container}\nsome-unrelated-app\n",
            f"inspect --format {{{{range .Config.Env}}}}{{{{println .}}}}{{{{end}}}} {container}": (
                "POSTGRES_USER=grantspider\nPOSTGRES_PASSWORD=testpass\n"
            ),
            f"datname = '{database}'": "1\n",
        },
        databases=frozenset({"postgres", "grantspider_test", database}),
    )


def test_the_worktrees_database_is_found_on_the_shared_container(doctor, tmp_path):
    _, worktree = _make_repo(tmp_path, captured=False)
    docker = _bench_docker("repo_test_demo")

    hits = doctor.database_hits(worktree, docker, name="repo_test_demo")

    assert len(hits) == 1
    assert hits[0].kind == doctor.DATABASE_OWNED
    assert "repo_test_demo" in hits[0].detail
    assert "grantspider-test-pg" in hits[0].where


def test_no_database_no_hit(doctor, tmp_path):
    _, worktree = _make_repo(tmp_path, captured=False)
    docker = ScriptedDocker({"ps --format": "grantspider-test-pg\n"})

    assert doctor.database_hits(worktree, docker, name="repo_test_demo") == []


def test_a_container_that_is_not_postgres_is_skipped(doctor, tmp_path):
    """No POSTGRES_USER means the image is not a postgres — never exec into it."""
    _, worktree = _make_repo(tmp_path, captured=False)
    docker = ScriptedDocker({"ps --format": "redis\n"})

    doctor.database_hits(worktree, docker, name="repo_test_demo")

    assert not any(call[0] == "exec" for call in docker.calls)


def test_the_database_does_not_block_removal(doctor, tmp_path):
    """It is owned state to drop, not capture that breaks another checkout.

    ``check`` exits non-zero on capture; if a database counted, every teardown
    of every worktree would be blocked forever.
    """
    _, worktree = _make_repo(tmp_path, captured=False)
    docker = _bench_docker("repo_test_demo")

    assert doctor.check_worktree(worktree, [], docker=docker) == []


def test_dropping_the_database_targets_the_right_container(doctor, tmp_path):
    _, worktree = _make_repo(tmp_path, captured=False)
    docker = _bench_docker("repo_test_demo")

    dropped = doctor.drop_database(worktree, docker, name="repo_test_demo")

    assert dropped == ["repo_test_demo (grantspider-test-pg)"]
    drops = [call for call in docker.calls if "dropdb" in call]
    assert drops, "no dropdb issued"
    assert drops[0][:3] == ["exec", "grantspider-test-pg", "dropdb"]
    assert "--if-exists" in drops[0]
    assert drops[0][-1] == "repo_test_demo"


def test_dropping_an_absent_database_is_a_no_op(doctor, tmp_path):
    _, worktree = _make_repo(tmp_path, captured=False)
    docker = ScriptedDocker({"ps --format": "grantspider-test-pg\n"})

    assert doctor.drop_database(worktree, docker, name="repo_test_demo") == []
    assert not any("dropdb" in call for call in docker.calls)


def test_teardown_drops_the_database_then_removes_the_worktree(doctor, tmp_path):
    repo, worktree = _make_repo(tmp_path, captured=False)
    docker = _bench_docker("repo_test_demo")
    removed: list[Path] = []

    rc = doctor.teardown(
        worktree,
        [doctor.venv_of(repo)],
        docker=docker,
        remove=removed.append,
        name="repo_test_demo",
    )

    assert rc == 0
    assert removed == [worktree]
    assert any("dropdb" in call for call in docker.calls)


def test_teardown_refuses_while_something_still_points_here(doctor, tmp_path):
    """Capture first, drop second: a blocked teardown must change nothing."""
    repo, worktree = _make_repo(tmp_path, captured=True)
    docker = _bench_docker("repo_test_demo")
    removed: list[Path] = []

    rc = doctor.teardown(
        worktree,
        [doctor.venv_of(repo)],
        docker=docker,
        remove=removed.append,
        name="repo_test_demo",
    )

    assert rc == 1
    assert removed == []
    assert not any("dropdb" in call for call in docker.calls)


def _git(tree: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(tree), *args], check=True, capture_output=True)


def _make_git_repo(tmp_path: Path) -> tuple[Path, Path]:
    """A real checkout with a real linked worktree — the database name needs git.

    Built git-first: ``git worktree add`` refuses a directory that already has
    content, so the venv scaffolding goes on afterwards.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("x", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")

    worktree = repo / ".claude" / "worktrees" / "demo"
    worktree.parent.mkdir(parents=True)
    _git(repo, "worktree", "add", "-q", "-b", "session/demo", str(worktree))

    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").write_text("", encoding="utf-8")
    (worktree / ".venv").symlink_to(repo / ".venv")
    return repo, worktree


def test_check_names_the_database_without_blocking_removal(tmp_path, monkeypatch):
    """The operator must see the database; it must not fail the gate."""
    repo, worktree = _make_git_repo(tmp_path)
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *"--format {{.Names}}"*) echo repo-test-pg ;;\n'
        '  *"{{range .Config.Env}}"*) echo POSTGRES_USER=repo ;;\n'
        "  *pg_database*) echo 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{__import__('os').environ['PATH']}")

    result = _run("check", str(worktree), "--repo", str(repo))

    assert result.returncode == 0
    assert "repo_test_demo" in result.stdout


def test_the_probe_names_a_database_it_can_actually_connect_to(doctor, tmp_path):
    """OS#278: ``psql -U <user>`` with no ``-d`` connects to a database named
    after the user, which no estate container has — so the probe never ran and
    every worktree looked database-free."""
    _, worktree = _make_repo(tmp_path, captured=False)
    docker = _bench_docker("repo_test_demo")

    doctor.database_hits(worktree, docker, name="repo_test_demo")

    probes = [call for call in docker.calls if "psql" in call]
    assert probes, "no psql probe issued"
    assert "-d" in probes[0], "psql must be told which database to connect to"
    assert probes[0][probes[0].index("-d") + 1] != "grantspider", (
        "connecting to a database named after the superuser is the OS#278 bug"
    )


def test_the_drop_connects_through_a_maintenance_database(doctor, tmp_path):
    """``dropdb`` cannot connect to the database it is dropping."""
    _, worktree = _make_repo(tmp_path, captured=False)
    docker = _bench_docker("repo_test_demo")

    doctor.drop_database(worktree, docker, name="repo_test_demo")

    drops = [call for call in docker.calls if "dropdb" in call]
    assert drops, "no dropdb issued"
    assert "--maintenance-db" in drops[0]
    assert drops[0][drops[0].index("--maintenance-db") + 1] != "repo_test_demo"


def test_a_container_that_only_carries_the_stale_label_is_not_capture(doctor, tmp_path):
    """A shared bench keeps whichever tree ran ``compose up`` first in its label.

    Under one fixed compose project name the bench container outlives every
    worktree, so its ``working_dir`` is an accident of who created it. With no
    bind mount under the worktree there is nothing for docker to re-materialise,
    and treating the label alone as capture blocks that tree's teardown forever.
    """
    _, worktree = _make_repo(tmp_path, captured=False)
    docker = ScriptedDocker(
        {
            "ps -a": "7c1182b75f03\tgrantspider-test-pg\n",
            "range .Mounts": "",  # a named volume only — no bind
        }
    )

    assert doctor.check_worktree(worktree, [], docker=docker) == []


def test_a_container_bind_mounting_the_worktree_is_capture(doctor, tmp_path):
    """The real breakage: docker re-creates the path as root-owned dirs."""
    _, worktree = _make_repo(tmp_path, captured=False)
    docker = ScriptedDocker(
        {
            "ps -a": "7c1182b75f03\tdemo-db-1\n",
            "range .Mounts": f"{worktree}/scripts/init.sql\n",
        }
    )

    hits = doctor.check_worktree(worktree, [], docker=docker)

    assert [hit.kind for hit in hits] == [doctor.DOCKER_CAPTURE]
    assert "init.sql" in hits[0].detail


def test_a_bind_mount_merely_sharing_a_prefix_is_not_capture(doctor, tmp_path):
    """``/wt/demo-old`` is not inside ``/wt/demo``."""
    _, worktree = _make_repo(tmp_path, captured=False)
    docker = ScriptedDocker(
        {
            "ps -a": "7c1182b75f03\tdemo-db-1\n",
            "range .Mounts": f"{worktree}-old/scripts/init.sql\n",
        }
    )

    assert doctor.check_worktree(worktree, [], docker=docker) == []

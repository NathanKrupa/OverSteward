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
DB_SCRIPT = _locate("scripts/dev/worktree_db.py", "shared/scripts/dev/worktree_db.py")

#: Only OverSteward holds the canonical source; a pickup repo has the deployed
#: copy and no ``shared/`` tree at all. Absence must skip the byte-identity
#: assertion, not raise at import — a module-scope raise fails COLLECTION, which
#: takes every other test in this file down with it in exactly the repos the
#: family exists to serve.
CANONICAL = _find("shared/scripts/dev/worktree_doctor.py")

#: This file, and its canonical twin. The doctor's tests are deployed the same
#: way the doctor is, so they drift the same way — and nothing was watching.
TESTS = _locate("tests/dev/test_worktree_doctor.py", "shared/scripts/dev/test_worktree_doctor.py")
CANONICAL_TESTS = _find("shared/scripts/dev/test_worktree_doctor.py")


def _import(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves annotations through
    # sys.modules[cls.__module__], which is None for an unregistered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def doctor():
    return _import("worktree_doctor", SCRIPT)


@pytest.fixture(scope="module")
def wdb():
    """The name derivation itself — a test must never recompute what it asserts."""
    return _import("worktree_db", DB_SCRIPT)


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


@pytest.mark.skipif(CANONICAL_TESTS is None, reason="no shared/ tree — this is a pickup repo")
def test_this_test_file_is_byte_identical_to_canonical() -> None:
    """The regression tests deploy with the script, or a pickup repo runs unguarded.

    The script had this assertion from the start; the tests did not, and drifted
    the first time a fix was written against ``tests/dev/`` alone. A repo that
    picks up the doctor gets whatever ``shared/scripts/dev/`` holds — so a test
    that never reached the canonical copy protects nowhere but here.
    """
    assert CANONICAL_TESTS is not None
    assert TESTS.read_bytes() == CANONICAL_TESTS.read_bytes()


# ---------------------------------------------------------------------------
# the worktree's database on the shared test container
# ---------------------------------------------------------------------------


#: A second stem, the way aigranthelper keeps one: nothing shares a prefix
#: with the project name, so only the derivation can find it.
RESEARCH = "test_research_demo"

#: The container was asked what databases it serves — the step that must
#: happen while the worktree still exists.
LISTED = "listed"


class ScriptedDocker:
    """A docker seam that answers per-argv, so a query can be told apart from a drop.

    ``psql``/``dropdb`` calls are modelled the way libpq actually behaves: with no
    ``-d``, the client connects to a database named after the *user*, and a
    connection to a database that does not exist fails outright. A fake that
    answered on the SQL text alone would pass a probe that can never connect —
    which is exactly the defect this models (OS#278).

    ``events`` records what the container was actually made to do, in order, so a
    test can assert that the drop came *after* the worktree was removed.
    """

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        *,
        databases: frozenset[str] = frozenset(),
        user: str = "grantspider",
        events: list[str] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.databases = databases
        self.user = user
        self.events = [] if events is None else events
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str | None:
        self.calls.append(args)
        if args[:1] == ["exec"] and ("psql" in args or "dropdb" in args):
            flag = "-d" if "psql" in args else "--maintenance-db"
            target = args[args.index(flag) + 1] if flag in args else self.user
            if target not in self.databases:
                return None  # FATAL: database "<target>" does not exist
            if "dropdb" in args:
                self.events.append(f"dropped {args[-1]}")
            elif args[-1].startswith("SELECT datname"):
                self.events.append(LISTED)
                return "".join(f"{name}\n" for name in sorted(self.databases))
        for marker, output in self.responses.items():
            if marker in " ".join(args):
                return output
        return ""


def _bench_docker(
    *databases: str, container: str = "grantspider-test-pg", events: list[str] | None = None
) -> ScriptedDocker:
    """A container running postgres that serves ``databases``.

    ``repo_test`` is always there: it is the primary checkout's own database, and
    every discovery test needs the bench present to prove it is left alone.
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
        },
        databases=frozenset({"postgres", "grantspider_test", "repo_test", *databases}),
        events=events,
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


def test_teardown_names_then_removes_then_drops(doctor, tmp_path):
    """The order IS the fix (OS#286): nothing irreversible until nothing can fail.

    The names must be taken while the worktree exists — they are derived from
    its path — and the drop must come after the removal git can still refuse.
    """
    repo, worktree = _make_repo(tmp_path, captured=False)
    events: list[str] = []
    docker = _bench_docker("repo_test_demo", events=events)

    rc = doctor.teardown(
        worktree,
        [doctor.venv_of(repo)],
        docker=docker,
        remove=lambda path: events.append(f"removed {path}"),
        name="repo_test_demo",
    )

    assert rc == 0
    assert events == [LISTED, f"removed {worktree}", "dropped repo_test_demo"]


def test_a_refused_removal_leaves_every_database_intact(doctor, tmp_path, capsys):
    """OS#286: a worktree that will not go must still have its databases."""
    repo, worktree = _make_repo(tmp_path, captured=False)
    docker = _bench_docker("repo_test_demo", RESEARCH)

    def refuse(path: Path) -> None:
        raise doctor.WorktreeRemovalRefused(f"'{path}' contains modified or untracked files")

    rc = doctor.teardown(
        worktree, [doctor.venv_of(repo)], docker=docker, remove=refuse, name="repo_test_demo"
    )

    assert rc == 1
    assert not any("dropdb" in call for call in docker.calls)
    assert "contains modified or untracked files" in capsys.readouterr().out


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


def _make_git_repo(
    tmp_path: Path, name: str = "demo", *, tracked: tuple[str, ...] = ()
) -> tuple[Path, Path]:
    """A real checkout with a real linked worktree — the database name needs git.

    Built git-first: ``git worktree add`` refuses a directory that already has
    content, so the venv scaffolding goes on afterwards.

    ``tracked`` names files committed *before* the worktree is added, so the
    worktree checks them out under version control — grantspider's ``.envrc``
    is one (OS#308).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("x", encoding="utf-8")
    _git(repo, "add", "README.md")
    for relative in tracked:
        (repo / relative).write_text(f"committed {relative}\n", encoding="utf-8")
        _git(repo, "add", relative)
    _git(repo, "commit", "-qm", "init")

    worktree = repo / ".claude" / "worktrees" / name
    worktree.parent.mkdir(parents=True)
    _git(repo, "worktree", "add", "-q", "-b", f"session/{name}", str(worktree))

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
        "  *pg_database*) echo repo_test; echo repo_test_demo ;;\n"
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


# ---------------------------------------------------------------------------
# a worktree can own more than one database (OS#283)
# ---------------------------------------------------------------------------


def _named(hits) -> set[str]:
    return {hit.detail for hit in hits}


def test_check_names_every_database_the_worktree_owns(doctor, tmp_path):
    """aigranthelper keeps two per checkout, and the second stem shares no prefix.

    Nothing tells the doctor that ``test_research`` is a stem of this repo; both
    names are found because both were derived from the worktree's own path.
    """
    _, worktree = _make_git_repo(tmp_path)
    docker = _bench_docker("repo_test_demo", RESEARCH)

    named = _named(doctor.database_hits(worktree, docker))

    assert named == {"database repo_test_demo", f"database {RESEARCH}"}


def test_teardown_drops_every_database_the_worktree_owns(doctor, tmp_path):
    """Dropping one and removing the worktree orphans the other forever."""
    _, worktree = _make_git_repo(tmp_path)
    events: list[str] = []
    docker = _bench_docker("repo_test_demo", RESEARCH, events=events)

    rc = doctor.teardown(worktree, [], docker=docker, remove=lambda path: events.append("removed"))

    assert rc == 0
    assert events == [LISTED, "removed", "dropped repo_test_demo", f"dropped {RESEARCH}"]


def test_a_hashed_database_is_found_by_its_digest_suffix(doctor, wdb, tmp_path):
    """Past 63 bytes the slug is cut away and only the path digest is left to match."""
    long_name = "os-286-283-teardown-with-a-name-long-enough-to-overflow-the-identifier-limit"
    _, worktree = _make_git_repo(tmp_path, name=long_name)
    hashed = wdb.database_name(worktree)
    digest = hashed.rsplit("_", 1)[1]
    docker = _bench_docker(hashed, f"test_research_{digest}")

    named = _named(doctor.database_hits(worktree, docker))

    assert not hashed.endswith(wdb.sanitize(long_name)), "not a shortened name — test is vacuous"
    assert named == {f"database {hashed}", f"database test_research_{digest}"}


def test_a_primary_checkout_owns_no_databases(doctor, tmp_path):
    """The unsuffixed database is the shared bench — reporting it invites its loss."""
    repo, _ = _make_git_repo(tmp_path)
    docker = _bench_docker("repo_test_demo")

    assert doctor.database_hits(repo, docker) == []
    assert doctor.drop_database(repo, docker) == []
    assert not any("dropdb" in call for call in docker.calls)


def test_the_shared_bench_survives_a_worktree_whose_slug_is_the_stem(doctor, tmp_path):
    """A worktree named ``test`` derives ``_test`` — what every bench name ends with.

    ``grantspider_test`` belongs to another repo on the same container and
    ``repo_test`` is this repo's own; neither is worktree-owned. The name is
    ambiguous, so discovery stands down to the one certain name — the extra
    stem this worktree may also own is knowingly not found, which orphans a
    database rather than destroying a shared one.
    """
    _, worktree = _make_git_repo(tmp_path, name="test")
    docker = _bench_docker("repo_test_test", "test_research_test")

    named = _named(doctor.database_hits(worktree, docker))

    assert named == {"database repo_test_test"}


# ---------------------------------------------------------------------------
# the removal itself (OS#286)
# ---------------------------------------------------------------------------


def test_new_session_scaffolding_does_not_block_the_removal(doctor, tmp_path):
    """The launcher's own untracked ``.venv`` symlink and ``.envrc`` refused every teardown."""
    _, worktree = _make_git_repo(tmp_path)
    (worktree / ".envrc").write_text('export PYTHONPATH="$PWD/src"\n', encoding="utf-8")

    doctor.remove_worktree(worktree)

    assert not worktree.exists()


def test_an_unexpected_untracked_file_still_refuses_the_removal(doctor, tmp_path):
    """``--force`` would discard real work — the loss this family exists to prevent."""
    _, worktree = _make_git_repo(tmp_path)
    (worktree / "notes.md").write_text("a session's uncommitted work\n", encoding="utf-8")

    with pytest.raises(doctor.WorktreeRemovalRefused):
        doctor.remove_worktree(worktree)

    assert (worktree / "notes.md").read_text(encoding="utf-8") == "a session's uncommitted work\n"


def test_a_real_venv_directory_is_never_deleted_as_scaffolding(doctor, tmp_path):
    """The launcher writes a symlink; a private venv is an environment, not scaffolding."""
    _, worktree = _make_git_repo(tmp_path)
    (worktree / ".venv").unlink()
    (worktree / ".venv" / "bin").mkdir(parents=True)

    doctor.clear_launcher_scaffolding(worktree)

    assert (worktree / ".venv" / "bin").is_dir()


def test_a_tracked_envrc_is_never_deleted_as_scaffolding(doctor, tmp_path):
    """OS#308: grantspider commits its ``.envrc``, so the name alone proves nothing.

    The launcher's ``.venv`` symlink still goes — the rule is *tracked*, not
    *named ``.envrc``*.
    """
    _, worktree = _make_git_repo(tmp_path, tracked=(".envrc",))

    cleared = doctor.clear_launcher_scaffolding(worktree)

    assert (worktree / ".envrc").read_text(encoding="utf-8") == "committed .envrc\n"
    assert cleared == [".venv"]


def test_a_worktree_whose_envrc_is_tracked_tears_down(doctor, tmp_path):
    """The grantspider shape end to end — previously blocked on every retry.

    Deleting the tracked file left ` D .envrc` behind, so git refused; the next
    attempt deleted it again. The worktree could never go through the sanctioned
    path.
    """
    _, worktree = _make_git_repo(tmp_path, tracked=(".envrc",))

    doctor.remove_worktree(worktree)

    assert not worktree.exists()


def _snapshot(tree: Path) -> dict[str, str]:
    """Every path under ``tree`` and what it holds — symlinks by target, files by text."""
    contents: dict[str, str] = {}
    for path in sorted(tree.rglob("*")):
        key = str(path.relative_to(tree))
        if path.is_symlink():
            contents[key] = f"-> {path.readlink()}"
        elif path.is_file():
            contents[key] = path.read_text(encoding="utf-8", errors="replace")
    return contents


def test_a_refused_removal_leaves_the_working_tree_byte_identical(doctor, tmp_path):
    """OS#286 promised a refused teardown changes nothing. OS#308 broke the tree half.

    The refusal was always clean about the databases; it was not clean about the
    working tree, because the scaffolding clear ran *before* the step git can
    still refuse. The operator was left restoring by hand what the doctor
    deleted on the way to failing.
    """
    _, worktree = _make_git_repo(tmp_path, tracked=(".envrc",))
    (worktree / "notes.md").write_text("a session's uncommitted work\n", encoding="utf-8")
    before = _snapshot(worktree)

    with pytest.raises(doctor.WorktreeRemovalRefused):
        doctor.remove_worktree(worktree)

    assert _snapshot(worktree) == before


def test_a_refused_teardown_keeps_the_launcher_symlink(doctor, tmp_path):
    """Through the full verb, with the real removal — the symlink is a mutation too."""
    repo, worktree = _make_git_repo(tmp_path)
    (worktree / "notes.md").write_text("a session's uncommitted work\n", encoding="utf-8")
    docker = _bench_docker("repo_test_demo")

    rc = doctor.teardown(
        worktree,
        [doctor.venv_of(repo)],
        docker=docker,
        remove=doctor.remove_worktree,
        name="repo_test_demo",
    )

    assert rc == 1
    assert (worktree / ".venv").is_symlink()
    assert not any("dropdb" in call for call in docker.calls)


# ---------------------------------------------------------------------------
# sweep — the databases whose worktree is already gone (OS#296)
# ---------------------------------------------------------------------------


def _orphans(candidates) -> set[str]:
    return {candidate.database for candidate in candidates if candidate.claimed_by is None}


def _databases(candidates) -> set[str]:
    return {candidate.database for candidate in candidates}


def test_sweep_finds_a_database_whose_worktree_is_gone(doctor, tmp_path):
    """The recovery direction: enumerate what exists, subtract what is live.

    ``repo_test_ghost`` is what a ``git worktree remove --force`` leaves behind —
    the path that named it is gone, so no forward derivation can reach it again.
    """
    repo, worktree = _make_git_repo(tmp_path)
    docker = _bench_docker("repo_test_demo", "repo_test_ghost")

    candidates = doctor.sweep_candidates(repo, docker)

    assert _orphans(candidates) == {"repo_test_ghost"}
    assert {c.database: c.claimed_by for c in candidates if c.claimed_by} == {
        "repo_test_demo": worktree
    }


def test_sweep_never_reports_the_shared_bench(doctor, tmp_path):
    """The primary checkout's unsuffixed name is every session's bench, not an orphan."""
    repo, _ = _make_git_repo(tmp_path)
    docker = _bench_docker("repo_test_demo")

    assert "repo_test" not in _databases(doctor.sweep_candidates(repo, docker))


def test_sweep_never_reports_another_repos_database(doctor, tmp_path):
    """One container serves several repos; a sweep run from here claims only here."""
    repo, _ = _make_git_repo(tmp_path)
    docker = _bench_docker("grantspider_test_gs_2044")

    assert doctor.sweep_candidates(repo, docker) == []


def test_sweep_finds_an_orphan_on_a_second_stem(doctor, tmp_path):
    """Nothing can tell this file that ``test_research`` is a stem of this repo.

    A *live* worktree reveals it: every database it owns ends with the suffix its
    own path derives, and what stands in front of that suffix is a stem.
    """
    repo, _ = _make_git_repo(tmp_path)
    docker = _bench_docker("repo_test_demo", RESEARCH, "test_research_ghost")

    assert _orphans(doctor.sweep_candidates(repo, docker)) == {"test_research_ghost"}


def test_a_live_worktree_with_a_hashed_name_is_not_swept(doctor, wdb, tmp_path):
    """Past 63 bytes the slug is cut away — only the path digest still matches."""
    long_name = "os-296-orphan-sweep-with-a-name-long-enough-to-overflow-the-identifier-limit"
    repo, worktree = _make_git_repo(tmp_path, name=long_name)
    hashed = wdb.database_name(worktree)
    docker = _bench_docker(hashed)

    assert not hashed.endswith(wdb.sanitize(long_name)), "not a shortened name — test is vacuous"
    assert _orphans(doctor.sweep_candidates(repo, docker)) == set()


def test_a_worktree_named_test_never_makes_a_bench_an_orphan(doctor, tmp_path):
    """``_test`` is the suffix every bench name ends with, so it reveals no stem.

    Read as one, ``repo_test`` would yield the stem ``repo`` — and every bench on
    the container would then look like an orphan of it.
    """
    repo, _ = _make_git_repo(tmp_path, name="test")
    docker = _bench_docker("repo_test_test")

    candidates = doctor.sweep_candidates(repo, docker)

    assert _orphans(candidates) == set()
    assert not {"repo_test", "grantspider_test"} & _databases(candidates)


def test_the_default_sweep_destroys_nothing(doctor, tmp_path, capsys):
    """A heuristic match may not destroy on its own say-so."""
    repo, _ = _make_git_repo(tmp_path)
    docker = _bench_docker("repo_test_ghost")

    rc = doctor.sweep(repo, docker)

    assert rc == 1
    assert not any("dropdb" in call for call in docker.calls)
    assert "repo_test_ghost" in capsys.readouterr().out


def test_sweep_drops_only_the_orphan_and_only_when_told(doctor, tmp_path):
    repo, _ = _make_git_repo(tmp_path)
    docker = _bench_docker("repo_test_demo", "repo_test_ghost")

    rc = doctor.sweep(repo, docker, drop=True)

    assert rc == 0
    assert [call[-1] for call in docker.calls if "dropdb" in call] == ["repo_test_ghost"]


def test_sweep_names_what_each_candidate_was_matched_against(doctor, tmp_path, capsys):
    """The inference is absence, not derivation — the operator has to audit it."""
    repo, worktree = _make_git_repo(tmp_path)
    docker = _bench_docker("repo_test_demo", "repo_test_ghost")

    doctor.sweep(repo, docker)

    printed = capsys.readouterr().out
    assert str(worktree) in printed
    assert "repo_test_demo" in printed


def test_sweep_refuses_when_docker_will_not_answer(doctor, tmp_path):
    """Silence is not an empty container — that is an orphan wearing a success message."""
    repo, _ = _make_git_repo(tmp_path)

    with pytest.raises(doctor.CouldNotLook):
        doctor.sweep_candidates(repo, lambda args: None)


def test_sweep_refuses_when_no_postgres_is_running(doctor, tmp_path):
    """A stopped bench still holds every database; it just cannot be asked."""
    repo, _ = _make_git_repo(tmp_path)
    docker = ScriptedDocker({"ps --format": "redis\n"})

    with pytest.raises(doctor.CouldNotLook):
        doctor.sweep_candidates(repo, docker)


def _deployed(tmp_path: Path, *sources: Path) -> Path:
    """The deploy shape a pickup repo gets: named files, no ``shared/`` tree, no siblings."""
    target = tmp_path / "deployed"
    target.mkdir()
    for source in sources:
        (target / source.name).write_bytes(source.read_bytes())
    return target / "worktree_doctor.py"


def _fake_docker(tmp_path: Path, *databases: str) -> None:
    """A ``docker`` on PATH that answers the three reads the sweep makes."""
    listing = "".join(f"echo {name}; " for name in databases)
    script = tmp_path / "docker"
    script.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *"--format {{.Names}}"*) echo repo-test-pg ;;\n'
        '  *"{{range .Config.Env}}"*) echo POSTGRES_USER=repo ;;\n'
        f"  *pg_database*) {listing};;\n"
        "esac\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


def test_a_doctor_without_the_derivation_refuses_the_sweep(tmp_path):
    """``_load_worktree_db`` tolerates absence — a sweep inheriting that would lie.

    With no derivation the sweep matches nothing, and nothing reads as "the
    container is clean" when the truth is "I could not look". Stdout must stay
    empty: a refusal belongs on stderr, where nothing mistakes it for a result.
    """
    repo, _ = _make_git_repo(tmp_path)
    lone = _deployed(tmp_path, SCRIPT)

    result = subprocess.run(
        [sys.executable, str(lone), "sweep", "--repo", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout.strip() == ""
    assert "worktree_db" in result.stderr


def test_the_cli_sweeps_a_materialised_copy_through_repo(tmp_path, monkeypatch):
    """``--repo`` is what makes the doctor work outside its own checkout.

    That path must not need ``guard_shared_venv.py`` either: the sweep looks at
    databases, not venvs, and the guard is not deployed beside this copy.
    """
    repo, _ = _make_git_repo(tmp_path)
    lone = _deployed(tmp_path, SCRIPT, DB_SCRIPT)
    _fake_docker(tmp_path, "postgres", "repo_test", "repo_test_demo", "repo_test_ghost")
    monkeypatch.setenv("PATH", f"{tmp_path}:{__import__('os').environ['PATH']}")

    result = subprocess.run(
        [sys.executable, str(lone), "sweep", "--repo", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, result.stderr
    assert "repo_test_ghost" in result.stdout


def test_the_cli_refuses_a_sweep_it_was_told_not_to_look_at(tmp_path):
    """``--no-docker`` leaves a docker-only verb nothing to reconcile against."""
    repo, _ = _make_git_repo(tmp_path)

    result = _run("sweep", "--repo", str(repo), "--no-docker")

    assert result.returncode == 2
    assert result.stdout.strip() == ""
    assert "reconcile" in result.stderr


# ---------------------------------------------------------------------------
# a doctor that cannot derive a name must not act (OS#305)
# ---------------------------------------------------------------------------


def test_ownership_refuses_rather_than_reporting_an_unowned_tree(doctor, tmp_path, monkeypatch):
    """``UNOWNED`` is a finding. "I could not derive any name" is not one.

    Folding them together is what let a teardown remove the worktree and report
    success while dropping nothing.
    """
    _, worktree = _make_git_repo(tmp_path)
    monkeypatch.setattr(doctor, "_load_worktree_db", lambda: None)

    with pytest.raises(doctor.CouldNotLook):
        doctor._ownership(worktree)


def test_a_primary_checkout_is_still_genuinely_unowned(doctor, tmp_path):
    """The sentinel must keep working where it means what it says."""
    repo, _ = _make_git_repo(tmp_path)

    assert doctor._ownership(repo) == doctor.UNOWNED


def test_teardown_refuses_before_removing_when_it_cannot_derive(doctor, tmp_path, monkeypatch):
    """The refusal has to land before the removal, or the names are unreachable forever.

    Once the path is gone no forward derivation can reach those databases again —
    the asymmetry that made this worse in ``teardown`` than in ``sweep``.
    """
    repo, worktree = _make_git_repo(tmp_path)
    docker = _bench_docker("repo_test_demo")
    removed: list[Path] = []
    monkeypatch.setattr(doctor, "_load_worktree_db", lambda: None)

    with pytest.raises(doctor.CouldNotLook):
        doctor.teardown(worktree, [doctor.venv_of(repo)], docker=docker, remove=removed.append)

    assert removed == []
    assert not any("dropdb" in call for call in docker.calls)


def test_a_lone_doctor_refuses_the_teardown_and_removes_nothing(tmp_path, monkeypatch):
    """The shape that actually occurs: the doctor materialised **alone** at a scratch path.

    Agents extract it there because a checkout's own copy is stale, and the
    sanctioned workaround silently disarmed half the tool — four orphan
    databases in one dispatch. Stdout must stay empty: nothing may read as a
    result the verb never reached.
    """
    repo, worktree = _make_git_repo(tmp_path)
    lone = _deployed(tmp_path, SCRIPT)
    _fake_docker(tmp_path, "postgres", "repo_test", "repo_test_demo")
    monkeypatch.setenv("PATH", f"{tmp_path}:{__import__('os').environ['PATH']}")

    result = subprocess.run(
        [sys.executable, str(lone), "teardown", str(worktree), "--repo", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout.strip() == ""
    assert "worktree_db" in result.stderr
    assert worktree.is_dir()


def test_the_pair_tears_the_same_worktree_down(tmp_path, monkeypatch):
    """The negative control in the same run: extracted *with* its sibling, it works.

    Without this beside the refusal, a doctor broken outright would pass the
    test above for the wrong reason.
    """
    repo, worktree = _make_git_repo(tmp_path)
    pair = _deployed(tmp_path, SCRIPT, DB_SCRIPT)
    _fake_docker(tmp_path, "postgres", "repo_test", "repo_test_demo")
    monkeypatch.setenv("PATH", f"{tmp_path}:{__import__('os').environ['PATH']}")

    result = subprocess.run(
        [sys.executable, str(pair), "teardown", str(worktree), "--repo", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not worktree.exists()


def test_a_lone_doctor_refuses_the_check_it_cannot_answer(tmp_path):
    """``check`` reports owned databases; with no derivation it reports none of them."""
    repo, worktree = _make_git_repo(tmp_path)
    lone = _deployed(tmp_path, SCRIPT)

    result = subprocess.run(
        [sys.executable, str(lone), "check", str(worktree), "--repo", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "worktree_db" in result.stderr


def test_a_no_docker_teardown_says_the_databases_were_left(doctor, tmp_path, capsys):
    """Explicit intent, but the same silence — and silence reads as "there were none"."""
    _, worktree = _make_git_repo(tmp_path)

    rc = doctor.teardown(worktree, [], docker=None, remove=lambda path: None)

    assert rc == 0
    assert "neither named nor dropped" in capsys.readouterr().out

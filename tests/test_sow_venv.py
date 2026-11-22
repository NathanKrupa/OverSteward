# ABOUTME: Tests for sow --verify's environment: a worktree venv built from the branch's uv.lock.
# ABOUTME: Real git temp repos and temp venvs; the uv builder is faked at its seam, so nothing downloads.

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from oversteward.sow.apply import ABORTED, DEPLOYED
from oversteward.sow.runners import CommandResult, MakeCommand, SowError, VenvBuilder
from oversteward.sow.venv import (
    LockedVenvPlan,
    carried_installs,
    ci_sync_args,
    lock_package_names,
    locked_venv_plan,
)
from tests.test_sow import (  # noqa: F401 — fixtures are used by name
    _apply,
    _git,
    _scrub_git_env,
    _write,
    canon,
    pickup,
)

# --------------------------------------------------------------------------
# what CI syncs

CONTINUED_SYNC = """
jobs:
  test:
    steps:
      - uses: actions/checkout@v4
      - name: Install
        # The prior form -- ``uv pip install --system -e ".[full,dev]"`` -- is gone.
        run: |
          uv sync --locked --extra full --extra dev \\
            --python "${{ steps.setup-python.outputs.python-path }}"
      - run: uv pip install --quiet --no-deps -e .
"""

LAYERED_SYNC = """
# A full ``uv sync --all-extras`` would pull the ML runtime, so the light job skips it.
jobs:
  light:
    steps:
      - run: uv pip install lint-tool pytest
  test:
    steps:
      - name: Install project dependencies
        run: uv sync --extra dev
      - run: uv pip install "git+https://example.invalid/sibling.git@abc1234"
  heavy:
    steps:
      - run: |
          # uv sync --extra ignored-in-a-comment
          uv sync --extra dev && uv run --no-sync pytest
"""


def test_a_multi_line_sync_yields_every_extra_and_drops_the_ci_interpreter():
    assert ci_sync_args(CONTINUED_SYNC) == ("--extra", "full", "--extra", "dev")


def test_only_run_scripts_are_read_never_comments_or_prose():
    assert ci_sync_args(LAYERED_SYNC) == ("--extra", "dev")


def test_a_ci_that_never_runs_uv_sync_reads_as_none():
    text = 'jobs:\n  t:\n    steps:\n      - run: uv pip install --system -e ".[dev]"\n'
    assert ci_sync_args(text) is None


def test_a_sync_with_no_extras_is_a_sync_not_none():
    assert ci_sync_args("jobs:\n  t:\n    steps:\n      - run: uv sync --locked\n") == ()


def test_extras_union_across_jobs_in_first_seen_order():
    text = (
        "jobs:\n  a:\n    steps:\n      - run: uv sync --extra dev\n"
        "  b:\n    steps:\n      - run: uv sync --extra=full --extra dev\n"
    )
    assert ci_sync_args(text) == ("--extra", "dev", "--extra", "full")


def test_all_extras_anywhere_means_all_of_them():
    text = (
        "jobs:\n  a:\n    steps:\n      - run: uv sync --extra dev\n"
        "  b:\n    steps:\n      - run: uv sync --all-extras\n"
    )
    assert ci_sync_args(text) == ("--all-extras",)


@pytest.mark.parametrize("flag", ["--group lint", "--no-dev", "--only-group docs", "--package x"])
def test_a_sync_flag_that_changes_the_install_set_is_refused(flag: str):
    with pytest.raises(SowError, match="cannot reproduce"):
        ci_sync_args(f"jobs:\n  t:\n    steps:\n      - run: uv sync --extra dev {flag}\n")


def test_an_extra_flag_with_no_value_is_refused():
    with pytest.raises(SowError, match="no extra named"):
        ci_sync_args("jobs:\n  t:\n    steps:\n      - run: uv sync --extra\n")


def test_an_unparseable_workflow_is_refused_not_read_as_no_sync():
    with pytest.raises(SowError, match="could not be parsed"):
        ci_sync_args("jobs: [unclosed\n")


# --------------------------------------------------------------------------
# the lock, and what the shared venv layers beyond it

LOCK = """version = 1
requires-python = ">=3.12"

[[package]]
name = "pickup"
version = "0.1.0"
source = { editable = "." }

[[package]]
name = "Lint_Tool"
version = "1.0.1"
source = { registry = "https://pypi.org/simple" }
"""


def test_lock_names_are_normalized():
    assert lock_package_names(LOCK) == frozenset({"pickup", "lint-tool"})


def test_an_unparseable_lock_is_refused():
    with pytest.raises(SowError, match="uv.lock could not be parsed"):
        lock_package_names("[[package]\n")


def _dist(venv: Path, name: str, direct_url: dict | None) -> Path:
    info = venv / "lib" / "python3.12" / "site-packages" / f"{name}-0.1.0.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\n", encoding="utf-8")
    if direct_url is not None:
        (info / "direct_url.json").write_text(json.dumps(direct_url), encoding="utf-8")
    return info


def test_only_a_local_directory_install_the_lock_does_not_name_is_carried(tmp_path: Path):
    venv = tmp_path / "shared"
    _dist(venv, "sibling", {"url": "file:///home/x/sibling", "dir_info": {}})
    _dist(venv, "pickup", {"url": "file:///home/x/pickup", "dir_info": {"editable": True}})
    _dist(venv, "lint_tool", {"url": "file:///home/x/lint", "dir_info": {}})
    _dist(venv, "remote", {"url": "https://example.invalid/remote.whl", "archive_info": {}})
    _dist(venv, "plain", None)
    assert carried_installs(venv, lock_package_names(LOCK)) == (("/home/x/sibling",),)


def test_an_editable_carried_install_stays_editable(tmp_path: Path):
    venv = tmp_path / "shared"
    _dist(venv, "sibling", {"url": "file:///home/x/my%20sib", "dir_info": {"editable": True}})
    assert carried_installs(venv, frozenset()) == (("-e", "/home/x/my sib"),)


def _uv_target(root: Path, ci: str = "jobs:\n  t:\n    steps:\n      - run: uv sync --extra dev\n"):
    _write(root, "uv.lock", LOCK)
    _write(root, ".github/workflows/ci.yml", ci)


def test_a_plan_needs_both_the_lock_and_a_ci_sync(tmp_path: Path):
    shared = tmp_path / "shared"
    only_ci = tmp_path / "only-ci"
    _write(only_ci, ".github/workflows/ci.yml", "jobs:\n  t:\n    steps:\n      - run: uv sync\n")
    only_lock = tmp_path / "only-lock"
    _write(only_lock, "uv.lock", LOCK)
    no_sync = tmp_path / "no-sync"
    _uv_target(no_sync, "jobs:\n  t:\n    steps:\n      - run: pip install -e .\n")
    both = tmp_path / "both"
    _uv_target(both)
    assert locked_venv_plan(only_ci, shared) is None
    assert locked_venv_plan(only_lock, shared) is None
    assert locked_venv_plan(no_sync, shared) is None
    assert locked_venv_plan(both, shared) == LockedVenvPlan(("--extra", "dev"), ())


# --------------------------------------------------------------------------
# the uv connector's real command line


def test_the_builder_runs_step_6a_locked_inside_the_worktree(tmp_path: Path):
    wt = tmp_path / "wt"
    commands = VenvBuilder().commands(wt, ("--extra", "dev"), (("/home/x/sibling",),))
    assert commands == [
        ["uv", "venv", str(wt / ".venv")],
        ["uv", "sync", "--locked", "--extra", "dev"],
        ["uv", "pip", "install", "--python", str(wt / ".venv/bin/python"), "/home/x/sibling"],
    ]


def test_the_builder_names_the_worktree_venv_and_drops_an_inherited_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "shared"))
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / "shared"))
    env = VenvBuilder().environment(tmp_path / "wt")
    assert env["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / "wt" / ".venv")
    assert "VIRTUAL_ENV" not in env


def _fake_uv(tmp_path: Path, fail_on: str = "") -> tuple[Path, Path]:
    """A `uv` that records argv, cwd and its uv environment, one line per call."""
    record = tmp_path / "uv-calls"
    script = tmp_path / "bin" / "uv"
    script.parent.mkdir(parents=True)
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s|%s|%s|%s\\n" "$*" "$(pwd)" "$UV_PROJECT_ENVIRONMENT" '
        f'"${{VIRTUAL_ENV-unset}}" >> "{record}"\n'
        f'[ "$1" = "{fail_on}" ] && {{ echo "uv refused $1" >&2; exit 1; }}\n'
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, record


def test_the_builder_runs_every_command_in_the_worktree_and_logs_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("VIRTUAL_ENV", "/somewhere/else")
    uv, record = _fake_uv(tmp_path)
    wt = tmp_path / "wt"
    wt.mkdir()
    log = tmp_path / "logs" / "venv.log"
    result = VenvBuilder(str(uv)).build(wt, ("--extra", "dev"), (("/sib",),), log)
    assert result.ok
    calls = [line.split("|") for line in record.read_text(encoding="utf-8").splitlines()]
    assert [call[0] for call in calls] == [
        f"venv {wt / '.venv'}",
        "sync --locked --extra dev",
        f"pip install --python {wt / '.venv/bin/python'} /sib",
    ]
    assert {call[1] for call in calls} == {str(wt)}
    assert {call[2] for call in calls} == {str(wt / ".venv")}
    assert {call[3] for call in calls} == {"unset"}
    assert "sync --locked --extra dev" in log.read_text(encoding="utf-8")


def test_the_builder_stops_at_the_first_failure(tmp_path: Path):
    uv, record = _fake_uv(tmp_path, fail_on="sync")
    wt = tmp_path / "wt"
    wt.mkdir()
    log = tmp_path / "venv.log"
    result = VenvBuilder(str(uv)).build(wt, (), (("/sib",),), log)
    assert not result.ok
    assert "uv refused sync" in result.text
    assert len(record.read_text(encoding="utf-8").splitlines()) == 2
    assert "uv refused sync" in log.read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not installed")
def test_real_uv_builds_the_worktree_venv_offline_and_leaves_a_shared_one_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # A virtual project with no dependencies: uv resolves, locks and syncs it
    # without a download, and UV_OFFLINE makes any attempt an error.
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setenv("UV_PYTHON_DOWNLOADS", "never")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "uv-cache"))
    wt = tmp_path / "wt"
    _write(wt, "pyproject.toml", '[project]\nname = "pickup"\nversion = "0.1.0"\n'
           'requires-python = ">=3.10"\ndependencies = []\n\n[tool.uv]\npackage = false\n')
    subprocess.run(["uv", "lock"], cwd=wt, check=True, capture_output=True)
    shared = tmp_path / "shared-venv"
    subprocess.run(["uv", "venv", str(shared)], check=True, capture_output=True)
    before = _venv_hashes(shared)
    monkeypatch.setenv("VIRTUAL_ENV", str(shared))
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(shared))
    result = VenvBuilder().build(wt, (), (), tmp_path / "venv.log")
    assert result.ok, (tmp_path / "venv.log").read_text(encoding="utf-8")
    assert (wt / ".venv" / "pyvenv.cfg").is_file()
    assert not (wt / ".venv").is_symlink()
    assert _venv_hashes(shared) == before


# --------------------------------------------------------------------------
# sow --apply --verify on a uv target, with the builder faked at its seam

SHARED_TOOL = "#!/bin/sh\necho 'lint-tool 1.0.0'\necho 'E999 a finding the base does not have' >&2\nexit 1\n"
LOCKED_TOOL = "#!/bin/sh\necho 'lint-tool 1.0.1'\nexit 0\n"


class FakeVenvBuilder:
    """Emulates a locked sync: writes the lock's lint-tool into the worktree's own `.venv`.

    Records what the worktree held at `.venv` when it was asked to build, so a
    sync that would have gone through a link to the shared venv shows.
    """

    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[dict] = []

    def build(self, worktree, sync_args, carried, log_path) -> CommandResult:
        held = worktree / ".venv"
        self.calls.append(
            {
                "worktree": worktree,
                "sync_args": sync_args,
                "carried": carried,
                "held_before": held.exists() or held.is_symlink(),
            }
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("fake uv sync\n", encoding="utf-8")
        if not self.ok:
            return CommandResult(False, "", "fake uv sync failed")
        # Written as uv would write, into whatever `.venv` names: through a link,
        # that is the shared venv, and its editable .pth then names this worktree.
        tool = held / "bin" / "lint-tool"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_text(LOCKED_TOOL, encoding="utf-8")
        tool.chmod(0o755)
        (held / "pyvenv.cfg").write_text("home = /fake\n", encoding="utf-8")
        site = held / "lib" / "python3.12" / "site-packages"
        site.mkdir(parents=True, exist_ok=True)
        (site / "_pickup.pth").write_text(f"{worktree}/src\n", encoding="utf-8")
        return CommandResult(True, "", "")


def _shared_venv(root: Path) -> Path:
    """The target's shared venv: an older lint-tool, a pyvenv.cfg and two .pth files."""
    venv = root / ".venv"
    tool = venv / "bin" / "lint-tool"
    tool.parent.mkdir(parents=True)
    tool.write_text(SHARED_TOOL, encoding="utf-8")
    tool.chmod(0o755)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.12\n", encoding="utf-8")
    site = venv / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (site / "_pickup.pth").write_text(f"{root}/src\n", encoding="utf-8")
    (site / "distutils-precedence.pth").write_text("import os\n", encoding="utf-8")
    return venv


def _venv_hashes(venv: Path) -> dict[str, str]:
    paths = [venv / "pyvenv.cfg", *sorted(venv.rglob("*.pth"))]
    assert paths[1:], "a venv fixture with no .pth files would prove nothing"
    return {str(p.relative_to(venv)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def _commit_uv_target(root: Path, ci: str | None = None) -> None:
    _uv_target(root, *(() if ci is None else (ci,)))
    _write(root, "Makefile", "verify:\n\t.venv/bin/lint-tool\n")
    _git(root, "add", "uv.lock", ".github/workflows/ci.yml", "Makefile")
    _git(root, "commit", "-qm", "uv target")
    _git(root, "push", "-q", "origin", "main")


def _verify_on_uv_target(canon_root, pickup_root, tmp_path, builder, **kwargs):
    return _apply(
        canon_root,
        pickup_root,
        tmp_path,
        verify=True,
        verify_runner=MakeCommand(),
        venv_builder=builder,
        **kwargs,
    )


def test_verify_runs_the_lockfile_version_not_the_shared_venvs(
    canon: Path, pickup: Path, tmp_path: Path
):
    _shared_venv(pickup)
    _commit_uv_target(pickup)
    builder = FakeVenvBuilder()
    report, gh, _ruff, reports = _verify_on_uv_target(canon, pickup, tmp_path, builder)
    outcome = report.outcomes[0]
    assert outcome.action == DEPLOYED, outcome.detail
    log = next(reports.glob("*-verify.log")).read_text(encoding="utf-8")
    assert "lint-tool 1.0.1" in log
    assert "lint-tool 1.0.0" not in log
    assert len(gh.created) == 1
    assert "worktree venv built from uv.lock (--extra dev)" in outcome.detail


def test_the_extras_come_from_the_branchs_own_ci(canon: Path, pickup: Path, tmp_path: Path):
    _shared_venv(pickup)
    gs = "jobs:\n  t:\n    steps:\n      - run: uv sync --locked --extra full --extra dev\n"
    _commit_uv_target(pickup, gs)
    builder = FakeVenvBuilder()
    _verify_on_uv_target(canon, pickup, tmp_path, builder)
    assert [call["sync_args"] for call in builder.calls] == [("--extra", "full", "--extra", "dev")]


def test_the_build_never_goes_through_a_link_to_the_shared_venv(
    canon: Path, pickup: Path, tmp_path: Path
):
    _shared_venv(pickup)
    _commit_uv_target(pickup)
    builder = FakeVenvBuilder()
    _verify_on_uv_target(canon, pickup, tmp_path, builder)
    (call,) = builder.calls
    assert call["held_before"] is False
    assert call["worktree"] != pickup
    assert pickup not in call["worktree"].parents


def test_the_shared_venvs_cfg_and_pth_files_are_unchanged(
    canon: Path, pickup: Path, tmp_path: Path
):
    shared = _shared_venv(pickup)
    _commit_uv_target(pickup)
    before = _venv_hashes(shared)
    report, *_ = _verify_on_uv_target(canon, pickup, tmp_path, FakeVenvBuilder())
    assert report.outcomes[0].action == DEPLOYED, report.outcomes[0].detail
    assert _venv_hashes(shared) == before
    assert shared.is_dir() and not shared.is_symlink()


def test_teardown_leaves_no_worktree_venv_behind(canon: Path, pickup: Path, tmp_path: Path):
    _shared_venv(pickup)
    _commit_uv_target(pickup)
    builder = FakeVenvBuilder()
    _verify_on_uv_target(canon, pickup, tmp_path, builder)
    worktree = builder.calls[0]["worktree"]
    assert not (worktree / ".venv").exists()
    assert not worktree.parent.exists()
    listed = _git(pickup, "worktree", "list", "--porcelain")
    assert str(worktree) not in listed


def test_a_failed_build_aborts_before_any_commit_or_push(
    canon: Path, pickup: Path, tmp_path: Path
):
    _shared_venv(pickup)
    _commit_uv_target(pickup)
    report, gh, _ruff, reports = _verify_on_uv_target(
        canon, pickup, tmp_path, FakeVenvBuilder(ok=False)
    )
    outcome = report.outcomes[0]
    assert outcome.action == ABORTED
    assert "worktree venv build failed" in outcome.detail
    assert str(reports / "2026-08-28-pickup-venv.log") in outcome.detail
    assert gh.created == []
    assert "oversteward/sync" not in _git(pickup, "branch", "--list", "--all")
    assert not list(reports.glob("*-verify.log"))


def test_a_shared_venv_local_install_the_lock_lacks_is_handed_to_the_build(
    canon: Path, pickup: Path, tmp_path: Path
):
    shared = _shared_venv(pickup)
    sibling = tmp_path / "sibling"
    _dist(shared, "sibling", {"url": sibling.as_uri(), "dir_info": {}})
    _commit_uv_target(pickup)
    builder = FakeVenvBuilder()
    _verify_on_uv_target(canon, pickup, tmp_path, builder)
    assert builder.calls[0]["carried"] == ((str(sibling),),)


def test_without_verify_a_uv_target_borrows_the_shared_venv_and_builds_nothing(
    canon: Path, pickup: Path, tmp_path: Path
):
    _shared_venv(pickup)
    _commit_uv_target(pickup)
    hook = pickup / ".git" / "hooks" / "pre-commit"
    seen = tmp_path / "link-seen"
    hook.write_text(f'#!/bin/sh\nreadlink .venv > "{seen}"\n', encoding="utf-8")
    hook.chmod(0o755)
    builder = FakeVenvBuilder()
    report, *_ = _apply(canon, pickup, tmp_path, venv_builder=builder)
    assert report.outcomes[0].action == DEPLOYED, report.outcomes[0].detail
    assert builder.calls == []
    assert Path(seen.read_text(encoding="utf-8").strip()) == pickup / ".venv"


def test_a_target_whose_ci_does_not_sync_keeps_the_shared_venv_under_verify(
    canon: Path, pickup: Path, tmp_path: Path
):
    _shared_venv(pickup)
    pip_ci = 'jobs:\n  t:\n    steps:\n      - run: uv pip install --system -e ".[dev]"\n'
    _commit_uv_target(pickup, pip_ci)
    builder = FakeVenvBuilder()
    report, *_ = _verify_on_uv_target(canon, pickup, tmp_path, builder)
    assert builder.calls == []
    assert report.outcomes[0].action == ABORTED
    assert "make verify failed" in report.outcomes[0].detail


def test_a_worktree_already_holding_a_venv_is_refused_not_synced_into(
    canon: Path, pickup: Path, tmp_path: Path
):
    _shared_venv(pickup)
    _commit_uv_target(pickup)
    _write(pickup, ".venv/tracked.txt", "committed by the target\n")
    _git(pickup, "add", "-f", ".venv/tracked.txt")
    _git(pickup, "commit", "-qm", "tracked venv file")
    _git(pickup, "push", "-q", "origin", "main")
    builder = FakeVenvBuilder()
    report, gh, *_ = _verify_on_uv_target(canon, pickup, tmp_path, builder)
    outcome = report.outcomes[0]
    assert outcome.action == ABORTED
    assert "already holds a .venv" in outcome.detail
    assert "Traceback" not in outcome.detail
    assert builder.calls == []
    assert gh.created == []


# --------------------------------------------------------------------------
# every failure is one context's abort, never an escape from the run

MULTI_LINE_QUOTE = """
jobs:
  t:
    steps:
      - run: uv sync --locked --extra dev
      - run: |
          python -c "
          print('a quoted argument across lines')
          "
          uv sync --extra docs # '
"""


def test_a_quoted_argument_spanning_lines_is_read_not_refused():
    assert ci_sync_args(MULTI_LINE_QUOTE) == ("--extra", "dev", "--extra", "docs")


def test_a_sync_inside_a_multi_line_quote_is_not_a_sync():
    text = 'jobs:\n  t:\n    steps:\n      - run: |\n          echo "\n          uv sync --extra nope\n          "\n'
    assert ci_sync_args(text) is None


def test_an_unclosed_quote_is_still_refused():
    with pytest.raises(SowError, match="cannot read"):
        ci_sync_args("jobs:\n  t:\n    steps:\n      - run: |\n          echo \"open\n")


@pytest.mark.parametrize(
    "text",
    [
        "jobs:\n  t: reusable\n",
        "jobs:\n  - a\n",
        "jobs:\n  t:\n    steps: run-me\n",
        "jobs:\n  t:\n    steps:\n      - run-me\n",
        "- not a workflow\n",
    ],
)
def test_a_workflow_of_the_wrong_shape_is_refused(text: str):
    with pytest.raises(SowError, match="ci.yml"):
        ci_sync_args(text)


def test_a_workflow_with_no_jobs_reads_as_no_sync():
    assert ci_sync_args("name: ci\non: push\n") is None


def test_an_undecodable_workflow_or_lock_is_refused(tmp_path: Path):
    bad_ci = tmp_path / "bad-ci"
    _uv_target(bad_ci)
    (bad_ci / ".github/workflows/ci.yml").write_bytes(b"jobs: \xff\xfe\n")
    bad_lock = tmp_path / "bad-lock"
    _uv_target(bad_lock)
    (bad_lock / "uv.lock").write_bytes(b"version = \xff\n")
    for root in (bad_ci, bad_lock):
        with pytest.raises(SowError, match="could not be read"):
            locked_venv_plan(root, tmp_path / "shared")


def test_a_uv_that_cannot_be_started_is_a_failed_build_not_a_crash(tmp_path: Path):
    wt = tmp_path / "wt"
    wt.mkdir()
    log = tmp_path / "venv.log"
    result = VenvBuilder(str(tmp_path / "no-such-uv")).build(wt, (), (), log)
    assert not result.ok
    assert "no-such-uv" in result.text
    assert "no-such-uv" in log.read_text(encoding="utf-8")


def test_an_unstartable_uv_aborts_one_context_and_the_run_still_reports(
    canon: Path, pickup: Path, tmp_path: Path
):
    _shared_venv(pickup)
    _commit_uv_target(pickup)
    report, gh, _ruff, reports = _verify_on_uv_target(
        canon, pickup, tmp_path, VenvBuilder(str(tmp_path / "no-such-uv"))
    )
    outcome = report.outcomes[0]
    assert outcome.action == ABORTED
    assert "worktree venv build failed" in outcome.detail
    assert gh.created == []
    assert (reports / "2026-08-28.jsonl").is_file()


def test_a_malformed_workflow_aborts_one_context_and_the_run_still_reports(
    canon: Path, pickup: Path, tmp_path: Path
):
    _shared_venv(pickup)
    _commit_uv_target(pickup, "jobs:\n  t: reusable\n")
    builder = FakeVenvBuilder()
    report, gh, _ruff, reports = _verify_on_uv_target(canon, pickup, tmp_path, builder)
    outcome = report.outcomes[0]
    assert outcome.action == ABORTED
    assert "ci.yml" in outcome.detail
    assert builder.calls == []
    assert (reports / "2026-08-28.jsonl").is_file()

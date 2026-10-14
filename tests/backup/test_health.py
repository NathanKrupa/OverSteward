# ABOUTME: Tests for the backup health sweep — snapshot age, verified restore, export age, E: free space.
# ABOUTME: A fake restic/systemctl runner, an injected clock and free-space reader drive every fixture.

"""Each RED row has a fixture on both sides of its edge, and each exit code its own case.

Nothing here touches ``/mnt/e``, ``/mnt/c`` or the real key: every path is under
``tmp_path`` and every dependency is a parameter. The real-restic tests run the
installed binary against a repository initialised inside ``tmp_path``; off a box
with restic they skip and say so.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from oversteward.backup import health
from oversteward.backup.health import (
    EXIT_COULD_NOT_READ,
    EXIT_MEASURED,
    EXIT_NOT_CONFIGURED,
    BackupHealthConfig,
    check_health,
    render,
)
from oversteward.backup.home import HomeBackupConfig, RunResult, run_backup

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2030, 1, 20, 12, 0, 0, tzinfo=timezone.utc)
LATEST_ID = "d0bfed749b71339d8602f0b865fba0c4a617e66fd7e193894b84eda3b7d148fa"
OTHER_ID = "112625f1d6e6e77d3af8a95e50c88570e74ac01b9f1db18e1e24a29ffa50571b"
DISTRO = "Ubuntu-24.04"
KEY_TEXT = "correct horse battery staple"
ARCHIVE_BYTES = 1000


def _stamp(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def _marker_text(at: datetime, snapshot_id: str = LATEST_ID) -> str:
    return f"{_stamp(at)} {snapshot_id}\n"


def _archive_name(day) -> str:
    return f"{DISTRO}_{day.isoformat()}.tar"


def _setup(tmp_path: Path) -> BackupHealthConfig:
    """A healthy estate: fresh snapshot, matching marker and mirror, a 10-day-old export."""
    export_dir = tmp_path / "E" / "WSLBackups"
    repo = export_dir / "restic"
    repo.mkdir(parents=True)
    (repo / "config").write_bytes(b"restic repo config")
    key = tmp_path / "C" / "WslResilience" / "restic.key"
    key.parent.mkdir(parents=True)
    key.write_text(KEY_TEXT)
    restic = tmp_path / "bin" / "restic"
    restic.parent.mkdir()
    restic.write_text("#!/bin/sh\n")
    restic.chmod(0o755)
    state = tmp_path / "state"
    state.mkdir()
    marker = _marker_text(NOW - timedelta(hours=7))
    (state / "restic.last-ok").write_text(marker)
    (key.parent / "restic.last-ok").write_text(marker)
    export_day = (NOW - timedelta(days=10)).date()
    (export_dir / _archive_name(export_day)).write_bytes(b"x" * ARCHIVE_BYTES)
    (key.parent / "export.last-ok").write_text(f"{export_day.isoformat()}\r\n")
    return BackupHealthConfig(
        repo=repo,
        key=key,
        restic=restic,
        state_dir=state,
        export_dir=export_dir,
        distro=DISTRO,
    )


def _snapshots_json(age: timedelta | None, snapshot_id: str = LATEST_ID) -> str:
    if age is None:
        return "[]\n"
    when = (NOW - age).astimezone(timezone(timedelta(hours=-4)))
    return json.dumps(
        [{"time": when.isoformat(), "id": snapshot_id, "short_id": snapshot_id[:8]}]
    ) + "\n"


class FakeRunner:
    """Answers ``restic snapshots`` and ``systemctl --user show``; records every call."""

    def __init__(
        self,
        *,
        snapshot_age: timedelta | None = timedelta(hours=7),
        snapshot_id: str = LATEST_ID,
        snapshots: RunResult | None = None,
        service_state: str = "inactive",
        systemctl: RunResult | None = None,
    ):
        self.calls: list[list[str]] = []
        self.snapshots = snapshots or RunResult(0, _snapshots_json(snapshot_age, snapshot_id), "")
        self.systemctl = systemctl or RunResult(0, f"ActiveState={service_state}\n", "")

    def __call__(self, argv: Sequence[str]) -> RunResult:
        argv = list(argv)
        self.calls.append(argv)
        if argv[0] == "systemctl":
            return self.systemctl
        if argv[1] == "snapshots":
            return self.snapshots
        raise AssertionError(f"unexpected command {argv}")


def _free(multiple: float):
    return lambda _path: int(ARCHIVE_BYTES * multiple)


def _check(config: BackupHealthConfig, runner: FakeRunner | None = None, *, free=2.0):
    return check_health(
        config, run=runner or FakeRunner(), now=lambda: NOW, free_bytes=_free(free)
    )


def _row(report, name: str):
    (row,) = [row for row in report.rows if row.name == name]
    return row


def _red_names(report) -> list[str]:
    return [row.name for row in report.rows if row.status == "RED"]


class TestHealthy:
    def test_a_healthy_estate_measures_four_rows_none_red(self, tmp_path):
        report = _check(_setup(tmp_path))
        assert report.exit_code == EXIT_MEASURED, render(report)
        assert [row.name for row in report.rows] == [
            "snapshot", "verified restore", "export", "E: free",
        ]
        assert _red_names(report) == []
        assert render(report).splitlines()[0] == "4 backup checks measured — 0 RED"

    def test_snapshots_are_read_lock_free_with_the_repo_and_key(self, tmp_path):
        config = _setup(tmp_path)
        runner = FakeRunner()
        _check(config, runner)
        (call,) = [c for c in runner.calls if c[0] == str(config.restic)]
        assert call[1:5] == ["snapshots", "--json", "--latest", "1"]
        assert "--no-lock" in call
        assert call[call.index("--repo") + 1] == str(config.repo)
        assert call[call.index("--password-file") + 1] == str(config.key)

    def test_the_key_is_never_printed(self, tmp_path):
        report = _check(_setup(tmp_path), FakeRunner(snapshot_age=timedelta(hours=49)))
        assert KEY_TEXT not in render(report)


class TestSnapshot:
    def test_47_hours_old_is_green(self, tmp_path):
        report = _check(_setup(tmp_path), FakeRunner(snapshot_age=timedelta(hours=47)))
        assert _row(report, "snapshot").status == "OK"

    def test_49_hours_old_is_red(self, tmp_path):
        report = _check(_setup(tmp_path), FakeRunner(snapshot_age=timedelta(hours=49)))
        assert _row(report, "snapshot").status == "RED"
        assert render(report).splitlines()[0] == "4 backup checks measured — 1 RED"

    @pytest.mark.parametrize("state", ["active", "activating"])
    def test_49_hours_old_with_the_backup_running_is_running_not_red(self, tmp_path, state):
        runner = FakeRunner(snapshot_age=timedelta(hours=49), service_state=state)
        report = _check(_setup(tmp_path), runner)
        assert _row(report, "snapshot").status == "RUNNING"
        assert "snapshot" not in _red_names(report)
        assert ["systemctl", "--user", "show", "home-backup.service"] == runner.calls[-1][:4]

    def test_a_repository_with_no_snapshot_is_red(self, tmp_path):
        report = _check(_setup(tmp_path), FakeRunner(snapshot_age=None))
        assert _row(report, "snapshot").status == "RED"

    def test_a_snapshot_dated_in_the_future_is_red(self, tmp_path):
        report = _check(_setup(tmp_path), FakeRunner(snapshot_age=-timedelta(hours=2)))
        assert _row(report, "snapshot").status == "RED"


class TestVerifiedRestore:
    def _marker(self, config: BackupHealthConfig, text: str | None, *, mirror: bool = True):
        for path in [config.state_dir / "restic.last-ok", config.key.parent / "restic.last-ok"]:
            if path.parent == config.key.parent and not mirror:
                continue
            if text is None:
                path.unlink()
            else:
                path.write_text(text)

    def test_a_marker_47_hours_old_is_green(self, tmp_path):
        config = _setup(tmp_path)
        self._marker(config, _marker_text(NOW - timedelta(hours=47)))
        assert _row(_check(config), "verified restore").status == "OK"

    def test_a_marker_49_hours_old_is_red(self, tmp_path):
        config = _setup(tmp_path)
        self._marker(config, _marker_text(NOW - timedelta(hours=49)))
        assert _row(_check(config), "verified restore").status == "RED"

    def test_no_marker_is_red(self, tmp_path):
        config = _setup(tmp_path)
        self._marker(config, None)
        assert _row(_check(config), "verified restore").status == "RED"

    def test_a_marker_in_the_future_is_red(self, tmp_path):
        config = _setup(tmp_path)
        self._marker(config, _marker_text(NOW + timedelta(hours=1)))
        row = _row(_check(config), "verified restore")
        assert row.status == "RED"
        assert "future" in row.detail

    def test_a_marker_naming_another_snapshot_than_the_repos_latest_is_red(self, tmp_path):
        config = _setup(tmp_path)
        self._marker(config, _marker_text(NOW - timedelta(hours=7), OTHER_ID))
        row = _row(_check(config), "verified restore")
        assert row.status == "RED"
        assert OTHER_ID[:8] in row.detail and LATEST_ID[:8] in row.detail

    def test_an_absent_c_mirror_is_red_logon_canary_blind(self, tmp_path):
        config = _setup(tmp_path)
        (config.key.parent / "restic.last-ok").unlink()
        row = _row(_check(config), "verified restore")
        assert row.status == "RED"
        assert "absent - logon canary blind" in row.detail

    def test_a_c_mirror_that_differs_is_red_logon_canary_blind(self, tmp_path):
        config = _setup(tmp_path)
        (config.key.parent / "restic.last-ok").write_text(
            _marker_text(NOW - timedelta(hours=31))
        )
        row = _row(_check(config), "verified restore")
        assert row.status == "RED"
        assert "differs - logon canary blind" in row.detail

    def test_the_mirror_dir_can_be_named_apart_from_the_key(self, tmp_path):
        config = _setup(tmp_path)
        elsewhere = tmp_path / "mirror"
        elsewhere.mkdir()
        shutil.move(config.key.parent / "restic.last-ok", elsewhere / "restic.last-ok")
        moved = BackupHealthConfig(
            repo=config.repo, key=config.key, restic=config.restic,
            state_dir=config.state_dir, mirror_dir=elsewhere,
            export_dir=config.export_dir, distro=DISTRO,
        )
        assert _row(_check(moved), "verified restore").status == "OK"


class TestExport:
    def _only_archive(self, config: BackupHealthConfig, age_days: int, size: int = ARCHIVE_BYTES):
        for old in config.export_dir.glob("*.tar"):
            old.unlink()
        day = (NOW - timedelta(days=age_days)).date()
        (config.export_dir / _archive_name(day)).write_bytes(b"x" * size)
        (config.key.parent / "export.last-ok").write_text(day.isoformat())

    def test_44_days_old_is_green(self, tmp_path):
        config = _setup(tmp_path)
        self._only_archive(config, 44)
        assert _row(_check(config), "export").status == "OK"

    def test_46_days_old_is_red(self, tmp_path):
        config = _setup(tmp_path)
        self._only_archive(config, 46)
        assert _row(_check(config), "export").status == "RED"

    def test_a_zero_byte_archive_is_red(self, tmp_path):
        config = _setup(tmp_path)
        self._only_archive(config, 3, size=0)
        assert _row(_check(config), "export").status == "RED"

    def test_no_archive_is_red(self, tmp_path):
        config = _setup(tmp_path)
        for old in config.export_dir.glob("*.tar"):
            old.unlink()
        assert _row(_check(config), "export").status == "RED"

    def test_the_newest_archive_is_chosen_by_its_filename_date(self, tmp_path):
        config = _setup(tmp_path)
        self._only_archive(config, 3)
        stale = config.export_dir / _archive_name((NOW - timedelta(days=60)).date())
        stale.write_bytes(b"")  # touched last, so it has the newest mtime
        row = _row(_check(config), "export")
        assert row.status == "OK", row.detail

    def test_another_distros_archive_is_not_this_ones_export(self, tmp_path):
        config = _setup(tmp_path)
        self._only_archive(config, 60)
        fresh = (NOW - timedelta(days=1)).date().isoformat()
        (config.export_dir / f"Debian_{fresh}.tar").write_bytes(b"x")
        assert _row(_check(config), "export").status == "RED"

    def test_an_absent_export_marker_is_a_note_not_red(self, tmp_path):
        config = _setup(tmp_path)
        (config.key.parent / "export.last-ok").unlink()
        row = _row(_check(config), "export")
        assert row.status == "OK"
        assert any("export.last-ok" in note for note in row.notes)

    def test_an_export_marker_naming_another_date_is_a_note_not_red(self, tmp_path):
        config = _setup(tmp_path)
        (config.key.parent / "export.last-ok").write_text("2029-12-01\r\n")
        row = _row(_check(config), "export")
        assert row.status == "OK"
        assert any("2029-12-01" in note for note in row.notes)

    def test_a_matching_export_marker_adds_no_note(self, tmp_path):
        assert _row(_check(_setup(tmp_path)), "export").notes == ()


class TestFreeSpace:
    def test_1_0x_the_newest_archive_is_red(self, tmp_path):
        assert _row(_check(_setup(tmp_path), free=1.0), "E: free").status == "RED"

    def test_1_2x_the_newest_archive_is_green(self, tmp_path):
        assert _row(_check(_setup(tmp_path), free=1.2), "E: free").status == "OK"

    def test_free_space_is_read_on_the_export_drive(self, tmp_path):
        config = _setup(tmp_path)
        seen: list[Path] = []
        check_health(
            config, run=FakeRunner(), now=lambda: NOW,
            free_bytes=lambda path: seen.append(path) or ARCHIVE_BYTES * 2,
        )
        assert seen == [config.export_dir]


class TestNotConfigured:
    def test_restic_missing_is_exit_2(self, tmp_path):
        config = _setup(tmp_path)
        config.restic.unlink()
        report = _check(config)
        assert report.exit_code == EXIT_NOT_CONFIGURED
        assert str(config.restic) in render(report)

    def test_the_key_missing_is_exit_2(self, tmp_path):
        config = _setup(tmp_path)
        config.key.unlink()
        assert _check(config).exit_code == EXIT_NOT_CONFIGURED

    def test_the_repo_dir_missing_with_its_parent_present_is_exit_2(self, tmp_path):
        config = _setup(tmp_path)
        shutil.rmtree(config.repo)
        assert _check(config).exit_code == EXIT_NOT_CONFIGURED


class TestCouldNotRead:
    def test_export_dir_missing_is_exit_1(self, tmp_path):
        # The repository lives elsewhere here, so only the export dir's absence is in play.
        config = _setup(tmp_path)
        repo = tmp_path / "R" / "restic"
        shutil.move(config.repo, repo)
        shutil.rmtree(config.export_dir)
        apart = BackupHealthConfig(
            repo=repo, key=config.key, restic=config.restic, state_dir=config.state_dir,
            export_dir=config.export_dir, distro=DISTRO,
        )
        report = _check(apart)
        assert report.exit_code == EXIT_COULD_NOT_READ
        assert report.rows == ()
        assert f"{config.export_dir} missing - export drive not mounted?" in render(report)

    def test_the_repos_parent_missing_is_exit_1_not_2(self, tmp_path):
        config = _setup(tmp_path)
        unmounted = BackupHealthConfig(
            repo=tmp_path / "F" / "WSLBackups" / "restic", key=config.key,
            restic=config.restic, state_dir=config.state_dir,
            export_dir=config.export_dir, distro=DISTRO,
        )
        assert _check(unmounted).exit_code == EXIT_COULD_NOT_READ

    def test_restic_exiting_1_is_exit_1(self, tmp_path):
        runner = FakeRunner(snapshots=RunResult(1, "", "Fatal: wrong password"))
        report = _check(_setup(tmp_path), runner)
        assert report.exit_code == EXIT_COULD_NOT_READ
        assert "wrong password" in render(report)
        assert not render(report).startswith("4 backup checks measured")

    def test_unparseable_snapshot_json_is_exit_1(self, tmp_path):
        runner = FakeRunner(snapshots=RunResult(0, "not json\n", ""))
        assert _check(_setup(tmp_path), runner).exit_code == EXIT_COULD_NOT_READ

    def test_systemctl_failing_on_a_stale_snapshot_is_exit_1(self, tmp_path):
        runner = FakeRunner(
            snapshot_age=timedelta(hours=49), systemctl=RunResult(1, "", "Failed to connect to bus")
        )
        report = _check(_setup(tmp_path), runner)
        assert report.exit_code == EXIT_COULD_NOT_READ
        assert "systemctl exited 1: Failed to connect to bus" in render(report)

    def test_systemctl_not_reporting_the_units_state_is_exit_1(self, tmp_path):
        runner = FakeRunner(snapshot_age=timedelta(hours=49), systemctl=RunResult(0, "", ""))
        report = _check(_setup(tmp_path), runner)
        assert report.exit_code == EXIT_COULD_NOT_READ
        assert "did not report ActiveState" in render(report)


# --- the entrypoint ----------------------------------------------------------


def _entrypoint():
    spec = importlib.util.spec_from_file_location(
        "backup_health", REPO_ROOT / "scripts" / "backup_health.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(config: BackupHealthConfig) -> list[str]:
    return [
        "--repo", str(config.repo),
        "--key", str(config.key),
        "--restic", str(config.restic),
        "--state-dir", str(config.state_dir),
        "--export-dir", str(config.export_dir),
    ]


class TestEntrypoint:
    def test_a_runner_that_raises_exits_1_with_the_reason(self, tmp_path, capsys):
        def _explode(_argv):
            raise RuntimeError("bus vanished")

        code = _entrypoint().main(_args(_setup(tmp_path)), run=_explode)
        assert code == EXIT_COULD_NOT_READ
        out = capsys.readouterr().out
        assert out.startswith("COULD NOT READ - backup health sweep crashed")
        assert "bus vanished" in out

    def test_a_measured_sweep_exits_0_and_prints_four_rows(self, tmp_path, capsys):
        config = _setup(tmp_path)
        code = _entrypoint().main(_args(config), run=FakeRunner())
        out = capsys.readouterr().out.splitlines()
        # The real clock reads this fixture as years old, so its rows may be RED;
        # a RED row is still a measured answer.
        assert code == EXIT_MEASURED
        assert out[0].startswith("4 backup checks measured")
        assert len(out) >= 5

    def test_not_configured_exits_2(self, tmp_path, capsys):
        config = _setup(tmp_path)
        config.restic.unlink()
        assert _entrypoint().main(_args(config), run=FakeRunner()) == EXIT_NOT_CONFIGURED
        assert capsys.readouterr().out.startswith("NOT CONFIGURED")


# --- real restic -------------------------------------------------------------


def _real_restic() -> str | None:
    found = shutil.which("restic")
    if found:
        return found
    local = Path.home() / ".local" / "bin" / "restic"
    return str(local) if local.is_file() else None


REAL_RESTIC = _real_restic()
needs_restic = pytest.mark.skipif(
    REAL_RESTIC is None,
    reason="restic not installed (ops/wsl/install-restic.sh installs it); real-restic run skipped",
)


@needs_restic
class TestRealRestic:
    def test_a_real_repository_backed_up_then_swept_is_all_green(self, tmp_path):
        config = _setup(tmp_path)
        shutil.rmtree(config.repo)
        for marker in [config.state_dir / "restic.last-ok", config.key.parent / "restic.last-ok"]:
            marker.unlink()
        source = tmp_path / "home"
        obj = source / "proj" / ".git" / "objects" / "ab" / ("c" * 38)
        obj.parent.mkdir(parents=True)
        obj.write_bytes(b"blob content")
        os.utime(obj, (1_000_000_000, 1_000_000_000))
        subprocess.run(
            [REAL_RESTIC, "init", "--repo", str(config.repo),
             "--password-file", str(config.key), "--quiet"],
            check=True, capture_output=True,
        )
        backed_up = run_backup(
            HomeBackupConfig(
                source=source, repository=config.repo, password_file=config.key,
                state_dir=config.state_dir, restic=Path(REAL_RESTIC),
            )
        )
        assert backed_up.exit_code == 0, backed_up.headline
        today = datetime.now().astimezone().date()
        for old in config.export_dir.glob("*.tar"):
            old.unlink()
        (config.export_dir / _archive_name(today)).write_bytes(b"x")
        (config.key.parent / "export.last-ok").write_text(today.isoformat())
        real = BackupHealthConfig(
            repo=config.repo, key=config.key, restic=Path(REAL_RESTIC),
            state_dir=config.state_dir, export_dir=config.export_dir, distro=DISTRO,
        )
        report = check_health(real, run=FakeRunnerPassthrough())
        text = render(report)
        assert report.exit_code == EXIT_MEASURED, text
        assert text.splitlines()[0] == "4 backup checks measured — 0 RED", text
        assert KEY_TEXT not in text


class FakeRunnerPassthrough:
    """Runs restic for real; answers systemctl as inactive so the box's own unit never leaks in."""

    def __call__(self, argv: Sequence[str]) -> RunResult:
        if argv[0] == "systemctl":
            return RunResult(0, "ActiveState=inactive\n", "")
        return health.run_command(argv)


# --- the session-start doctrine ----------------------------------------------


def test_claude_md_runs_backup_health_as_the_sixth_session_start_sweep() -> None:
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Session start — the six sweeps" in text
    section = text.split("## Session start", 1)[1].split("\n## ", 1)[0]
    block = section.split("```bash", 1)[1].split("```", 1)[0]
    lines = [line for line in block.splitlines() if "backup_health.py" in line]
    assert lines == [
        ".venv/bin/python scripts/backup_health.py            # whether the laptop could be rebuilt"
    ]

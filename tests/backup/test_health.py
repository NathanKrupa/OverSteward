# ABOUTME: Tests for the backup health sweep — snapshot, verified restore, export, E: free, AG/GS restores.
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
import re
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
AG_MARKER = "aigranthelper.last-ok"
GS_MARKER = "grantspider.last-ok"
DUMP_KEY = "db-backups/research/20300101T030000Z_scheduled.dump"


def _stamp(at: datetime) -> str:
    return at.isoformat(timespec="seconds")


def _marker_text(at: datetime, snapshot_id: str = LATEST_ID) -> str:
    return f"{_stamp(at)} {snapshot_id}\n"


def _utc(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat(timespec="seconds")


def _restore_text(restored: datetime, created: datetime | None = None, key: str = DUMP_KEY) -> str:
    """A restore marker in the contract's form: restored-at, dump-created-at, dump key."""
    created = created if created is not None else restored - timedelta(hours=5)
    return f"{_utc(restored)} {_utc(created)} {key}\n"


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
    restores = tmp_path / "estate-restore"
    restores.mkdir()
    for name in (AG_MARKER, GS_MARKER):
        (restores / name).write_text(_restore_text(NOW - timedelta(days=3)))
    return BackupHealthConfig(
        repo=repo,
        key=key,
        restic=restic,
        state_dir=state,
        export_dir=export_dir,
        distro=DISTRO,
        restore_marker_dir=restores,
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
    found = [row for row in report.rows if row.name == name]
    assert len(found) == 1, f"expected one row named {name!r}, found {len(found)}:\n{render(report)}"
    return found[0]


def _red_names(report) -> list[str]:
    return [row.name for row in report.rows if row.status == "RED"]


class TestHealthy:
    def test_a_healthy_estate_measures_six_rows_none_red(self, tmp_path):
        report = _check(_setup(tmp_path))
        assert report.exit_code == EXIT_MEASURED, render(report)
        assert [row.name for row in report.rows] == [
            "snapshot", "verified restore", "export", "E: free", "AG restore", "GS restore",
        ]
        assert _red_names(report) == []
        assert render(report).splitlines()[0] == "6 backup checks measured — 0 RED"

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

    def test_exactly_48_hours_old_is_still_green(self, tmp_path):
        report = _check(_setup(tmp_path), FakeRunner(snapshot_age=timedelta(hours=48)))
        assert _row(report, "snapshot").status == "OK"

    def test_49_hours_old_is_red(self, tmp_path):
        report = _check(_setup(tmp_path), FakeRunner(snapshot_age=timedelta(hours=49)))
        assert _row(report, "snapshot").status == "RED"
        assert render(report).splitlines()[0] == "6 backup checks measured — 1 RED"

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

    def test_a_mirror_differing_only_in_line_endings_is_red(self, tmp_path):
        # The mirror is a byte copy; Windows tooling rewriting it as CRLF is a difference.
        config = _setup(tmp_path)
        primary = (config.state_dir / "restic.last-ok").read_text()
        (config.key.parent / "restic.last-ok").write_bytes(primary.replace("\n", "\r\n").encode())
        row = _row(_check(config), "verified restore")
        assert row.status == "RED"
        assert "differs - logon canary blind" in row.detail

    def test_an_unparseable_marker_is_red_even_when_mirrored(self, tmp_path):
        config = _setup(tmp_path)
        self._marker(config, "garbage\n")
        row = _row(_check(config), "verified restore")
        assert row.status == "RED"
        assert "marker unreadable" in row.detail

    def test_a_marker_against_a_repository_with_no_snapshot_is_red(self, tmp_path):
        row = _row(_check(_setup(tmp_path), FakeRunner(snapshot_age=None)), "verified restore")
        assert row.status == "RED"
        assert "repository latest is none" in row.detail

    def test_an_unreadable_snapshot_list_makes_the_row_could_not_read_not_red(self, tmp_path):
        runner = FakeRunner(snapshots=RunResult(1, "", "Fatal: wrong password"))
        row = _row(_check(_setup(tmp_path), runner), "verified restore")
        assert row.status == "COULD NOT READ"

    def test_the_mirror_dir_can_be_named_apart_from_the_key(self, tmp_path):
        config = _setup(tmp_path)
        elsewhere = tmp_path / "mirror"
        elsewhere.mkdir()
        shutil.move(config.key.parent / "restic.last-ok", elsewhere / "restic.last-ok")
        moved = BackupHealthConfig(
            repo=config.repo, key=config.key, restic=config.restic,
            state_dir=config.state_dir, mirror_dir=elsewhere,
            export_dir=config.export_dir, distro=DISTRO,
            restore_marker_dir=config.restore_marker_dir,
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

    def test_exactly_45_days_old_is_still_green(self, tmp_path):
        config = _setup(tmp_path)
        self._only_archive(config, 45)
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

    def test_no_archive_to_size_against_is_red(self, tmp_path):
        config = _setup(tmp_path)
        for old in config.export_dir.glob("*.tar"):
            old.unlink()
        assert _row(_check(config), "E: free").status == "RED"

    def test_a_zero_byte_newest_archive_leaves_nothing_to_size_against_so_red(self, tmp_path):
        # A zero-byte archive is a failed export, and a full drive is one way to fail.
        config = _setup(tmp_path)
        (config.export_dir / _archive_name((NOW - timedelta(days=1)).date())).write_bytes(b"")
        report = check_health(config, run=FakeRunner(), now=lambda: NOW, free_bytes=lambda _p: 0)
        row = _row(report, "E: free")
        assert row.status == "RED"
        assert "zero bytes" in row.detail

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
            restore_marker_dir=config.restore_marker_dir,
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
            restore_marker_dir=config.restore_marker_dir,
        )
        assert _check(unmounted).exit_code == EXIT_COULD_NOT_READ

    def test_restic_exiting_1_is_exit_1(self, tmp_path):
        runner = FakeRunner(snapshots=RunResult(1, "", "Fatal: wrong password"))
        report = _check(_setup(tmp_path), runner)
        assert report.exit_code == EXIT_COULD_NOT_READ
        assert "wrong password" in render(report)
        assert not render(report).startswith("6 backup checks measured")

    def test_a_check_that_cannot_read_never_stops_the_others(self, tmp_path):
        runner = FakeRunner(snapshots=RunResult(1, "", "Fatal: wrong password"))
        report = _check(_setup(tmp_path), runner)
        assert [(row.name, row.status) for row in report.rows] == [
            ("snapshot", "COULD NOT READ"),
            ("verified restore", "COULD NOT READ"),
            ("export", "OK"),
            ("E: free", "OK"),
            ("AG restore", "OK"),
            ("GS restore", "OK"),
        ]
        assert render(report).splitlines()[0] == (
            "COULD NOT READ - 2 of 6 backup checks unreadable; 4 measured — 0 RED"
        )

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


RESTORE_ROWS = [
    ("AG restore", AG_MARKER, "python manage.py restore_drill"),
    ("GS restore", GS_MARKER, "grantspider backup drill"),
]


@pytest.mark.parametrize(("row_name", "marker", "command"), RESTORE_ROWS)
class TestRestoreRows:
    def _write(self, config: BackupHealthConfig, marker: str, content: str | bytes) -> None:
        path = config.restore_marker_dir / marker
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)

    def test_34_days_old_is_green(self, tmp_path, row_name, marker, command):
        config = _setup(tmp_path)
        self._write(config, marker, _restore_text(NOW - timedelta(days=34)))
        assert _row(_check(config), row_name).status == "OK"

    def test_exactly_35_days_old_is_still_green(self, tmp_path, row_name, marker, command):
        config = _setup(tmp_path)
        self._write(config, marker, _restore_text(NOW - timedelta(days=35)))
        assert _row(_check(config), row_name).status == "OK"

    def test_a_second_past_35_days_is_red_and_names_the_drill(
        self, tmp_path, row_name, marker, command
    ):
        config = _setup(tmp_path)
        self._write(config, marker, _restore_text(NOW - timedelta(days=35, seconds=1)))
        row = _row(_check(config), row_name)
        assert row.status == "RED"
        assert "limit 35 days" in row.detail
        assert command in row.detail

    def test_a_marker_dated_in_the_future_is_red(self, tmp_path, row_name, marker, command):
        config = _setup(tmp_path)
        self._write(config, marker, _restore_text(NOW + timedelta(minutes=5)))
        row = _row(_check(config), row_name)
        assert row.status == "RED"
        assert "in the future" in row.detail
        assert command in row.detail

    def test_no_marker_is_red_and_names_the_command_that_clears_it(
        self, tmp_path, row_name, marker, command
    ):
        config = _setup(tmp_path)
        (config.restore_marker_dir / marker).unlink()
        report = _check(config)
        row = _row(report, row_name)
        assert row.status == "RED"
        assert "no restore drill has passed" in row.detail
        assert str(config.restore_marker_dir / marker) in row.detail
        assert command in row.detail
        assert row.notes == ()
        assert command in render(report)

    def test_a_dump_created_after_the_restore_is_red(self, tmp_path, row_name, marker, command):
        config = _setup(tmp_path)
        restored = NOW - timedelta(days=1)
        self._write(config, marker, _restore_text(restored, restored + timedelta(seconds=1)))
        row = _row(_check(config), row_name)
        assert row.status == "RED"
        assert "after the restore" in row.detail

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param("garbage\n", id="garbage"),
            pytest.param("", id="empty"),
            pytest.param(f"{_utc(NOW - timedelta(days=1))} {DUMP_KEY}\n", id="missing-field"),
            pytest.param(
                _restore_text(NOW - timedelta(days=1), key="db backups/x.dump"),
                id="key-with-a-space",
            ),
            pytest.param(
                "2030-01-19T12:00:00 2030-01-19T07:00:00 " + DUMP_KEY + "\n",
                id="no-utc-offset",
            ),
            pytest.param("2030-01-19 2030-01-18 " + DUMP_KEY + "\n", id="date-only"),
            pytest.param(
                _restore_text(NOW - timedelta(days=1)).replace(" ", "  ", 1), id="double-space"
            ),
            pytest.param(_restore_text(NOW - timedelta(days=1)) * 2, id="two-lines"),
            pytest.param(_restore_text(NOW - timedelta(days=1)) + "extra\n", id="second-line"),
            pytest.param(
                _restore_text(NOW - timedelta(days=1), key="db-backups/x.dump\rjunk"),
                id="carriage-return-in-key",
            ),
            pytest.param(
                _restore_text(NOW - timedelta(days=1), key="db-backups/x\t.dump"), id="tab-in-key"
            ),
            pytest.param(_restore_text(NOW - timedelta(days=1), key=""), id="empty-key"),
            pytest.param(b"\xff\xfe" + _restore_text(NOW).encode(), id="not-utf8"),
        ],
    )
    def test_an_unparseable_marker_is_red(self, tmp_path, row_name, marker, command, content):
        config = _setup(tmp_path)
        self._write(config, marker, content)
        row = _row(_check(config), row_name)
        assert row.status == "RED"
        assert "unparseable" in row.detail
        assert command in row.detail

    def test_a_crlf_ending_is_accepted(self, tmp_path, row_name, marker, command):
        config = _setup(tmp_path)
        self._write(config, marker, _restore_text(NOW - timedelta(days=1)).replace("\n", "\r\n"))
        assert _row(_check(config), row_name).status == "OK"

    def test_each_row_reads_its_own_repos_marker(self, tmp_path, row_name, marker, command):
        config = _setup(tmp_path)
        self._write(config, marker, _restore_text(NOW - timedelta(days=40)))
        report = _check(config)
        assert [name for name in _red_names(report)] == [row_name]

    def test_red_restore_rows_are_a_measured_answer(self, tmp_path, row_name, marker, command):
        config = _setup(tmp_path)
        (config.restore_marker_dir / marker).unlink()
        report = _check(config)
        assert report.exit_code == EXIT_MEASURED
        assert render(report).splitlines()[0] == "6 backup checks measured — 1 RED"

    def test_a_marker_that_cannot_be_read_is_could_not_read(
        self, tmp_path, row_name, marker, command
    ):
        config = _setup(tmp_path)
        path = config.restore_marker_dir / marker
        path.unlink()
        path.mkdir()
        report = _check(config)
        assert _row(report, row_name).status == "COULD NOT READ"
        assert report.exit_code == EXIT_COULD_NOT_READ


class TestRestoreMarkerContract:
    """The README is the contract the drills are written from; it must agree with the reader."""

    README = REPO_ROOT / "ops" / "wsl" / "README.md"

    def test_the_readme_names_each_marker_path_the_sweep_reads(self):
        text = self.README.read_text(encoding="utf-8")
        default = BackupHealthConfig().restore_marker_dir
        assert default == Path.home() / ".local" / "state" / "estate-restore"
        for marker in (AG_MARKER, GS_MARKER):
            assert f"`~/.local/state/estate-restore/{marker}`" in text

    def test_the_readme_example_file_reads_ok(self, tmp_path):
        text = self.README.read_text(encoding="utf-8")
        found = re.search(r"Example file, `[^`]*grantspider\.last-ok`:\n\n```text\n(.*?)```", text, re.S)
        assert found, "the README's example marker file was not found"
        example = found[1]
        config = _setup(tmp_path)
        (config.restore_marker_dir / GS_MARKER).write_text(example)
        restored = datetime.fromisoformat(example.split(" ")[0])
        report = check_health(
            config, run=FakeRunner(), now=lambda: restored + timedelta(days=1),
            free_bytes=_free(2.0),
        )
        assert _row(report, "GS restore").status == "OK", render(report)


@pytest.mark.parametrize("doc", ["CLAUDE.md", "ops/wsl/README.md"])
def test_each_document_pins_the_sweeps_own_row_count(doc):
    text = (REPO_ROOT / doc).read_text(encoding="utf-8")
    assert f"{len(health.CHECKS)} backup checks measured" in text


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
        "--restore-marker-dir", str(config.restore_marker_dir),
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

    def test_a_measured_sweep_exits_0_and_prints_six_rows(self, tmp_path, capsys):
        config = _setup(tmp_path)
        code = _entrypoint().main(_args(config), run=FakeRunner())
        out = capsys.readouterr().out.splitlines()
        # The real clock reads this fixture as years old, so its rows may be RED;
        # a RED row is still a measured answer.
        assert code == EXIT_MEASURED
        assert out[0].startswith("6 backup checks measured")
        assert len(out) >= 7

    def test_mirror_dir_is_passed_through_to_the_sweep(self, tmp_path, capsys):
        config = _setup(tmp_path)
        elsewhere = tmp_path / "mirror"
        elsewhere.mkdir()
        shutil.move(config.key.parent / "restic.last-ok", elsewhere / "restic.last-ok")
        _entrypoint().main(_args(config), run=FakeRunner())
        assert "absent - logon canary blind" in capsys.readouterr().out
        _entrypoint().main([*_args(config), "--mirror-dir", str(elsewhere)], run=FakeRunner())
        assert "logon canary blind" not in capsys.readouterr().out

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
        for name in (AG_MARKER, GS_MARKER):
            (config.restore_marker_dir / name).write_text(
                _restore_text(datetime.now(timezone.utc) - timedelta(days=1))
            )
        real = BackupHealthConfig(
            repo=config.repo, key=config.key, restic=Path(REAL_RESTIC),
            state_dir=config.state_dir, export_dir=config.export_dir, distro=DISTRO,
            restore_marker_dir=config.restore_marker_dir,
        )
        report = check_health(real, run=FakeRunnerPassthrough())
        text = render(report)
        assert report.exit_code == EXIT_MEASURED, text
        assert text.splitlines()[0] == "6 backup checks measured — 0 RED", text
        assert KEY_TEXT not in text


class FakeRunnerPassthrough:
    """Runs restic for real; answers systemctl as inactive so the box's own unit never leaks in."""

    def __call__(self, argv: Sequence[str]) -> RunResult:
        if argv[0] == "systemctl":
            return RunResult(0, "ActiveState=inactive\n", "")
        return health.run_command(argv)


# --- the session-start doctrine ----------------------------------------------


def test_claude_md_runs_backup_health_as_a_session_start_sweep() -> None:
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Session start — the eight sweeps" in text
    section = text.split("## Session start", 1)[1].split("\n## ", 1)[0]
    block = section.split("```bash", 1)[1].split("```", 1)[0]
    lines = [line for line in block.splitlines() if "backup_health.py" in line]
    assert lines == [
        ".venv/bin/python scripts/backup_health.py            # whether the laptop could be rebuilt"
    ]

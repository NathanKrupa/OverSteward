# ABOUTME: Tests for the daily restic backup of /home — preflight, retention, self-verifying restore.
# ABOUTME: A fake restic drives the unit tests; one real-restic run uses a throwaway repo in tmp_path.

"""``restic.last-ok`` may only appear after a snapshot was taken, pruned and proved.

The unit tests inject a fake restic runner, so nothing touches ``/mnt/e`` or the
real key. The real-restic tests run the installed binary against a repository
initialised inside ``tmp_path``; off a box with restic they skip and say so.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import pytest

from oversteward.backup import home
from oversteward.backup.home import (
    EXIT_FAILED,
    EXIT_NOT_CONFIGURED,
    EXIT_OK,
    HomeBackupConfig,
    RunResult,
    exclude_patterns,
    run_backup,
    verify_candidates,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "ops" / "wsl"
LOOSE_OBJECT = "proj/.git/objects/ab/" + "c" * 38
KEY_TEXT = "correct horse battery staple"
SNAPSHOT_ID = "0c56af2b1bbf5460a8f9e9c784fe93d430db5583d096eeba45b790bacf46ca3e"
FIXED_NOW = datetime(2030, 1, 2, 4, 0, 0)


def _setup(tmp_path: Path) -> HomeBackupConfig:
    """A source with one git object, an initialised-looking repo and a key outside the source."""
    source = tmp_path / "home"
    obj = source / LOOSE_OBJECT
    obj.parent.mkdir(parents=True)
    obj.write_bytes(b"blob content")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "config").write_bytes(b"restic repo config")
    key = tmp_path / "keys" / "restic.key"
    key.parent.mkdir()
    key.write_text(KEY_TEXT)
    restic = tmp_path / "bin" / "restic"
    restic.parent.mkdir()
    restic.write_text("#!/bin/sh\n")
    restic.chmod(0o755)
    return HomeBackupConfig(
        source=source,
        repository=repo,
        password_file=key,
        state_dir=tmp_path / "state",
        restic=restic,
    )


def _summary(**extra) -> str:
    fields = {
        "message_type": "summary",
        "files_new": 3,
        "files_changed": 1,
        "data_added": 2 * 1024 * 1024,
        "total_bytes_processed": 10 * 1024 * 1024,
        "total_duration": 2.0,
        "snapshot_id": SNAPSHOT_ID,
    }
    fields.update(extra)
    return json.dumps(fields) + "\n"


class FakeRestic:
    """Answers restic subcommands; ``restore`` copies the requested source file into --target."""

    def __init__(
        self, *, backup=None, forget=None, restore_bytes=None, restore_nothing=False, restore=None
    ):
        self.calls: list[list[str]] = []
        self.restore = restore
        self.backup = backup or RunResult(0, _summary(), "")
        self.forget = forget or RunResult(0, "", "")
        self.restore_bytes = restore_bytes
        self.restore_nothing = restore_nothing

    def __call__(self, argv: Sequence[str]) -> RunResult:
        argv = list(argv)
        self.calls.append(argv)
        command = argv[1]
        if command == "backup":
            return self.backup
        if command == "forget":
            return self.forget
        if command == "restore":
            return self.restore or self._restore(argv)
        raise AssertionError(f"unexpected restic command {argv}")

    def _restore(self, argv: list[str]) -> RunResult:
        target = Path(argv[argv.index("--target") + 1])
        include = Path(argv[argv.index("--include") + 1])
        if not self.restore_nothing:
            dest = target / include.relative_to("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.restore_bytes or include.read_bytes())
        return RunResult(0, '{"message_type":"summary"}\n', "")

    def commands(self) -> list[str]:
        return [call[1] for call in self.calls]


def _run(config: HomeBackupConfig, fake: FakeRestic):
    return run_backup(config, run=fake, choose=lambda items: items[0], now=lambda: FIXED_NOW)


def _last_ok(config: HomeBackupConfig) -> Path:
    return config.state_dir / "restic.last-ok"


# --- preflight: nothing configured is exit 2, never 0 ----------------------


def _missing_key(config: HomeBackupConfig) -> None:
    config.password_file.unlink()


def _empty_key(config: HomeBackupConfig) -> None:
    config.password_file.write_text("")


def _uninitialised_repo(config: HomeBackupConfig) -> None:
    (config.repository / "config").unlink()


def _missing_restic(config: HomeBackupConfig) -> None:
    config.restic.unlink()


def _missing_source(config: HomeBackupConfig) -> None:
    shutil.rmtree(config.source)


class TestPreflight:
    @pytest.mark.parametrize(
        ("breakage", "reason"),
        [
            (_missing_key, "password file"),
            (_empty_key, "password file"),
            (_uninitialised_repo, "not an initialised restic repository"),
            (_missing_restic, "restic"),
            (_missing_source, "source"),
        ],
    )
    def test_each_missing_piece_is_not_configured_and_runs_nothing(
        self, tmp_path, breakage, reason
    ):
        config = _setup(tmp_path)
        breakage(config)
        fake = FakeRestic()
        outcome = _run(config, fake)
        assert outcome.exit_code == EXIT_NOT_CONFIGURED
        assert outcome.headline.startswith("NOT CONFIGURED")
        assert any(reason in line for line in outcome.details)
        assert fake.calls == []
        assert not _last_ok(config).exists()

    def test_a_key_inside_the_backed_up_tree_is_refused(self, tmp_path):
        config = _setup(tmp_path)
        inside = config.source / ".restic.key"
        inside.write_text(KEY_TEXT)
        config = HomeBackupConfig(
            source=config.source,
            repository=config.repository,
            password_file=inside,
            state_dir=config.state_dir,
            restic=config.restic,
        )
        fake = FakeRestic()
        outcome = _run(config, fake)
        assert outcome.exit_code == EXIT_NOT_CONFIGURED
        assert any("inside the backed-up source" in line for line in outcome.details)
        assert fake.calls == []

    def test_the_key_is_never_printed(self, tmp_path):
        config = _setup(tmp_path)
        _uninitialised_repo(config)
        outcome = _run(config, FakeRestic())
        assert KEY_TEXT not in home.render(outcome)


# --- the full run -----------------------------------------------------------


class TestSuccessfulRun:
    def test_backup_forget_restore_in_order_then_last_ok(self, tmp_path):
        config = _setup(tmp_path)
        fake = FakeRestic()
        outcome = _run(config, fake)
        assert outcome.exit_code == EXIT_OK, home.render(outcome)
        assert fake.commands() == ["backup", "forget", "restore"]
        assert _last_ok(config).read_text() == f"2030-01-02T04:00:00 {SNAPSHOT_ID}\n"
        assert outcome.headline.startswith("OK")
        assert SNAPSHOT_ID[:8] in outcome.headline

    def test_backup_names_repo_key_source_and_excludes(self, tmp_path):
        config = _setup(tmp_path)
        fake = FakeRestic()
        _run(config, fake)
        backup = fake.calls[0]
        assert backup[0] == str(config.restic)
        assert backup[backup.index("--repo") + 1] == str(config.repository)
        assert backup[backup.index("--password-file") + 1] == str(config.password_file)
        assert str(config.source) in backup
        excludes = [backup[i + 1] for i, arg in enumerate(backup) if arg == "--exclude"]
        assert excludes == exclude_patterns(config.source)

    def test_retention_is_14_daily_8_weekly_6_monthly_with_prune(self, tmp_path):
        config = _setup(tmp_path)
        fake = FakeRestic()
        _run(config, fake)
        forget = fake.calls[1]
        assert forget[forget.index("--repo") + 1] == str(config.repository)
        tail = forget[forget.index("forget") + 1 :]
        for flag, value in [("--keep-daily", "14"), ("--keep-weekly", "8"), ("--keep-monthly", "6")]:
            assert tail[tail.index(flag) + 1] == value
        assert "--prune" in tail

    def test_restore_reads_the_new_snapshot_not_latest(self, tmp_path):
        config = _setup(tmp_path)
        fake = FakeRestic()
        _run(config, fake)
        restore = fake.calls[2]
        assert restore[restore.index("restore") + 1] == SNAPSHOT_ID
        assert restore[restore.index("--include") + 1] == str(config.source / LOOSE_OBJECT)

    def test_the_state_dir_is_created(self, tmp_path):
        config = _setup(tmp_path)
        assert not config.state_dir.exists()
        _run(config, FakeRestic())
        assert _last_ok(config).is_file()


class TestFailedRun:
    def test_restic_backup_failure_stops_before_forget(self, tmp_path):
        config = _setup(tmp_path)
        fake = FakeRestic(backup=RunResult(1, "", "Fatal: unable to open repository"))
        outcome = _run(config, fake)
        assert outcome.exit_code == EXIT_FAILED
        assert fake.commands() == ["backup"]
        assert "unable to open repository" in home.render(outcome)
        assert not _last_ok(config).exists()

    def test_unreadable_source_files_fail_and_name_each_one(self, tmp_path):
        config = _setup(tmp_path)
        stderr = (
            '{"message_type":"error","error":{"message":"open /home/x: permission denied"},'
            '"during":"archival","item":"/home/x"}\n'
            '{"message_type":"exit_error","code":3,"message":"Warning: at least one source'
            ' file could not be read"}\n'
        )
        fake = FakeRestic(backup=RunResult(3, _summary(), stderr))
        outcome = _run(config, fake)
        assert outcome.exit_code == EXIT_FAILED
        assert fake.commands() == ["backup"]
        assert "/home/x" in home.render(outcome)
        assert not _last_ok(config).exists()

    def test_a_backup_with_no_summary_is_a_failure(self, tmp_path):
        config = _setup(tmp_path)
        fake = FakeRestic(backup=RunResult(0, "", ""))
        outcome = _run(config, fake)
        assert outcome.exit_code == EXIT_FAILED
        assert fake.commands() == ["backup"]
        assert not _last_ok(config).exists()

    def test_forget_failure_writes_no_last_ok(self, tmp_path):
        config = _setup(tmp_path)
        fake = FakeRestic(forget=RunResult(1, "", "Fatal: repository is already locked"))
        outcome = _run(config, fake)
        assert outcome.exit_code == EXIT_FAILED
        assert fake.commands() == ["backup", "forget"]
        assert "already locked" in home.render(outcome)
        assert not _last_ok(config).exists()

    def test_a_restore_that_produced_nothing_fails(self, tmp_path):
        # restic restore exits 0 when --include matches nothing in the snapshot.
        config = _setup(tmp_path)
        outcome = _run(config, FakeRestic(restore_nothing=True))
        assert outcome.exit_code == EXIT_FAILED
        assert "verify" in outcome.headline
        assert not _last_ok(config).exists()

    def test_a_failing_restore_reports_restics_reason(self, tmp_path):
        config = _setup(tmp_path)
        fake = FakeRestic(restore=RunResult(1, "", "Fatal: pack 3f2a is damaged"))
        outcome = _run(config, fake)
        assert outcome.exit_code == EXIT_FAILED
        assert "pack 3f2a is damaged" in outcome.headline
        assert not _last_ok(config).exists()

    def test_a_restore_with_different_bytes_fails(self, tmp_path):
        config = _setup(tmp_path)
        outcome = _run(config, FakeRestic(restore_bytes=b"bit rot"))
        assert outcome.exit_code == EXIT_FAILED
        assert "sha256" in home.render(outcome)
        assert not _last_ok(config).exists()

    def test_a_source_deleted_before_the_compare_fails_cleanly(self, tmp_path):
        config = _setup(tmp_path)

        def _choose_then_gc(items):
            items[0].unlink()
            return items[0]

        outcome = run_backup(
            config, run=FakeRestic(restore_bytes=b"blob content"), choose=_choose_then_gc,
            now=lambda: FIXED_NOW,
        )
        assert outcome.exit_code == EXIT_FAILED
        assert "vanished" in outcome.headline
        assert not _last_ok(config).exists()

    def test_no_file_to_verify_against_fails(self, tmp_path):
        config = _setup(tmp_path)
        shutil.rmtree(config.source / "proj")
        (config.source / "notes.txt").write_text("not content-addressed")
        fake = FakeRestic()
        outcome = _run(config, fake)
        assert outcome.exit_code == EXIT_FAILED
        assert fake.commands() == ["backup", "forget"]
        assert not _last_ok(config).exists()


# --- excludes and verify candidates ----------------------------------------


class TestExcludes:
    def test_home_level_paths_are_anchored_and_build_dirs_match_anywhere(self):
        source = Path("/home/natha")
        assert exclude_patterns(source) == [
            "/home/natha/.claude/tmp",
            "/home/natha/.cache",
            "/home/natha/.ollama",
            "/home/natha/.npm",
            "/home/natha/.vscode-server",
            "/home/natha/grantspider/data/irs_cache",
            ".venv",
            "node_modules",
        ]


class TestVerifyCandidates:
    def _obj(self, source: Path, rel: str, mtime: float) -> Path:
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        os.utime(path, (mtime, mtime))
        return path

    def test_loose_objects_and_packs_older_than_the_start_qualify(self, tmp_path):
        loose = self._obj(tmp_path, "a/.git/objects/ab/" + "d" * 38, 100)
        pack = self._obj(tmp_path, "b/.git/objects/pack/pack-1.pack", 100)
        assert verify_candidates(tmp_path, started=200) == sorted([loose, pack])

    def test_a_file_written_after_the_backup_started_is_not_a_candidate(self, tmp_path):
        self._obj(tmp_path, "a/.git/objects/ab/" + "d" * 38, 300)
        assert verify_candidates(tmp_path, started=200) == []

    def test_a_file_under_an_excluded_path_is_not_a_candidate(self, tmp_path):
        self._obj(tmp_path, ".cache/.git/objects/ab/" + "d" * 38, 100)
        self._obj(tmp_path, "node_modules/.git/objects/pack/p.pack", 100)
        assert verify_candidates(tmp_path, started=200) == []

    def test_a_symlink_is_not_a_candidate(self, tmp_path):
        real = self._obj(tmp_path, "real.bin", 100)
        link = tmp_path / "a/.git/objects/ab" / ("e" * 38)
        link.parent.mkdir(parents=True)
        link.symlink_to(real)
        os.utime(link, (100, 100), follow_symlinks=False)
        assert verify_candidates(tmp_path, started=200) == []


# --- the entry point --------------------------------------------------------


def _entrypoint():
    spec = importlib.util.spec_from_file_location(
        "backup_home", REPO_ROOT / "scripts" / "backup_home.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEntrypoint:
    def test_not_configured_exits_2_and_prints_why(self, tmp_path, capsys):
        missing = tmp_path / "absent.key"
        code = _entrypoint().main(
            [
                "--source", str(tmp_path),
                "--repo", str(tmp_path / "repo"),
                "--password-file", str(missing),
                "--state-dir", str(tmp_path / "state"),
                "--restic", str(tmp_path / "restic"),
            ]
        )
        assert code == EXIT_NOT_CONFIGURED
        out = capsys.readouterr().out
        assert out.startswith("NOT CONFIGURED")
        assert str(missing) in out

    def test_a_crash_is_a_failure_never_ok(self, monkeypatch, capsys):
        def _explode(*_args, **_kwargs):
            raise RuntimeError("disk vanished")

        monkeypatch.setattr(home, "run_backup", _explode)
        assert _entrypoint().main([]) == EXIT_FAILED
        assert capsys.readouterr().out.startswith("FAILED - home backup crashed")


# --- systemd units and the installer ---------------------------------------


def _directives(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return dict(
        line.split("=", 1) for line in lines if "=" in line and not line.startswith("#")
    )


class TestUnits:
    def test_timer_runs_daily_at_four_and_catches_up(self):
        timer = _directives(OPS / "home-backup.timer")
        assert timer["OnCalendar"] == "*-*-* 04:00:00"
        assert timer["Persistent"] == "true"

    def test_service_is_a_oneshot_running_the_primary_checkout_entrypoint(self):
        service = _directives(OPS / "home-backup.service")
        assert service["Type"] == "oneshot"
        assert service["ExecStart"] == (
            "/home/natha/OverSteward/.venv/bin/python "
            "/home/natha/OverSteward/scripts/backup_home.py"
        )

    @pytest.mark.parametrize("name", ["home-backup.service", "home-backup.timer"])
    def test_units_open_with_aboutme(self, name):
        first = (OPS / name).read_text(encoding="utf-8").splitlines()[:2]
        assert all(line.startswith("# ABOUTME: ") for line in first)


class TestInstaller:
    SCRIPT = OPS / "install-restic.sh"

    def _run(self, tmp_path: Path, url: str) -> subprocess.CompletedProcess:
        env = dict(os.environ, RESTIC_INSTALL_DIR=str(tmp_path / "bin"), RESTIC_DOWNLOAD_URL=url)
        return subprocess.run(
            ["bash", str(self.SCRIPT)], env=env, capture_output=True, text=True, check=False
        )

    def test_a_checksum_mismatch_installs_nothing(self, tmp_path):
        bogus = tmp_path / "restic.bz2"
        bogus.write_bytes(b"not restic")
        result = self._run(tmp_path, bogus.as_uri())
        assert result.returncode == 1
        assert "sha256 mismatch" in result.stderr
        assert not (tmp_path / "bin" / "restic").exists()

    def test_the_pinned_version_already_installed_downloads_nothing(self, tmp_path):
        script = self.SCRIPT.read_text(encoding="utf-8")
        version = script.split('RESTIC_VERSION="', 1)[1].split('"', 1)[0]
        fake = tmp_path / "bin" / "restic"
        fake.parent.mkdir()
        fake.write_text(f"#!/bin/sh\necho 'restic {version} compiled with go'\n")
        fake.chmod(0o755)
        result = self._run(tmp_path, (tmp_path / "does-not-exist.bz2").as_uri())
        assert result.returncode == 0, result.stderr
        assert "already installed" in result.stdout

    @pytest.mark.parametrize("installed", ["0.16.0", "{pin}0"])
    def test_any_other_installed_version_is_replaced(self, tmp_path, installed):
        script = self.SCRIPT.read_text(encoding="utf-8")
        pin = script.split('RESTIC_VERSION="', 1)[1].split('"', 1)[0]
        fake = tmp_path / "bin" / "restic"
        fake.parent.mkdir()
        fake.write_text(f"#!/bin/sh\necho 'restic {installed.format(pin=pin)} compiled with go'\n")
        fake.chmod(0o755)
        result = self._run(tmp_path, (tmp_path / "does-not-exist.bz2").as_uri())
        # The download is attempted (and fails here), so the old binary is never kept as current.
        assert result.returncode == 1
        assert "could not download" in result.stderr
        assert "already installed" not in result.stdout

    def test_the_pin_is_a_version_and_a_full_sha256(self):
        script = self.SCRIPT.read_text(encoding="utf-8")
        sha = script.split('RESTIC_SHA256="', 1)[1].split('"', 1)[0]
        assert len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)


# --- real restic against a throwaway repository ----------------------------


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


def _real_setup(tmp_path: Path) -> HomeBackupConfig:
    config = _setup(tmp_path)
    shutil.rmtree(config.repository)
    for rel in [".cache/c.txt", "a/node_modules/n.js", "a/.venv/v.py", "a/keep.txt"]:
        path = config.source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel)
    os.utime(config.source / LOOSE_OBJECT, (1_000_000_000, 1_000_000_000))
    subprocess.run(
        [REAL_RESTIC, "init", "--repo", str(config.repository),
         "--password-file", str(config.password_file), "--quiet"],
        check=True, capture_output=True,
    )
    return HomeBackupConfig(
        source=config.source,
        repository=config.repository,
        password_file=config.password_file,
        state_dir=config.state_dir,
        restic=Path(REAL_RESTIC),
    )


def _snapshot_files(config: HomeBackupConfig) -> list[str]:
    out = subprocess.run(
        [str(config.restic), "ls", "latest", "--repo", str(config.repository),
         "--password-file", str(config.password_file)],
        check=True, capture_output=True, text=True,
    ).stdout
    return [line for line in out.splitlines() if line.startswith(str(config.source))]


@needs_restic
class TestRealRestic:
    def test_a_real_run_snapshots_prunes_verifies_and_marks(self, tmp_path):
        config = _real_setup(tmp_path)
        outcome = run_backup(config)
        text = home.render(outcome)
        assert outcome.exit_code == EXIT_OK, text
        assert KEY_TEXT not in text
        marker = _last_ok(config).read_text().split()
        assert len(marker) == 2 and len(marker[1]) == 64
        files = _snapshot_files(config)
        assert str(config.source / "a/keep.txt") in files
        assert str(config.source / LOOSE_OBJECT) in files
        for excluded in [".cache", "node_modules", ".venv"]:
            assert not any(f"/{excluded}" in f for f in files), excluded
        expected = hashlib.sha256(b"blob content").hexdigest()
        assert expected[:12] in text

    def test_a_real_unreadable_file_fails_without_a_marker(self, tmp_path):
        if os.geteuid() == 0:
            pytest.skip("root reads mode-000 files; the unreadable case cannot be staged")
        config = _real_setup(tmp_path)
        locked = config.source / "locked.txt"
        locked.write_text("x")
        locked.chmod(0)
        try:
            outcome = run_backup(config)
        finally:
            locked.chmod(0o600)
        assert outcome.exit_code == EXIT_FAILED
        assert str(locked) in home.render(outcome)
        assert not _last_ok(config).exists()


class TestExportSeesTheBackup:
    def test_a_running_home_backup_makes_the_export_gate_busy(self, tmp_path):
        # The service's comment promises the monthly export never kills a backup in flight.
        from oversteward.backup.readiness import systemd_jobs

        shutil.copy(OPS / "home-backup.service", tmp_path / "home-backup.service")
        seen: list[list[str]] = []

        def _show(argv):
            seen.append(list(argv))
            units = argv[4:]
            return "\n\n".join(
                f"Id={unit}\nActiveState={'activating' if unit == 'home-backup.service' else 'inactive'}"
                f"\nSubState={'start' if unit == 'home-backup.service' else 'dead'}"
                for unit in units
            )

        blockers = systemd_jobs(run=_show, unit_dir=tmp_path)
        assert [b.detail for b in blockers] == ["home-backup.service activating/start"]

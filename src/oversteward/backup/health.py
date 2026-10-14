# ABOUTME: MIDDLE service for the backup health sweep — four checks over the restic history and the export.
# ABOUTME: Runner, clock and free-space reader are injected; "could not read" never prints as measured.

"""Measure whether the estate's two backups are current, from inside the distro.

Four rows, each OK or RED (the snapshot row may also read RUNNING):

1. **snapshot** — the restic repository's latest snapshot, read lock-free. RED
   when older than 48 hours, dated in the future, or absent; RUNNING instead of
   RED while ``home-backup.service`` is active or activating, because a backup
   in flight is the remedy, not the fault.
2. **verified restore** — ``restic.last-ok``, which the backup writes only after
   a restored file's sha256 matched its source. RED when absent, unparseable,
   older than 48 hours or in the future; when it names a snapshot other than
   the repository's latest; and when its C: mirror is absent or differs, which
   leaves the Windows logon check reading stale news ("logon canary blind").
3. **export** — the newest ``<distro>_YYYY-MM-DD.tar`` by the date in its name.
   RED when there is none, it is zero bytes, or it is older than 45 days.
   ``export.last-ok`` absent or naming another date is a NOTE: the export
   writes that marker, but an archive made before it did is still an archive.
4. **E: free** — free space on the export drive. RED below 1.1 times the
   newest archive, because the next export is written before the old one is
   pruned. With no archive to size against it is RED too: unmeasured is not ok.

Exit codes, the session-start contract:

* **0** — measured: all four rows were read, whatever they say.
* **1** — could not read: the export drive or the repository's parent is not
  mounted, restic or systemctl exited non-zero, or restic's JSON did not parse.
* **2** — not configured: restic, the key, or the repository (with its parent
  present) is missing, so there was nothing to look with.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from oversteward.backup.home import (
    DEFAULT_PASSWORD_FILE,
    DEFAULT_REPOSITORY,
    DEFAULT_RESTIC,
    DEFAULT_STATE_DIR,
    LAST_OK_NAME,
    Runner,
    run_command,
)

EXIT_MEASURED = 0
EXIT_COULD_NOT_READ = 1
EXIT_NOT_CONFIGURED = 2

DEFAULT_EXPORT_DIR = Path("/mnt/e/WSLBackups")
DEFAULT_DISTRO = "Ubuntu-24.04"
EXPORT_LAST_OK_NAME = "export.last-ok"
BACKUP_UNIT = "home-backup.service"

SNAPSHOT_MAX_AGE = timedelta(hours=48)
EXPORT_MAX_AGE = timedelta(days=45)
FREE_SPACE_FACTOR = 1.1

OK = "OK"
RED = "RED"
RUNNING = "RUNNING"
COULD_NOT_READ = "COULD NOT READ"

_RUNNING_STATES = frozenset({"active", "activating"})
_GIB = 1024**3


@dataclass(frozen=True, slots=True)
class BackupHealthConfig:
    """Where the two backups and their markers live, and the thresholds they are held to."""

    repo: Path = DEFAULT_REPOSITORY
    key: Path = DEFAULT_PASSWORD_FILE
    restic: Path = DEFAULT_RESTIC
    state_dir: Path = DEFAULT_STATE_DIR
    #: The Windows-side state dir: the marker's mirror and ``export.last-ok``.
    #: ``None`` means the key's directory.
    mirror_dir: Path | None = None
    export_dir: Path = DEFAULT_EXPORT_DIR
    distro: str = DEFAULT_DISTRO
    snapshot_max_age: timedelta = SNAPSHOT_MAX_AGE
    export_max_age: timedelta = EXPORT_MAX_AGE

    @property
    def mirror(self) -> Path:
        """The directory holding the C: mirror and the export marker."""
        return self.mirror_dir if self.mirror_dir is not None else self.key.parent


@dataclass(frozen=True, slots=True)
class Row:
    """One check's verdict, with the measurement behind it and any notes."""

    name: str
    status: str
    detail: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HealthReport:
    """The sweep's verdict: the rows read, or why nothing could be read."""

    rows: tuple[Row, ...] = ()
    problems: tuple[str, ...] = ()
    not_configured: bool = False

    @property
    def exit_code(self) -> int:
        if self.not_configured:
            return EXIT_NOT_CONFIGURED
        if self.problems or any(row.status == COULD_NOT_READ for row in self.rows):
            return EXIT_COULD_NOT_READ
        return EXIT_MEASURED


class CouldNotRead(Exception):
    """A check's source could not be read; the message is the reason."""


@dataclass(frozen=True, slots=True)
class _Snapshot:
    time: datetime
    id: str


@dataclass(frozen=True, slots=True)
class _Archive:
    path: Path
    day: date
    size: int


@dataclass(slots=True)
class _Sweep:
    config: BackupHealthConfig
    run: Runner
    now: datetime
    free_bytes: Callable[[Path], int]
    latest: _Snapshot | None = None
    latest_read: bool = False
    archive: _Archive | None = None


def local_now() -> datetime:
    """The current time, aware, in the box's own zone."""
    return datetime.now().astimezone()


def disk_free(path: Path) -> int:
    """Free bytes on the filesystem holding ``path``."""
    return shutil.disk_usage(path).free


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.astimezone()


def _age(now: datetime, then: datetime) -> str:
    hours = (now - then).total_seconds() / 3600
    return f"{hours / 24:.1f} days" if abs(hours) >= 48 else f"{hours:.1f} h"


def _tail(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


# --- preflight ---------------------------------------------------------------


def preflight(config: BackupHealthConfig) -> HealthReport | None:
    """A report when the sweep cannot start; ``None`` when it can."""
    unmounted = [
        f"{path} missing - export drive not mounted?"
        for path in dict.fromkeys([config.export_dir, config.repo.parent])
        if not path.is_dir()
    ]
    missing = []
    if not (config.restic.is_file() and os.access(config.restic, os.X_OK)):
        missing.append(f"restic binary not found at {config.restic} (ops/wsl/install-restic.sh)")
    if not config.key.is_file():
        missing.append(f"restic key missing: {config.key}")
    if config.repo.parent.is_dir() and not (config.repo / "config").is_file():
        missing.append(f"{config.repo} is not an initialised restic repository")
    if missing:
        return HealthReport(problems=tuple(missing + unmounted), not_configured=True)
    if unmounted:
        return HealthReport(problems=tuple(unmounted))
    return None


# --- 1. snapshot -------------------------------------------------------------


def _restic_argv(config: BackupHealthConfig) -> list[str]:
    return [
        str(config.restic), "snapshots", "--json", "--latest", "1", "--no-lock",
        "--repo", str(config.repo),
        "--password-file", str(config.key),
    ]


def _parse_snapshots(stdout: str) -> _Snapshot | None:
    try:
        snapshots = json.loads(stdout)
        if not isinstance(snapshots, list):
            raise TypeError(f"expected a list, got {type(snapshots).__name__}")
        if not snapshots:
            return None
        newest = max(
            (_Snapshot(_aware(datetime.fromisoformat(s["time"])), str(s["id"])) for s in snapshots),
            key=lambda snap: snap.time,
        )
    except (ValueError, TypeError, KeyError) as exc:
        raise CouldNotRead(f"restic snapshots JSON unreadable: {type(exc).__name__}: {exc}") from None
    return newest


def _latest_snapshot(sweep: _Sweep) -> _Snapshot | None:
    result = sweep.run(_restic_argv(sweep.config))
    if result.returncode != 0:
        raise CouldNotRead(f"restic snapshots exited {result.returncode}: {_tail(result.stderr)}")
    return _parse_snapshots(result.stdout)


def _backup_unit_state(sweep: _Sweep) -> str:
    result = sweep.run(["systemctl", "--user", "show", BACKUP_UNIT, "--property=ActiveState"])
    if result.returncode != 0:
        raise CouldNotRead(f"systemctl exited {result.returncode}: {_tail(result.stderr)}")
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "ActiveState":
            return value.strip()
    raise CouldNotRead(f"systemctl did not report ActiveState for {BACKUP_UNIT}")


def check_snapshot(sweep: _Sweep) -> Row:
    sweep.latest = _latest_snapshot(sweep)
    sweep.latest_read = True
    if sweep.latest is None:
        return Row("snapshot", RED, f"no snapshot in {sweep.config.repo}")
    snap = sweep.latest
    detail = f"latest {snap.id[:8]} at {snap.time.isoformat(timespec='seconds')}"
    if snap.time > sweep.now:
        return Row("snapshot", RED, f"{detail} is in the future")
    age = sweep.now - snap.time
    detail = f"{detail}, {_age(sweep.now, snap.time)} old"
    if age <= sweep.config.snapshot_max_age:
        return Row("snapshot", OK, detail)
    state = _backup_unit_state(sweep)
    if state in _RUNNING_STATES:
        return Row("snapshot", RUNNING, f"{detail}; {BACKUP_UNIT} is {state}")
    limit = sweep.config.snapshot_max_age.total_seconds() / 3600
    return Row("snapshot", RED, f"{detail} (limit {limit:.0f} h; {BACKUP_UNIT} {state})")


# --- 2. verified restore -----------------------------------------------------


def _read_marker(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CouldNotRead(f"{path}: {exc}") from None


def _marker_problems(sweep: _Sweep, text: str) -> list[str]:
    parts = text.split()
    try:
        stamp = _aware(datetime.fromisoformat(parts[0]))
        marker_id = parts[1]
    except (IndexError, ValueError):
        return [f"marker unreadable: {text.strip()!r}"]
    problems = []
    if stamp > sweep.now:
        problems.append(f"marker {stamp.isoformat(timespec='seconds')} is in the future")
    elif sweep.now - stamp > sweep.config.snapshot_max_age:
        problems.append(f"last verified restore {_age(sweep.now, stamp)} ago")
    latest_id = sweep.latest.id if sweep.latest else None
    if marker_id != latest_id:
        latest = latest_id[:8] if latest_id else "none"
        problems.append(f"marker names {marker_id[:8]}, repository latest is {latest}")
    return problems


def check_verified_restore(sweep: _Sweep) -> Row:
    if not sweep.latest_read:
        raise CouldNotRead("repository latest unread, so the marker cannot be matched to it")
    primary = sweep.config.state_dir / LAST_OK_NAME
    text = _read_marker(primary)
    if text is None:
        return Row("verified restore", RED, f"no verified restore on record ({primary} absent)")
    problems = _marker_problems(sweep, text)
    mirror = sweep.config.mirror / LAST_OK_NAME
    mirrored = _read_marker(mirror)
    if mirrored is None:
        problems.append(f"C: mirror {mirror} absent - logon canary blind")
    elif mirrored != text:
        problems.append(f"C: mirror {mirror} differs - logon canary blind")
    if problems:
        return Row("verified restore", RED, "; ".join(problems))
    return Row("verified restore", OK, f"{text.split()[0]} restored {text.split()[1][:8]}, mirrored")


# --- 3. export ---------------------------------------------------------------


def _newest_archive(config: BackupHealthConfig) -> _Archive | None:
    pattern = re.compile(rf"^{re.escape(config.distro)}_(\d{{4}}-\d{{2}}-\d{{2}})\.tar$")
    found = []
    for path in config.export_dir.iterdir():
        match = pattern.match(path.name)
        if match and path.is_file():
            try:
                found.append(_Archive(path, date.fromisoformat(match[1]), path.stat().st_size))
            except ValueError:
                continue
    return max(found, key=lambda archive: archive.day, default=None)


def _export_marker_note(config: BackupHealthConfig, archive: _Archive) -> tuple[str, ...]:
    marker = config.mirror / EXPORT_LAST_OK_NAME
    try:
        text = marker.read_text(encoding="ascii", errors="replace").strip()
    except FileNotFoundError:
        return (f"{EXPORT_LAST_OK_NAME} absent ({marker}); the next successful export writes it",)
    except OSError as exc:
        return (f"{EXPORT_LAST_OK_NAME} unreadable: {exc}",)
    if text != archive.day.isoformat():
        return (f"{EXPORT_LAST_OK_NAME} names {text!r}, newest archive is {archive.day}",)
    return ()


def check_export(sweep: _Sweep) -> Row:
    config = sweep.config
    try:
        sweep.archive = _newest_archive(config)
    except OSError as exc:
        raise CouldNotRead(f"{config.export_dir}: {exc}") from None
    archive = sweep.archive
    if archive is None:
        return Row("export", RED, f"no {config.distro}_YYYY-MM-DD.tar in {config.export_dir}")
    age_days = (sweep.now.date() - archive.day).days
    detail = f"{archive.path.name}, {archive.size / _GIB:.1f} GiB, {age_days} days old"
    notes = _export_marker_note(config, archive)
    if archive.size == 0:
        return Row("export", RED, f"{detail} - zero bytes", notes)
    if age_days > config.export_max_age.days:
        return Row("export", RED, f"{detail} (limit {config.export_max_age.days} days)", notes)
    return Row("export", OK, detail, notes)


# --- 4. E: free --------------------------------------------------------------


def check_free_space(sweep: _Sweep) -> Row:
    try:
        free = sweep.free_bytes(sweep.config.export_dir)
    except OSError as exc:
        raise CouldNotRead(f"free space on {sweep.config.export_dir}: {exc}") from None
    detail = f"{free / _GIB:.1f} GiB free on {sweep.config.export_dir}"
    if sweep.archive is None:
        return Row("E: free", RED, f"{detail}; no archive to size the next export against")
    needed = sweep.archive.size * FREE_SPACE_FACTOR
    detail = f"{detail}, next export needs ~{needed / _GIB:.1f} GiB"
    if free < needed:
        return Row("E: free", RED, f"{detail} ({FREE_SPACE_FACTOR}x the newest archive)")
    return Row("E: free", OK, detail)


# --- the sweep ---------------------------------------------------------------

CHECKS: tuple[tuple[str, Callable[[_Sweep], Row]], ...] = (
    ("snapshot", check_snapshot),
    ("verified restore", check_verified_restore),
    ("export", check_export),
    ("E: free", check_free_space),
)


def check_health(
    config: BackupHealthConfig = BackupHealthConfig(),
    run: Runner = run_command,
    now: Callable[[], datetime] = local_now,
    free_bytes: Callable[[Path], int] = disk_free,
) -> HealthReport:
    """Run all four checks; one that cannot read is recorded and never stops the others."""
    blocked = preflight(config)
    if blocked is not None:
        return blocked
    sweep = _Sweep(config=config, run=run, now=_aware(now()), free_bytes=free_bytes)
    rows = []
    for name, check in CHECKS:
        try:
            rows.append(check(sweep))
        except CouldNotRead as exc:
            rows.append(Row(name, COULD_NOT_READ, str(exc)))
    return HealthReport(rows=tuple(rows))


def _headline(report: HealthReport) -> str:
    code = report.exit_code
    if code == EXIT_NOT_CONFIGURED:
        return f"NOT CONFIGURED - {len(report.problems)} problem(s); no backup check measured"
    reds = sum(row.status == RED for row in report.rows)
    if code == EXIT_COULD_NOT_READ and not report.rows:
        return f"COULD NOT READ - {len(report.problems)} problem(s); no backup check measured"
    if code == EXIT_COULD_NOT_READ:
        unread = sum(row.status == COULD_NOT_READ for row in report.rows)
        measured = len(report.rows) - unread
        return (
            f"COULD NOT READ - {unread} of {len(report.rows)} backup checks unreadable; "
            f"{measured} measured — {reds} RED"
        )
    return f"{len(report.rows)} backup checks measured — {reds} RED"


def render(report: HealthReport) -> str:
    """The headline naming the count, then every row and problem beneath it."""
    lines = [_headline(report)]
    lines += [f"  {problem}" for problem in report.problems]
    for row in report.rows:
        lines.append(f"  {row.name:<17} {row.status:<8} {row.detail}")
        lines += [f"  {'':<17} {'NOTE':<8} {note}" for note in row.notes]
    return "\n".join(lines)


__all__ = [
    "BACKUP_UNIT",
    "COULD_NOT_READ",
    "DEFAULT_DISTRO",
    "DEFAULT_EXPORT_DIR",
    "EXIT_COULD_NOT_READ",
    "EXIT_MEASURED",
    "EXIT_NOT_CONFIGURED",
    "EXPORT_LAST_OK_NAME",
    "EXPORT_MAX_AGE",
    "FREE_SPACE_FACTOR",
    "OK",
    "RED",
    "RUNNING",
    "SNAPSHOT_MAX_AGE",
    "BackupHealthConfig",
    "HealthReport",
    "Row",
    "check_health",
    "disk_free",
    "local_now",
    "preflight",
    "render",
    "run_command",
]

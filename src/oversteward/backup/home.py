# ABOUTME: MIDDLE service for the daily live restic backup of /home — snapshot, prune, prove a restore.
# ABOUTME: restic.last-ok is written only after a restored file's sha256 matches its source.

"""Back up ``/home/natha`` with restic while the distro runs, and prove it worked.

One run is four steps, each of which must succeed before the next starts:

1. ``restic backup`` of the source, with the regenerable trees excluded.
2. ``restic forget`` with the retention policy and ``--prune``.
3. Restore one randomly chosen file from the *new* snapshot into a temporary
   directory and compare its sha256 against the source. The file is a git
   object (a loose object or a pack) written before the backup started: git
   names those files by their content and never rewrites them, so the source
   cannot have changed between the snapshot and the compare.
4. Write ``restic.last-ok`` (timestamp and snapshot id) in the state directory.

The key is only ever passed to restic as ``--password-file <path>``; this module
never opens it. It must live outside the backed-up tree, or the snapshot would
carry the key beside the repository it unlocks.

Exit codes:

* **0** — ok: snapshot taken, retention applied, restore verified, marker written.
* **1** — failed: a restic step failed, a source file could not be read, or the
  restore did not match. No marker is written.
* **2** — not configured: the key, the repository, restic or the source is
  missing, so nothing was attempted. Never reads as ok.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_CONFIGURED = 2

DEFAULT_SOURCE = Path.home()
DEFAULT_REPOSITORY = Path("/mnt/e/WSLBackups/restic")
DEFAULT_PASSWORD_FILE = Path("/mnt/c/Users/natha/AppData/Local/WslResilience/restic.key")
DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "oversteward" / "backup"
DEFAULT_RESTIC = Path.home() / ".local" / "bin" / "restic"

LAST_OK_NAME = "restic.last-ok"

#: Regenerable trees directly under the source, anchored to it.
SOURCE_EXCLUDES: tuple[str, ...] = (
    ".claude/tmp",
    ".cache",
    ".ollama",
    ".npm",
    ".vscode-server",
    "grantspider/data/irs_cache",
)

#: Build trees excluded wherever they appear.
ANYWHERE_EXCLUDES: tuple[str, ...] = (".venv", "node_modules")

RETENTION: tuple[str, ...] = (
    "--keep-daily", "14",
    "--keep-weekly", "8",
    "--keep-monthly", "6",
    "--prune",
)

#: Content-addressed files that git writes once and never changes in place.
VERIFY_GLOBS: tuple[str, ...] = ("*/.git/objects/??/*", "*/.git/objects/pack/*.pack")

_ERROR_LINES_SHOWN = 10
_RESTIC_UNREADABLE = 3


@dataclass(frozen=True, slots=True)
class HomeBackupConfig:
    """Where the backup reads from, writes to, and records success."""

    source: Path = DEFAULT_SOURCE
    repository: Path = DEFAULT_REPOSITORY
    password_file: Path = DEFAULT_PASSWORD_FILE
    state_dir: Path = DEFAULT_STATE_DIR
    restic: Path = DEFAULT_RESTIC


@dataclass(frozen=True, slots=True)
class RunResult:
    """What one restic invocation returned."""

    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class BackupOutcome:
    """The verdict of one run: an exit code, a headline, and the lines behind it."""

    exit_code: int
    headline: str
    details: tuple[str, ...] = ()


class StepFailed(Exception):
    """A step did not succeed; its message is the headline's reason."""

    def __init__(self, step: str, reason: str, details: Sequence[str] = ()) -> None:
        super().__init__(f"{step}: {reason}")
        self.step = step
        self.reason = reason
        self.details = tuple(details)


Runner = Callable[[Sequence[str]], RunResult]
Chooser = Callable[[Sequence[Path]], Path]


def run_command(argv: Sequence[str]) -> RunResult:
    """Run ``argv`` to completion with no timeout; a missing program is exit 127."""
    try:
        proc = subprocess.run(list(argv), capture_output=True, text=True, check=False)
    except OSError as exc:
        return RunResult(127, "", f"{argv[0]}: {exc}")
    return RunResult(proc.returncode, proc.stdout, proc.stderr)


def exclude_patterns(source: Path) -> list[str]:
    """restic ``--exclude`` patterns: source-level trees anchored, build trees anywhere."""
    return [str(source / rel) for rel in SOURCE_EXCLUDES] + list(ANYWHERE_EXCLUDES)


def _is_excluded(path: Path, source: Path) -> bool:
    rel = path.relative_to(source)
    if any(rel.is_relative_to(anchored) for anchored in SOURCE_EXCLUDES):
        return True
    return any(part in ANYWHERE_EXCLUDES for part in rel.parts)


def verify_candidates(source: Path, started: float) -> list[Path]:
    """Git objects under ``source`` that the snapshot must hold, sorted.

    A candidate is a regular file (not a symlink) matching :data:`VERIFY_GLOBS`,
    last modified before ``started`` (so it existed when the backup began), and
    outside every excluded tree.
    """
    found: set[Path] = set()
    for pattern in VERIFY_GLOBS:
        for path in source.glob(pattern):
            if path.is_symlink() or not path.is_file() or _is_excluded(path, source):
                continue
            if path.stat().st_mtime < started:
                found.add(path)
    return sorted(found)


def preflight(config: HomeBackupConfig) -> list[str]:
    """Everything missing before a run can start; empty means configured."""
    problems = []
    if not (config.restic.is_file() and os.access(config.restic, os.X_OK)):
        problems.append(f"restic binary not found at {config.restic} (ops/wsl/install-restic.sh)")
    if not config.password_file.is_file() or config.password_file.stat().st_size == 0:
        problems.append(f"password file missing or empty: {config.password_file}")
    elif config.password_file.resolve().is_relative_to(config.source.resolve()):
        problems.append(f"password file {config.password_file} is inside the backed-up source")
    if not (config.repository / "config").is_file():
        problems.append(f"{config.repository} is not an initialised restic repository")
    if not config.source.is_dir():
        problems.append(f"source directory missing: {config.source}")
    return problems


def _restic(config: HomeBackupConfig, *args: str) -> list[str]:
    return [
        str(config.restic),
        *args,
        "--repo", str(config.repository),
        "--password-file", str(config.password_file),
    ]


def _tail(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


def _unreadable_items(stderr: str) -> list[str]:
    items = []
    for line in stderr.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("message_type") == "error":
            items.append(str(message.get("item") or message.get("error", {}).get("message")))
    return items


def _summary(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("message_type") == "summary":
            return message
    return None


def _backup(config: HomeBackupConfig, run: Runner) -> dict:
    excludes = [arg for pattern in exclude_patterns(config.source) for arg in ("--exclude", pattern)]
    result = run(_restic(config, "backup", str(config.source), "--json", "--quiet", *excludes))
    if result.returncode == _RESTIC_UNREADABLE:
        items = _unreadable_items(result.stderr)
        shown = [f"unreadable: {item}" for item in items[:_ERROR_LINES_SHOWN]]
        raise StepFailed("backup", f"{len(items)} source file(s) could not be read", shown)
    if result.returncode != 0:
        raise StepFailed("backup", f"restic exited {result.returncode}: {_tail(result.stderr)}")
    summary = _summary(result.stdout)
    if summary is None or not summary.get("snapshot_id"):
        raise StepFailed("backup", "restic reported no snapshot")
    return summary


def _forget(config: HomeBackupConfig, run: Runner) -> None:
    result = run(_restic(config, "forget", *RETENTION, "--quiet"))
    if result.returncode != 0:
        raise StepFailed("forget", f"restic exited {result.returncode}: {_tail(result.stderr)}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify(
    config: HomeBackupConfig, run: Runner, snapshot_id: str, choose: Chooser, started: float
) -> tuple[Path, str]:
    candidates = verify_candidates(config.source, started)
    if not candidates:
        raise StepFailed("verify", f"no git object under {config.source} to restore and compare")
    chosen = choose(candidates)
    with tempfile.TemporaryDirectory(prefix="home-backup-verify-") as target:
        result = run(_restic(config, "restore", snapshot_id, "--target", target,
                             "--include", str(chosen), "--quiet"))
        if result.returncode != 0:
            raise StepFailed("verify", f"restic restore exited {result.returncode}: "
                                       f"{_tail(result.stderr)}")
        restored = Path(target) / chosen.relative_to(chosen.anchor)
        if not restored.is_file():
            raise StepFailed("verify", f"snapshot {snapshot_id[:8]} did not restore {chosen}")
        got, want = _sha256(restored), _sha256(chosen)
    if got != want:
        raise StepFailed("verify", f"sha256 mismatch on {chosen}: restored {got}, source {want}")
    return chosen, want


def _write_last_ok(state_dir: Path, stamp: datetime, snapshot_id: str) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    marker = state_dir / LAST_OK_NAME
    partial = state_dir / f"{LAST_OK_NAME}.partial"
    partial.write_text(f"{stamp.isoformat(timespec='seconds')} {snapshot_id}\n", encoding="utf-8")
    partial.replace(marker)
    return marker


def _ok_headline(config: HomeBackupConfig, summary: dict, chosen: Path, digest: str) -> str:
    mib = 1024 * 1024
    seconds = float(summary.get("total_duration") or 0)
    processed = int(summary.get("total_bytes_processed") or 0)
    rate = processed / mib / seconds if seconds else 0.0
    return (
        f"OK - snapshot {summary['snapshot_id'][:8]} of {config.source}: "
        f"{summary.get('files_new', 0)} new, {summary.get('files_changed', 0)} changed, "
        f"{int(summary.get('data_added') or 0) / mib:.1f} MiB added, "
        f"{processed / mib:.1f} MiB read in {seconds:.0f}s ({rate:.1f} MiB/s); "
        f"retention applied; restore of {chosen.relative_to(config.source)} verified "
        f"(sha256 {digest[:12]})"
    )


def run_backup(
    config: HomeBackupConfig = HomeBackupConfig(),
    run: Runner = run_command,
    choose: Chooser = random.SystemRandom().choice,
    now: Callable[[], datetime] = datetime.now,
) -> BackupOutcome:
    """Run backup, forget, verify and the marker in order; stop at the first failure."""
    problems = preflight(config)
    if problems:
        return BackupOutcome(
            EXIT_NOT_CONFIGURED,
            f"NOT CONFIGURED - {len(problems)} problem(s); nothing backed up",
            tuple(problems),
        )
    started = now().timestamp()
    try:
        summary = _backup(config, run)
        _forget(config, run)
        chosen, digest = _verify(config, run, summary["snapshot_id"], choose, started)
    except StepFailed as failure:
        return BackupOutcome(
            EXIT_FAILED, f"FAILED - {failure.step}: {failure.reason}", failure.details
        )
    marker = _write_last_ok(config.state_dir, now(), summary["snapshot_id"])
    return BackupOutcome(
        EXIT_OK, _ok_headline(config, summary, chosen, digest), (f"marker: {marker}",)
    )


def render(outcome: BackupOutcome) -> str:
    """The headline, then each detail line indented beneath it."""
    return "\n".join([outcome.headline, *(f"  {line}" for line in outcome.details)])


__all__ = [
    "ANYWHERE_EXCLUDES",
    "DEFAULT_PASSWORD_FILE",
    "DEFAULT_REPOSITORY",
    "DEFAULT_RESTIC",
    "DEFAULT_SOURCE",
    "DEFAULT_STATE_DIR",
    "EXIT_FAILED",
    "EXIT_NOT_CONFIGURED",
    "EXIT_OK",
    "LAST_OK_NAME",
    "RETENTION",
    "SOURCE_EXCLUDES",
    "VERIFY_GLOBS",
    "BackupOutcome",
    "HomeBackupConfig",
    "RunResult",
    "StepFailed",
    "exclude_patterns",
    "preflight",
    "render",
    "run_backup",
    "run_command",
    "verify_candidates",
]

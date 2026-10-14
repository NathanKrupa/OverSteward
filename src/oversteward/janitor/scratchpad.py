# ABOUTME: MIDDLE service that prunes dead sessions' scratchpad dirs under ~/.claude/tmp/claude-<uid>/.
# ABOUTME: A dir goes only when its files are old, no process holds it, and it holds no git repo.

"""Reclaim the disk that finished Claude Code sessions leave in ``~/.claude/tmp``.

Each session writes under ``<root>/<slug>/<uuid>/`` and nothing ever removes it.
A *candidate* is exactly such a ``<slug>/<uuid>/`` directory; every other entry
under the root (loose files, non-uuid dirs, symlinks) is counted and left alone.

A candidate is pruned only when all of these hold:

* **Old** — its newest regular file (``os.walk``, symlinks never followed) is at
  least ``days`` old. The directory's own mtime is not the age: a file written
  two levels down does not change its top directory's mtime. A
  candidate holding no regular file at all takes its own mtime.
* **Unheld** — no process the janitor can inspect has its cwd, its executable,
  an open file descriptor or a mapped file inside it, read from
  ``/proc/<pid>`` once before the sweep and again just before each delete. It
  can inspect every process of this uid but itself and the non-dumpable ones it
  names as not inspected. It cannot see processes of other uids (root daemons,
  ``sudo``), processes in other WSL distros (Docker Desktop's containers), or
  Windows-side access over 9p.
* **Free of git** — nothing inside it, walked without following symlinks, is
  an entry named ``.git`` (directory, file or symlink) or a directory holding
  ``HEAD``, ``objects/`` and ``refs/`` (a bare or ``--separate-git-dir``
  repository, whatever its name). Git can tie a repository inside to a
  checkout outside without leaving any trace inside (``--separate-git-dir``
  writes nothing back), so the
  janitor never judges those ties: a candidate holding any repository is
  SKIPPED, naming the first marker, for a person to remove by hand (or through
  ``worktree_doctor.py`` when it is a registered worktree).
* **Fully read** — every directory inside it could be listed; an unreadable one
  could hide a file written today.

The liveness scan fails closed. A process owned by this uid whose ``fd``
directory cannot be listed is a blind spot, and a running ``claude`` process
holding nothing under the root means the scan cannot see sessions at all
(measured 2026-10-14: every running session held its own ``<uuid>/tasks``
open); either aborts the run before anything is deleted.

Exit codes:

* **0** — measured: the dry run reported, or every prune completed.
* **1** — could not look (``/proc`` blind, a candidate unreadable) or a prune
  was partial. A blind scan deletes nothing.
* **2** — not configured: the root is missing, not a directory, or a symlink,
  or ``days`` is below 1. Nothing was attempted.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import stat
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NOT_CONFIGURED = 2

DEFAULT_ROOT = Path.home() / ".claude" / "tmp" / f"claude-{os.getuid()}"
DEFAULT_PROC = Path("/proc")
DEFAULT_DAYS = 7
C_DRIVE = Path("/mnt/c")
VHDX_GLOB = "/mnt/c/Users/natha/AppData/Local/wsl/*/ext4.vhdx"

#: Slack between the VHDX file and the distro's used bytes that is worth a compaction.
COMPACT_SLACK_BYTES = 20 * 1_000_000_000

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DELETED_SUFFIX = " (deleted)"
_CLAUDE_COMM = "claude"
_DAY_SECONDS = 86_400
_GB = 1_000_000_000

LIVE = "LIVE"
SKIPPED = "SKIPPED"
UNREADABLE = "UNREADABLE"
KEPT = "KEPT"
WOULD_PRUNE = "WOULD-PRUNE"
PRUNED = "PRUNED"
PARTIAL = "PARTIAL"


@dataclass(frozen=True, slots=True)
class JanitorConfig:
    """Where the janitor looks, how old a session must be, and whether it deletes."""

    root: Path = DEFAULT_ROOT
    proc: Path = DEFAULT_PROC
    days: int = DEFAULT_DAYS
    apply: bool = False


@dataclass(frozen=True, slots=True)
class DiskStats:
    """Free space on C:, the VHDX file's size and the distro's used bytes; ``None`` is unmeasured."""

    c_free: int | None
    vhdx_bytes: int | None
    root_used: int | None


@dataclass(frozen=True, slots=True)
class JanitorOutcome:
    """The verdict of one run: an exit code, a headline, and the lines behind it."""

    exit_code: int
    headline: str
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Scan:
    """What walking one candidate found."""

    size: int
    newest: float
    newest_file: str
    #: The first git repository marker found inside, which keeps the dir.
    git: str | None
    unreadable: str | None


@dataclass(frozen=True, slots=True)
class _Holders:
    """Which candidates running processes hold, and why the scan cannot be trusted if it cannot."""

    held: dict[tuple[str, str], list[int]]
    blind: list[str]
    #: Pids running as this uid whose open files (non-dumpable) or maps (extra capabilities)
    #: the kernel withholds.
    withheld: list[str]


DiskProbe = Callable[[], DiskStats]
#: Re-reads ``/proc`` for one candidate just before it is deleted: a verdict and note to keep it.
Recheck = Callable[[Path], tuple[str, str] | None]


def measure_disk() -> DiskStats:
    """Read C:'s free space, the distro VHDX's size and ``/``'s used bytes; unreadable is ``None``."""
    try:
        c_free: int | None = shutil.disk_usage(C_DRIVE).free
    except OSError:
        c_free = None
    try:
        root_used: int | None = shutil.disk_usage("/").used
    except OSError:
        root_used = None
    sizes = []
    for path in glob.glob(VHDX_GLOB):
        try:
            sizes.append(os.stat(path).st_size)
        except OSError:
            continue
    return DiskStats(c_free=c_free, vhdx_bytes=max(sizes) if sizes else None, root_used=root_used)


def compact_advised(vhdx_bytes: int, root_used: int) -> bool:
    """True when the VHDX holds more than :data:`COMPACT_SLACK_BYTES` the distro no longer uses."""
    return vhdx_bytes - root_used > COMPACT_SLACK_BYTES


def _root_problem(root: Path) -> str | None:
    if root.is_symlink():
        return f"{root} is a symlink; the janitor never follows one into a tree it deletes"
    if not root.exists():
        return f"{root} does not exist"
    if not root.is_dir():
        return f"{root} is not a directory"
    return None


def _candidates(root: Path) -> tuple[list[Path], int]:
    """The ``<slug>/<uuid>/`` dirs under ``root``, and how many other entries were left alone."""
    found: list[Path] = []
    other = 0
    for slug in sorted(root.iterdir()):
        if slug.is_symlink() or not slug.is_dir():
            other += 1
            continue
        for entry in sorted(slug.iterdir()):
            if entry.is_symlink() or not entry.is_dir() or not _UUID.fullmatch(entry.name):
                other += 1
                continue
            found.append(entry)
    return found, other


_GIT_SKIP_REMEDY = (
    "holds a git repository; remove it by hand or through worktree_doctor "
    "if it is a registered worktree"
)


def _git_marker(dirpath: str, dirnames: list[str], filenames: list[str]) -> str | None:
    """The first sign of a git repository in one walked directory, or ``None``.

    An entry named ``.git`` of any type (directory, file or symlink), or the
    directory itself when it holds what git requires of a repository directory
    (``is_git_directory``): a ``HEAD`` file beside ``objects/`` and ``refs/``.
    That catches a bare or ``--separate-git-dir`` repository whatever its name.
    """
    if ".git" in dirnames or ".git" in filenames:
        return os.path.join(dirpath, ".git")
    if "HEAD" in filenames and {"objects", "refs"} <= set(dirnames):
        return dirpath
    return None


def _scan(candidate: Path) -> _Scan:
    """Walk ``candidate`` in sorted order without following symlinks.

    Collects bytes on disk, the newest regular file and the first git
    repository marker (:func:`_git_marker`).
    """
    size = 0
    newest = candidate.lstat().st_mtime
    newest_file = ""
    seen_file = False
    git: str | None = None
    errors: list[OSError] = []
    for dirpath, dirnames, filenames in os.walk(candidate, onerror=errors.append):
        dirnames.sort()
        if git is None:
            git = _git_marker(dirpath, dirnames, filenames)
        for name in dirnames + sorted(filenames):
            path = os.path.join(dirpath, name)
            try:
                info = os.lstat(path)
            except OSError as exc:
                errors.append(exc)
                continue
            size += info.st_blocks * 512
            if not stat.S_ISREG(info.st_mode):
                continue
            if not seen_file or info.st_mtime > newest:
                newest, newest_file, seen_file = info.st_mtime, os.path.relpath(path, candidate), True
    unreadable = f"{errors[0].filename}: {errors[0].strerror}" if errors else None
    return _Scan(size, newest, newest_file, git, unreadable)


def _strip_deleted(target: str) -> str:
    return target[: -len(_DELETED_SUFFIX)] if target.endswith(_DELETED_SUFFIX) else target


def _candidate_key(target: str, root: str) -> tuple[str, str] | None:
    """The ``(slug, uuid)`` that ``target``, already known to lie under ``root``, lies in."""
    parts = target[len(root) + 1 :].split(os.sep)
    return (parts[0], parts[1]) if len(parts) >= 2 else None


def _mapped(entry: Path) -> list[str] | None:
    """Files ``entry`` has mapped (shared libraries, mmapped data), from ``/proc/<pid>/maps``.

    A process can keep using a file it mapped after closing the descriptor, so
    ``fd`` alone misses an interpreter running from a venv inside a scratchpad.
    ``None`` when the kernel refuses the read: a process of this uid holding a
    capability the reader lacks (``systemd --user`` holds ``CAP_WAKE_ALARM``)
    keeps its ``maps`` even from its own user. A process that exited is empty:
    ``maps`` is missing, or (exited between the open and the read) the read
    raises ``ProcessLookupError``.
    """
    try:
        text = (entry / "maps").read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, ProcessLookupError):
        return []
    except PermissionError:
        return None
    found = []
    for line in text.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and fields[5].startswith("/"):
            found.append(fields[5])
    return found


def _targets(entry: Path) -> list[str]:
    """Every path ``entry`` (a ``/proc/<pid>``) holds; ``PermissionError`` from ``fd`` propagates."""
    found = []
    for link in ("cwd", "exe"):
        try:
            found.append(os.readlink(entry / link))
        except OSError:
            continue  # exited, a zombie, or a kernel thread
    for fd in os.listdir(entry / "fd"):
        try:
            found.append(os.readlink(entry / "fd" / fd))
        except OSError:
            continue  # closed between the listing and the read
    return found


def _comm(entry: Path) -> str:
    try:
        return (entry / "comm").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _pids(proc: Path) -> Iterable[Path]:
    return (entry for entry in proc.iterdir() if entry.name.isdigit())


def _owners(entry: Path) -> tuple[int, int]:
    """The uid owning ``/proc/<pid>`` and the uid owning its ``fd`` directory.

    The kernel hands a non-dumpable process's ``fd`` directory to root even when
    the process runs as this user (``(sd-pam)`` under systemd --user is one), so
    the two can differ; the ``fd`` owner is whose files the kernel says they are.
    """
    return entry.lstat().st_uid, (entry / "fd").lstat().st_uid


def _holders(proc: Path, root: str, self_pid: int, uid: int) -> _Holders:
    """Map each held candidate to the pids holding it; record every blind spot and withheld pid."""
    held: dict[tuple[str, str], list[int]] = {}
    blind: list[str] = []
    withheld: list[str] = []
    for entry in _pids(proc):
        pid = int(entry.name)
        if pid == self_pid:
            continue
        try:
            pid_owner, fd_owner = _owners(entry)
        except FileNotFoundError:
            continue  # the process exited mid-scan
        try:
            targets = _targets(entry)
        except FileNotFoundError:
            continue  # the process exited mid-scan
        except PermissionError as exc:
            if fd_owner == uid:
                blind.append(f"pid {pid}: cannot read its open files ({exc.strerror})")
            elif pid_owner == uid:
                withheld.append(f"pid {pid} {_comm(entry) or '?'}")
            continue
        mapped = _mapped(entry)
        if mapped is None:
            if pid_owner == uid:
                withheld.append(f"pid {pid} {_comm(entry) or '?'} (maps only)")
            mapped = []
        held_paths = map(_strip_deleted, targets + mapped)
        under_root = [t for t in held_paths if t.startswith(root + os.sep)]
        if fd_owner == uid and _comm(entry) == _CLAUDE_COMM and not under_root:
            blind.append(
                f"pid {pid}: a running claude holds nothing under {root}, "
                "so the scan cannot see sessions"
            )
        for key in {key for t in under_root if (key := _candidate_key(t, root)) is not None}:
            held.setdefault(key, []).append(pid)
    return _Holders(held, blind, withheld)


def _gb(size: int) -> str:
    return f"{size / _GB:.1f} GB"


def _remove(candidate: Path) -> list[str]:
    """``rmtree`` that keeps going past a failure and returns every error it met."""
    errors: list[str] = []

    def _record(_func, path, exc) -> None:
        errors.append(f"{path}: {exc}")

    shutil.rmtree(candidate, onexc=_record)
    return errors


def _remaining(candidate: Path) -> int:
    return _scan(candidate).size if candidate.exists() else 0


def _disk_lines(disk: DiskStats) -> list[str]:
    lines = [f"/mnt/c free: {_gb(disk.c_free) if disk.c_free is not None else 'unmeasured'}"]
    if disk.vhdx_bytes is None or disk.root_used is None:
        lines.append("ext4.vhdx: unmeasured")
        return lines
    lines.append(f"ext4.vhdx: {_gb(disk.vhdx_bytes)} (used on /: {_gb(disk.root_used)})")
    if compact_advised(disk.vhdx_bytes, disk.root_used):
        slack = disk.vhdx_bytes - disk.root_used
        lines.append(
            f"COMPACT ADVISED: the VHDX holds {_gb(slack)} the distro no longer uses "
            "(ops/wsl/README.md, 'The scratchpad janitor')"
        )
    return lines


def run_janitor(
    config: JanitorConfig,
    *,
    now: float | None = None,
    self_pid: int | None = None,
    uid: int | None = None,
    disk: DiskProbe = measure_disk,
) -> JanitorOutcome:
    """Report every candidate's verdict and, under ``config.apply``, delete the prunable ones."""
    now = time.time() if now is None else now
    self_pid = os.getpid() if self_pid is None else self_pid
    uid = os.getuid() if uid is None else uid
    if config.days < 1:
        return JanitorOutcome(
            EXIT_NOT_CONFIGURED, f"NOT CONFIGURED - days must be at least 1, got {config.days}"
        )
    problem = _root_problem(config.root)
    if problem is not None:
        return JanitorOutcome(EXIT_NOT_CONFIGURED, f"NOT CONFIGURED - {problem}")
    root = os.path.realpath(config.root)
    try:
        holders = _holders(config.proc, root, self_pid, uid)
    except OSError as exc:
        return JanitorOutcome(EXIT_FAILED, f"FAILED - cannot read {config.proc}: {exc}")
    if holders.blind:
        return JanitorOutcome(
            EXIT_FAILED,
            f"FAILED - the liveness scan is blind; nothing was deleted ({len(holders.blind)})",
            tuple(holders.blind),
        )
    return _sweep(config, holders, now, disk(), _recheck(config.proc, root, self_pid, uid))


def _recheck(proc: Path, root: str, self_pid: int, uid: int) -> Recheck:
    """A fresh liveness read for one candidate, so a session resumed mid-sweep is never deleted."""

    def recheck(candidate: Path) -> tuple[str, str] | None:
        try:
            current = _holders(proc, root, self_pid, uid)
        except OSError as exc:
            return UNREADABLE, f"liveness re-check could not read {proc}: {exc}"
        if current.blind:
            return UNREADABLE, f"liveness re-check blind: {current.blind[0]}"
        pids = current.held.get((candidate.parent.name, candidate.name))
        if pids:
            return LIVE, "held at re-check by " + ", ".join(f"pid {pid}" for pid in sorted(pids))
        return None

    return recheck


def _verdict(
    candidate: Path, scan: _Scan, holders: _Holders, config: JanitorConfig, now: float
) -> tuple[str, str]:
    """The verdict for a candidate that has been scanned but not touched, and its note."""
    pids = holders.held.get((candidate.parent.name, candidate.name))
    if scan.unreadable is not None:
        return UNREADABLE, scan.unreadable
    if pids:
        return LIVE, "held by " + ", ".join(f"pid {pid}" for pid in sorted(pids))
    if scan.git is not None:
        return SKIPPED, f"{scan.git} {_GIT_SKIP_REMEDY}"
    if now - scan.newest < config.days * _DAY_SECONDS:
        return KEPT, f"newest {scan.newest_file or '(no files)'}"
    return (PRUNED if config.apply else WOULD_PRUNE), ""


def _judge(
    candidate: Path, holders: _Holders, config: JanitorConfig, now: float, recheck: Recheck
) -> tuple[str, int, str]:
    """Scan one candidate, delete it if ``config.apply`` and it is prunable: verdict, freed, row."""
    scan = _scan(candidate)
    verdict, note = _verdict(candidate, scan, holders, config, now)
    freed = scan.size if verdict == WOULD_PRUNE else 0
    if verdict == PRUNED:
        kept = recheck(candidate)
        if kept is not None:
            verdict, note = kept
    if verdict == PRUNED:
        errors = _remove(candidate)
        freed = scan.size - _remaining(candidate)
        if errors:
            verdict, note = PARTIAL, f"{len(errors)} error(s), first: {errors[0]}"
    age = max(0.0, now - scan.newest) / _DAY_SECONDS
    rel = candidate.relative_to(config.root)
    return verdict, freed, f"{verdict:<11} {_gb(scan.size):>9} {age:6.1f}d  {rel}  {note}".rstrip()


def _sweep(
    config: JanitorConfig, holders: _Holders, now: float, disk: DiskStats, recheck: Recheck
) -> JanitorOutcome:
    candidates, other = _candidates(config.root)
    rows: list[str] = []
    counts: dict[str, int] = {}
    freed = 0
    for candidate in candidates:
        verdict, size, row = _judge(candidate, holders, config, now, recheck)
        counts[verdict] = counts.get(verdict, 0) + 1
        freed += size
        rows.append(row)

    pruned = counts.get(PRUNED, 0) + counts.get(WOULD_PRUNE, 0)
    summary = (
        f"{'freed' if config.apply else 'would free'} {_gb(freed)} from {pruned} of "
        f"{len(candidates)} session dirs older than {config.days} days "
        f"({'apply' if config.apply else 'dry run'})"
    )
    totals = (
        f"totals: {'freed' if config.apply else 'would-free'} {_gb(freed)} "
        f"({pruned} dirs); live {counts.get(LIVE, 0)}; skipped {counts.get(SKIPPED, 0)}; "
        f"kept {counts.get(KEPT, 0)}; partial {counts.get(PARTIAL, 0)}; "
        f"unreadable {counts.get(UNREADABLE, 0)}; unrecognised {other}"
    )
    withheld = (
        f"not inspected: {len(holders.withheld)} process(es) of this uid whose open files "
        f"or maps the kernel withholds: {', '.join(holders.withheld) or 'none'}"
    )
    details = (*rows, totals, withheld, *_disk_lines(disk))
    if counts.get(PARTIAL, 0):
        return JanitorOutcome(EXIT_FAILED, f"PARTIAL - {summary}", details)
    if counts.get(UNREADABLE, 0):
        return JanitorOutcome(EXIT_FAILED, f"FAILED - could not read every dir; {summary}", details)
    return JanitorOutcome(EXIT_OK, f"OK - {summary}", details)


def render(outcome: JanitorOutcome) -> str:
    """The headline, then each detail line indented beneath it."""
    return "\n".join([outcome.headline, *(f"  {line}" for line in outcome.details)])


__all__ = [
    "COMPACT_SLACK_BYTES",
    "DEFAULT_DAYS",
    "DEFAULT_PROC",
    "DEFAULT_ROOT",
    "EXIT_FAILED",
    "EXIT_NOT_CONFIGURED",
    "EXIT_OK",
    "VHDX_GLOB",
    "DiskStats",
    "JanitorConfig",
    "JanitorOutcome",
    "compact_advised",
    "measure_disk",
    "render",
    "run_janitor",
]

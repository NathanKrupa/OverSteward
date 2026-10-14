# ABOUTME: MIDDLE service that prunes dead sessions' scratchpad dirs under ~/.claude/tmp/claude-<uid>/.
# ABOUTME: A dir goes only when every file in it is old and no process holds anything inside it.

"""Reclaim the disk that finished Claude Code sessions leave in ``~/.claude/tmp``.

Each session writes under ``<root>/<slug>/<uuid>/`` and nothing ever removes it.
A *candidate* is exactly such a ``<slug>/<uuid>/`` directory; every other entry
under the root (loose files, non-uuid dirs, symlinks) is counted and left alone.

A candidate is pruned only when all of these hold:

* **Old** — its newest regular file (``os.walk``, symlinks never followed) is at
  least ``days`` old. The directory's own mtime is not the age: a clone inside
  a scratchpad receives new packs without its top directory changing. A
  candidate holding no regular file at all takes its own mtime.
* **Unheld** — no process the janitor can inspect has its cwd, its executable
  or any open file descriptor inside it, read from ``/proc/<pid>`` once before
  the sweep and again just before each delete. It can inspect every process of
  this uid but itself and the non-dumpable ones it names as not inspected. It
  cannot see processes of other uids (root daemons, ``sudo``) or Windows-side
  access over 9p.
* **Not tied by git to a live checkout outside it** — git ties a repository to
  its checkouts, and either end can lie inside a candidate. The janitor reads
  every trace git leaves on disk:

  - a ``.git`` *file* (a worktree or submodule checkout) whose ``gitdir:``
    names an existing repository outside the candidate. Deleting it would leave
    that repository a dangling registration;
  - a ``worktrees/<name>/gitdir`` file (inside a clone's ``.git`` or a bare
    repository) naming an existing worktree outside the candidate. That
    worktree's commits live only in this clone, so deleting it destroys them;
  - a repository directory (``HEAD``, ``config`` and ``objects/``) whose
    ``core.worktree`` names an existing checkout outside the candidate;
  - a non-bare repository directory not named ``.git`` and without
    ``core.worktree`` — a ``--separate-git-dir`` repository, whose checkout's
    ``.git`` file points at it while it records nothing back — unless a
    ``.git`` file inside the candidate names it.

  Any of these keeps the candidate (SKIPPED). A link whose far end no longer
  exists, or lies inside the same candidate, ties nothing outside and does not;
  a link file or config that cannot be read or parsed keeps the candidate too.
  Two ties leave no trace inside the candidate and are not seen: a repository
  driven only through ``GIT_DIR``/``GIT_WORK_TREE`` with a checkout elsewhere,
  and an outside repository borrowing this one's objects through
  ``objects/info/alternates``.
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
    #: What git ties between this dir and a live checkout outside it, and the remedy.
    link: tuple[str, str] | None
    unreadable: str | None


@dataclass(frozen=True, slots=True)
class _Holders:
    """Which candidates running processes hold, and why the scan cannot be trusted if it cannot."""

    held: dict[tuple[str, str], list[int]]
    blind: list[str]
    #: Pids running as this uid whose open files the kernel withholds (non-dumpable).
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


_READ_LIMIT = 65_536
_TRUE = frozenset({"true", "yes", "on", "1"})


def _read_inside(path: str, candidate_real: str) -> str | None:
    """The text of a file inside the candidate, or ``None`` if it lies outside or cannot be read."""
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(candidate_real):
        return None
    try:
        with resolved.open(encoding="utf-8", errors="replace") as handle:
            return handle.read(_READ_LIMIT)
    except OSError:
        return None


def _link_target(path: str, prefix: str, candidate_real: str) -> str | None:
    """The absolute path a git link file names, a relative one resolved from the file's directory.

    ``None`` when the file cannot be read or its first line is not ``<prefix><path>``.
    """
    text = _read_inside(path, candidate_real)
    first = text.strip().split("\n", 1)[0] if text else ""
    target = first[len(prefix) :].strip() if first.startswith(prefix) else ""
    return os.path.normpath(os.path.join(os.path.dirname(path), target)) if target else None


def _outside(target: str, candidate_real: str) -> bool:
    """True when ``target`` still exists and does not lie inside the candidate."""
    if not os.path.lexists(target):
        return False  # the far end is gone; nothing outside is tied to this dir
    return not (os.path.realpath(target) + os.sep).startswith(candidate_real + os.sep)


def _core_config(repo: str, candidate_real: str) -> dict[str, str] | None:
    """The ``[core]`` keys of a repository's ``config``, lower-cased; ``None`` if unreadable."""
    text = _read_inside(os.path.join(repo, "config"), candidate_real)
    if text is None:
        return None
    section, core = "", {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        if line.startswith("["):
            section = line.strip("[]").strip().lower()
        elif section == "core" and "=" in line:
            key, value = line.split("=", 1)
            core[key.strip().lower()] = value.strip().strip('"')
    return core


def _teardown(what: str, worktree: str) -> tuple[str, str]:
    return what, f"tear it down from its repo with scripts/dev/worktree_doctor.py teardown {worktree}"


def _link_tie(path: str, kind: str, candidate_real: str) -> tuple[str, str] | None:
    """What a ``.git`` file or a ``worktrees/<name>/gitdir`` file ties outside the candidate."""
    here = os.path.dirname(path)
    target = _link_target(path, "gitdir:" if kind == ".git" else "", candidate_real)
    if target is None:
        return f"unreadable git link file {path}", "read it, then decide by hand"
    if not _outside(target, candidate_real):
        return None
    if kind == ".git":
        return _teardown(f"checkout at {here} is registered with {target}", here)
    clone, worktree = os.path.dirname(os.path.dirname(here)), os.path.dirname(target)
    return _teardown(f"clone at {clone} has a linked worktree at {worktree}", worktree)


def _repo_tie(repo: str, named: set[str], candidate_real: str) -> tuple[str, str] | None:
    """What a repository directory inside the candidate ties to a checkout outside it.

    ``named`` holds the repositories some ``.git`` file inside the candidate names.
    """
    core = _core_config(repo, candidate_real)
    if core is None:
        return f"unreadable git config in {repo}", "read it, then decide by hand"
    if "worktree" in core:
        checkout = os.path.normpath(os.path.join(repo, core["worktree"]))
        if not _outside(checkout, candidate_real):
            return None
        return (
            f"repository at {repo} has its checkout at {checkout}",
            f"push or move the work in {checkout}, then delete {repo} by hand",
        )
    separate = os.path.basename(repo) != ".git" and core.get("bare", "").lower() not in _TRUE
    if not separate or os.path.realpath(repo) in named:
        return None
    return (
        f"repository at {repo} is a separate git dir no checkout inside this dir names",
        f"find its checkout (its .git file names {repo}), push its work, then delete by hand",
    )


def _git_tie(
    links: list[tuple[str, str]], repos: list[str], candidate_real: str
) -> tuple[str, str] | None:
    """The first thing git ties between the candidate and a live checkout outside it."""
    for path, kind in links:
        tie = _link_tie(path, kind, candidate_real)
        if tie is not None:
            return tie
    named = set()
    for path, kind in links:
        target = _link_target(path, "gitdir:", candidate_real) if kind == ".git" else None
        if target is not None:
            named.add(os.path.realpath(target))
    for repo in repos:
        tie = _repo_tie(repo, named, candidate_real)
        if tie is not None:
            return tie
    return None


def _link_kind(dirpath: str, name: str) -> str | None:
    if name == ".git":
        return ".git"
    if name == "gitdir" and os.path.basename(os.path.dirname(dirpath)) == "worktrees":
        return "gitdir"
    return None


def _scan(candidate: Path) -> _Scan:
    """Walk ``candidate`` in sorted order without following symlinks.

    Collects bytes on disk, the newest regular file, every git link file and
    every repository directory (one holding ``HEAD``, ``config`` and ``objects/``).
    """
    size = 0
    newest = candidate.lstat().st_mtime
    newest_file = ""
    seen_file = False
    links: list[tuple[str, str]] = []
    repos: list[str] = []
    errors: list[OSError] = []
    for dirpath, dirnames, filenames in os.walk(candidate, onerror=errors.append):
        dirnames.sort()
        if "objects" in dirnames and {"HEAD", "config"} <= set(filenames):
            repos.append(dirpath)
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
            kind = _link_kind(dirpath, name)
            if kind is not None:
                links.append((path, kind))
            if not seen_file or info.st_mtime > newest:
                newest, newest_file, seen_file = info.st_mtime, os.path.relpath(path, candidate), True
    unreadable = f"{errors[0].filename}: {errors[0].strerror}" if errors else None
    tie = _git_tie(links, repos, os.path.realpath(candidate))
    return _Scan(size, newest, newest_file, tie, unreadable)


def _strip_deleted(target: str) -> str:
    return target[: -len(_DELETED_SUFFIX)] if target.endswith(_DELETED_SUFFIX) else target


def _candidate_key(target: str, root: str) -> tuple[str, str] | None:
    """The ``(slug, uuid)`` that ``target``, already known to lie under ``root``, lies in."""
    parts = target[len(root) + 1 :].split(os.sep)
    return (parts[0], parts[1]) if len(parts) >= 2 else None


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
        under_root = [t for t in map(_strip_deleted, targets) if t.startswith(root + os.sep)]
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
    if scan.link is not None:
        what, remedy = scan.link
        return SKIPPED, f"{what}; {remedy}"
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
        f"not inspected: {len(holders.withheld)} non-dumpable process(es) of this uid whose "
        f"open files the kernel withholds: {', '.join(holders.withheld) or 'none'}"
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

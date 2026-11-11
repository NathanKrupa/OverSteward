# ABOUTME: The dream cycle's machine-wide run lock: one holder record on disk plus an append-only run ledger.
# ABOUTME: Stdlib-only. The holder is the long-lived `claude` ancestor, identified by pid and kernel start time.

from __future__ import annotations

import fcntl
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)

# Machine-local, beside the Stop hook's dream_queue.jsonl. Not under the repo's
# data/dream/: cycle.OVERSTEWARD_ROOT comes from __file__, so a repo path would
# give every worktree its own lock, which is no lock at all.
DEFAULT_LOCK_PATH = Path.home() / ".claude" / "dream_run.lock"
DEFAULT_RUNS_PATH = Path.home() / ".claude" / "dream_runs.jsonl"

# How long ensure/release wait for the flock that serializes their
# read-decide-write. The flock is held only for that critical section, never
# for the run; the record on disk is the lock.
DEFAULT_WAIT_SECONDS = 5.0
_POLL_SECONDS = 0.01

TRIGGERS = ("timer", "session", "manual")
TRIGGER_ENV = "OVERSTEWARD_DREAM_TRIGGER"

# Every scripts/dream.py call is a process that lives for milliseconds, so the
# holder is the Claude Code process that runs the whole cycle above it.
HOLDER_COMM = "claude"
PROC_ROOT = Path("/proc")

# /proc/<pid>/stat: after the ")" closing comm, field 3 (state) is index 0, so
# ppid (field 4) is index 1 and starttime (field 22) is index 19 (proc(5)).
_PPID_INDEX = 1
_START_INDEX = 19

STARTED = "started"
RECLAIMED = "reclaimed"
SKIPPED = "skipped"
COMPLETED = "completed"
ENDED = "ended"


class Locked(Exception):
    """Another live run holds the lock."""


class LockUnreadable(Exception):
    """The lock could not be read, or liveness could not be judged.

    Never treated as a free lock: a run that cannot look does not write.
    """


@dataclass(frozen=True)
class ProcStat:
    """The three /proc/<pid>/stat fields the lock reads, plus the pid itself."""

    pid: int
    comm: str
    ppid: int
    start: int


@dataclass(frozen=True)
class Holder:
    """A lock holder. Identity is (pid, start): a recycled pid is another process."""

    pid: int
    start: int
    comm: str = field(default="", compare=False)


# pid -> its kernel start time, or None when it cannot be read (gone, or no /proc).
Probe = Callable[[int], "int | None"]


def parse_stat(text: str) -> ProcStat:
    """Parse one /proc/<pid>/stat line. comm may hold spaces and ")", so split on the LAST ")"."""
    head, _, rest = text.rpartition(")")
    pid, _, comm = head.partition(" (")
    fields = rest.split()
    return ProcStat(int(pid), comm, int(fields[_PPID_INDEX]), int(fields[_START_INDEX]))


def read_stat(pid: int, proc_root: Path = PROC_ROOT) -> ProcStat | None:
    """The process's stat, or None when /proc has no readable, parsable entry for it."""
    try:
        return parse_stat((proc_root / str(pid) / "stat").read_text(encoding="utf-8"))
    except (OSError, ValueError, IndexError):
        return None


def proc_start_time(pid: int, proc_root: Path = PROC_ROOT) -> int | None:
    """The default liveness probe: the pid's kernel start time, or None."""
    stat = read_stat(pid, proc_root)
    return None if stat is None else stat.start


def discover_holder(pid: int | None = None, proc_root: Path = PROC_ROOT) -> Holder:
    """The nearest ancestor of ``pid`` whose comm is ``claude``, else its direct parent.

    Raises :class:`LockUnreadable` when ``pid`` or its parent cannot be read.
    """
    own = read_stat(os.getpid() if pid is None else pid, proc_root)
    parent = read_stat(own.ppid, proc_root) if own is not None else None
    if parent is None:
        raise LockUnreadable("could not read the run lock holder: /proc is unreadable")
    ancestor: ProcStat | None = parent
    while ancestor is not None:
        if ancestor.comm == HOLDER_COMM:
            return Holder(ancestor.pid, ancestor.start, ancestor.comm)
        ancestor = read_stat(ancestor.ppid, proc_root) if ancestor.ppid > 0 else None
    return Holder(parent.pid, parent.start, parent.comm)


def default_trigger(holder: Holder, environ: dict[str, str]) -> str:
    """The environment's trigger (the timer unit sets it), else session under claude, else manual."""
    explicit = environ.get(TRIGGER_ENV)
    if explicit:
        return explicit
    return "session" if holder.comm == HOLDER_COMM else "manual"


def _well_formed(record: object) -> bool:
    """A holder record: integer pid and start, string trigger and started_at."""
    if not isinstance(record, dict):
        return False
    numbers = all(type(record.get(key)) is int for key in ("pid", "start"))
    strings = all(isinstance(record.get(key), str) for key in ("trigger", "started_at"))
    return numbers and strings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RunLock:
    """One exclusive dream run per machine, held across many short CLI calls.

    The record file holds the holder as JSON (pid, start, trigger, started_at),
    or nothing when free. The runs file is append-only: one row per decision.
    """

    def __init__(
        self,
        lock_path: Path,
        runs_path: Path,
        *,
        probe: Probe | None = None,
        wait_seconds: float | None = None,
    ) -> None:
        self.lock_path = lock_path
        self.runs_path = runs_path
        self._probe = probe if probe is not None else proc_start_time
        self._wait = DEFAULT_WAIT_SECONDS if wait_seconds is None else wait_seconds

    def ensure(self, holder: Holder, trigger: str) -> bool:
        """Hold the lock for ``holder``. True when this call acquired it, False when already held.

        Raises :class:`Locked` (after recording a ``skipped`` row) when another live
        holder has it, and :class:`LockUnreadable` when the record or liveness
        cannot be read.
        """
        with self._critical() as fd:
            record = self._read(fd)
            if record is not None and self._is_holder(record, holder):
                return False
            if self._probe(holder.pid) != holder.start:
                raise LockUnreadable(
                    f"could not read the run lock {self.lock_path}: "
                    f"liveness of this run's own holder (pid {holder.pid}) is unreadable"
                )
            if record is not None:
                self._displace(record, holder, trigger)
            self._write(fd, holder, trigger)
            self._append(STARTED, holder, trigger)
            return True

    def release(self, holder: Holder, event: str, *, count: int = 0, reason: str = "") -> None:
        """Free the lock and close the run with ``event``. Only the holder may release."""
        with self._critical() as fd:
            record = self._read(fd)
            if record is not None and not self._is_holder(record, holder):
                raise Locked(self._locked_message(record))
            trigger = record["trigger"] if record is not None else ""
            os.ftruncate(fd, 0)
            os.fsync(fd)
            self._append(event, holder, trigger, count=count, reason=reason)

    # ---- the decision ---------------------------------------------------------

    def _displace(self, record: dict, holder: Holder, trigger: str) -> None:
        """Refuse a live foreign holder; record the reclaim of a dead or recycled one."""
        if self._probe(record["pid"]) == record["start"]:
            self._append(SKIPPED, holder, trigger, reason=f"locked by {record['pid']}")
            raise Locked(self._locked_message(record))
        reason = (
            f"reclaimed from dead pid {record['pid']} "
            f"({record['trigger']}, since {record['started_at']})"
        )
        log.warning("dream run lock: %s", reason)
        self._append(RECLAIMED, holder, trigger, reason=reason)

    @staticmethod
    def _is_holder(record: dict, holder: Holder) -> bool:
        return (record["pid"], record["start"]) == (holder.pid, holder.start)

    @staticmethod
    def _locked_message(record: dict) -> str:
        return (
            f"locked by pid {record['pid']} "
            f"({record['trigger']}, since {record['started_at']})"
        )

    # ---- the record file ------------------------------------------------------

    def _critical(self) -> _Flock:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        return _Flock(self.lock_path, self._wait)

    def _read(self, fd: int) -> dict | None:
        os.lseek(fd, 0, os.SEEK_SET)
        text = b""
        while chunk := os.read(fd, 65536):
            text += chunk
        if not text.strip():
            return None
        try:
            record = json.loads(text)
        except ValueError:
            record = None
        if not _well_formed(record):
            raise LockUnreadable(f"could not read the run lock {self.lock_path}: unparsable record")
        return record

    @staticmethod
    def _write(fd: int, holder: Holder, trigger: str) -> None:
        record = {"pid": holder.pid, "start": holder.start, "trigger": trigger, "started_at": _now()}
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, json.dumps(record).encode("utf-8"))
        os.fsync(fd)

    def _append(
        self, event: str, holder: Holder, trigger: str, *, count: int = 0, reason: str = ""
    ) -> None:
        row = {"event": event, "pid": holder.pid, "trigger": trigger, "at": _now(), "count": count}
        if reason:
            row["reason"] = reason
        self.runs_path.parent.mkdir(parents=True, exist_ok=True)
        with self.runs_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")


class _Flock:
    """An exclusive flock on the record file, taken within a bounded wait."""

    def __init__(self, path: Path, wait_seconds: float) -> None:
        self._path = path
        self._wait = wait_seconds
        self._fd = -1

    def __enter__(self) -> int:
        self._fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + self._wait
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self._fd
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(self._fd)
                    raise LockUnreadable(
                        f"could not read the run lock {self._path}: "
                        f"its flock stayed held past {self._wait}s"
                    ) from None
                time.sleep(_POLL_SECONDS)

    def __exit__(self, *exc: object) -> None:
        os.close(self._fd)

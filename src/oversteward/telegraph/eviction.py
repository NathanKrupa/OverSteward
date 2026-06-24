# ABOUTME: Single-instance eviction for the Telegraph operator — SIGTERM->poll->SIGKILL + reaper.
# ABOUTME: Pure algorithm over an injected ProcessControl; the real OS edge lives in the CLI.
"""Guarantee one operator session before the supervisor relaunches it.

When the supervisor decides the operator is deaf, a relaunch must not leave the
wedged poller alive: two pollers 409-fight over the same Telegram ``getUpdates``
long-poll and the new instance never receives. So before (re)launch we **evict**
the stale instance and **claim** a PID file (OverSteward #115, lifting the
claude-plugins-official #2229 eviction recipe).

Three pieces, all pure over an injected :class:`ProcessControl` so they unit-test
without touching real processes or signals:

  - :func:`evict_pid` — **SIGTERM, then poll ``kill(pid, 0)`` every
    ``poll_interval_s`` up to ``term_timeout_s``, then SIGKILL** if still alive.
    A wedged poller cannot process SIGTERM, so the escalation is mandatory.
  - :func:`is_orphaned_operator` — the **ancestor-walk** orphan reaper. It climbs
    the PPID chain: a chain that terminates at PID 1 is an orphan (kill); a chain
    that reaches a live ``claude`` process belongs to a real session (spare it,
    so concurrent sessions survive). A plain ``PPID == 1`` test misses the common
    case — the ``bun run`` wrapper outlives the session and reparents to init.
  - :func:`claim_single_instance` — write-and-own the PID file, evicting any live
    stale owner first.
"""

from __future__ import annotations

import signal
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ProcInfo:
    """A process's ancestry facts read in one shot: parent PID and command name."""

    ppid: int | None
    name: str


class ProcessControl(Protocol):
    """The OS edge: signal delivery, liveness polling, sleeping, ancestry."""

    def send_signal(self, pid: int, sig: int) -> None: ...
    def poll_alive(self, pid: int) -> bool: ...
    def sleep(self, seconds: float) -> None: ...
    def proc_info(self, pid: int) -> ProcInfo | None: ...


class EvictionResult(str, Enum):
    """Outcome of evicting a single PID."""

    ALREADY_GONE = "already_gone"  # the pid was not alive to begin with
    TERMINATED = "terminated"      # died on SIGTERM
    KILLED = "killed"              # survived SIGTERM, escalated to SIGKILL


@dataclass(frozen=True)
class EvictionConfig:
    """Eviction thresholds (injected; never globals)."""

    term_timeout_s: float = 3.0
    poll_interval_s: float = 0.1
    operator_cmd_substr: str = "claude"

    def __post_init__(self) -> None:
        if self.term_timeout_s < 0:
            raise ValueError("term_timeout_s must be >= 0")
        if self.poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")


def evict_pid(pid: int, proc: ProcessControl, cfg: EvictionConfig) -> EvictionResult:
    """SIGTERM ``pid``; poll up to ``term_timeout_s``; SIGKILL if still alive.

    A wedged poller ignores SIGTERM, so escalation to SIGKILL is mandatory. Runs
    synchronously — the caller relaunches only after this returns.
    """
    if not proc.poll_alive(pid):
        return EvictionResult.ALREADY_GONE

    proc.send_signal(pid, signal.SIGTERM)
    elapsed = 0.0
    while elapsed < cfg.term_timeout_s:
        proc.sleep(cfg.poll_interval_s)
        elapsed += cfg.poll_interval_s
        if not proc.poll_alive(pid):
            return EvictionResult.TERMINATED

    proc.send_signal(pid, signal.SIGKILL)
    return EvictionResult.KILLED


def is_orphaned_operator(pid: int, proc: ProcessControl, cfg: EvictionConfig) -> bool:
    """Climb the PPID chain: orphan (ends at PID 1) → ``True``; live ``claude``
    ancestor → ``False``.

    Cycle- and missing-parent-safe: a chain that loops or hits an unknown parent
    is treated as an orphan rather than spinning forever — the conservative call
    is to reap a process with no live session above it.
    """
    seen: set[int] = set()
    current: int | None = pid
    while current is not None and current != 1 and current not in seen:
        seen.add(current)
        info = proc.proc_info(current)
        if info is None or info.ppid is None:
            return True
        parent = info.ppid
        parent_info = proc.proc_info(parent)
        if (
            parent_info is not None
            and cfg.operator_cmd_substr in parent_info.name
            and proc.poll_alive(parent)
        ):
            return False
        current = parent
    return True


def _read_pid(pidfile: Path) -> int | None:
    """Read the recorded owner PID; ``None`` for a missing or corrupt file."""
    try:
        return int(pidfile.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def claim_single_instance(
    pidfile: Path, my_pid: int, proc: ProcessControl, cfg: EvictionConfig
) -> bool:
    """Evict any live stale owner, then write ``my_pid`` into ``pidfile``.

    Returns ``True`` once this process owns the file. The stale owner is evicted
    via :func:`evict_pid` (SIGTERM→SIGKILL); a dead or corrupt record is simply
    overwritten. Claiming our own already-recorded PID is a no-op signal-wise.
    """
    owner = _read_pid(pidfile)
    if owner is not None and owner != my_pid:
        evict_pid(owner, proc, cfg)
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.write_text(str(my_pid))
    return True

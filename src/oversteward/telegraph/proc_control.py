# ABOUTME: Inner connector — the real OS process edge for the Telegraph supervisor's eviction.
# ABOUTME: Talks only to signals + Linux /proc; satisfies the ProcessControl protocol.
"""The concrete :class:`ProcessControl` over POSIX signals and Linux ``/proc``.

This is the **inner edge** the eviction algorithm in :mod:`.eviction` is written
against. It owns exactly one external system — the local process table — and
holds no decision logic. The supervisor injects it; tests inject a fake instead,
so none of the SIGTERM/SIGKILL/ancestry logic ever needs a real process.

``/proc/<pid>/stat`` is the source for both the parent PID (field 4) and the
process name (field 2, parenthesised); using it avoids a psutil dependency in a
deploy area that must stay light.
"""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

from oversteward.telegraph.eviction import ProcInfo

_PROC = Path("/proc")
_log = logging.getLogger(__name__)


class PosixProcessControl:
    """``ProcessControl`` backed by POSIX signals and ``/proc`` (Linux)."""

    # pid is the OS-native process identity this connector relays to the kernel
    # (os.kill, /proc/<pid>); threading it is the connector's purpose, not a leak.
    def send_signal(self, pid: int, sig: int) -> None:  # noqa: CPLX-002
        """Deliver ``sig`` to ``pid``; a gone process is not an error."""
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            _log.debug("send_signal: pid %s already gone before signal %s", pid, sig)

    def poll_alive(self, pid: int) -> bool:
        """``kill(pid, 0)`` liveness probe; ``False`` once the process is gone."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # Exists but owned by another user — alive for our purposes.
            return True
        return True

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def proc_info(self, pid: int) -> ProcInfo | None:
        """Parent PID and command name from ``/proc/<pid>/stat`` in one read."""
        stat = self._read_stat(pid)
        if stat is None:
            return None
        name, ppid = stat
        return ProcInfo(ppid=int(ppid), name=name)

    @classmethod
    def _read_stat(cls, pid: int) -> tuple[str, str] | None:
        """Return ``(comm, ppid)`` from ``/proc/<pid>/stat`` or ``None`` if gone."""
        try:
            raw = (_PROC / str(pid) / "stat").read_text()
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            return None
        return cls._parse_stat(raw)

    @staticmethod
    def _parse_stat(raw: str) -> tuple[str, str] | None:
        """Parse a ``/proc/<pid>/stat`` line into ``(comm, ppid)``.

        ``comm`` is parenthesised and may itself contain spaces or ``)``; split
        on the last ``)`` so the field offsets after it stay correct. After the
        comm token the fields are ``state ppid pgrp ...``, so ppid is index 1.
        """
        rparen = raw.rfind(")")
        if rparen == -1:
            return None
        comm = raw[raw.find("(") + 1 : rparen]
        after = raw[rparen + 2 :].split()
        if len(after) < 2:
            return None
        return comm, after[1]


SIGTERM = signal.SIGTERM
SIGKILL = signal.SIGKILL

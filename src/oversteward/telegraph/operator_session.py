# ABOUTME: tmux-backed operator session edge + relaunch/adopt service for the supervisor.
# ABOUTME: A fixed-name detached tmux session gives a pty, survives restarts, and is single-instance.

"""Run + rescue the Telegraph operator inside a fixed-name detached tmux session.

The supervisor runs under systemd, where there is **no controlling terminal**.
``claude --channels …`` detects a non-interactive stdin and drops into
``--print`` mode, dying immediately — so a bare ``subprocess.Popen`` relaunch
never produces a working operator (OverSteward #120). The fix is to launch the
operator inside a **detached tmux session**: tmux allocates a pty (so claude runs
interactive), the tmux *server* keeps the session alive independently of
supervisor restarts and logout (linger), and a **fixed session name**
(``telegraph-operator``) gives single-instance for free — tmux refuses a
duplicate name, so a hand-started operator and the supervised one converge on one
canonical session.

This module is the **inner edge plus a thin service**:
  - :class:`SessionControl` — the process-control protocol the service is written
    against; unit tests inject a fake so no real tmux runs.
  - :class:`TmuxControl` — the concrete edge over ``/usr/bin/tmux`` (list-form
    argv, never a shell; the operator command is shell-quoted once via
    :func:`shlex.join` for tmux's own shell parse).
  - :func:`relaunch_operator` — evict the wedged session (``kill-session``) then
    recreate it (``new-session``). ``kill-session`` runs only when a session
    exists, so a cold start (no session) just creates one.
"""

from __future__ import annotations

import shlex
import subprocess  # list-form argv, never shell
from collections.abc import Callable
from typing import Protocol

DEFAULT_SESSION_NAME = "telegraph-operator"
_TMUX_BIN = "tmux"


class SessionControl(Protocol):
    """The process-control edge: presence, creation, and eviction of a session."""

    def has_session(self, name: str) -> bool: ...
    def start_session(self, name: str, command: list[str]) -> None: ...
    def kill_session(self, name: str) -> None: ...


class TmuxControl:
    """:class:`SessionControl` over a real ``tmux`` server (detached sessions)."""

    def __init__(
        self,
        *,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        tmux_bin: str = _TMUX_BIN,
    ):
        self._run = run
        self._tmux = tmux_bin

    def has_session(self, name: str) -> bool:
        """``tmux has-session -t <name>`` — alive iff it exits zero."""
        result = self._run(
            [self._tmux, "has-session", "-t", name],
            capture_output=True,
        )
        return result.returncode == 0

    def start_session(self, name: str, command: list[str]) -> None:
        """``tmux new-session -d -s <name> '<command>'`` — detached, pty-backed.

        The command list is shell-quoted into one string because tmux passes its
        final argument to a shell; quoting keeps multi-word arguments intact.
        """
        result = self._run(
            [self._tmux, "new-session", "-d", "-s", name, shlex.join(command)],
            capture_output=True,
        )
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", "replace").strip()
            raise RuntimeError(f"tmux new-session failed (rc={result.returncode}): {stderr}")

    def kill_session(self, name: str) -> None:
        """``tmux kill-session -t <name>`` — best-effort; a gone session is fine."""
        self._run(
            [self._tmux, "kill-session", "-t", name],
            capture_output=True,
        )


def relaunch_operator(session: SessionControl, name: str, command: list[str]) -> None:
    """Evict the named session if present, then (re)create it from ``command``.

    The fixed session name is the single-instance guarantee: there is at most one
    operator, whether Nathan started it by hand or the supervisor relaunched it.
    A cold start (no session yet) skips the eviction and just creates one.
    """
    if session.has_session(name):
        session.kill_session(name)
    session.start_session(name, command)

# ABOUTME: Tests for the tmux-backed operator session edge + relaunch/adopt service.
# ABOUTME: Fakes the process-control edge — no real tmux, no real processes, no network.

from __future__ import annotations

from types import SimpleNamespace

import pytest

from oversteward.telegraph.operator_session import (
    TmuxControl,
    relaunch_operator,
)


class _FakeRun:
    """Stand-in for ``subprocess.run`` that records argv and returns a rc."""

    def __init__(self, returncodes: dict[str, int] | None = None):
        self.calls: list[list[str]] = []
        self._returncodes = returncodes or {}

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        sub = argv[1] if len(argv) > 1 else ""
        return SimpleNamespace(returncode=self._returncodes.get(sub, 0), stdout=b"", stderr=b"")


class FakeSession:
    """In-memory ``SessionControl``: records kills/starts, tracks existence."""

    def __init__(self, exists: bool = False):
        self._exists = exists
        self.killed: list[str] = []
        self.started: list[tuple[str, list[str]]] = []

    def has_session(self, name: str) -> bool:
        return self._exists

    def kill_session(self, name: str) -> None:
        self.killed.append(name)
        self._exists = False

    def start_session(self, name: str, command: list[str]) -> None:
        self.started.append((name, list(command)))
        self._exists = True


# --- TmuxControl: argv construction (no real tmux) -------------------------


def test_start_session_builds_detached_named_argv():
    run = _FakeRun()
    TmuxControl(run=run).start_session("telegraph-operator", ["claude", "--channels", "x"])
    assert run.calls == [
        ["tmux", "new-session", "-d", "-s", "telegraph-operator", "claude --channels x"]
    ]


def test_start_session_shell_quotes_the_command():
    run = _FakeRun()
    TmuxControl(run=run).start_session("s", ["claude", "--prompt", "a b c"])
    # The command string is shell-quoted so spaces survive tmux's shell parse.
    assert run.calls[0][-1] == "claude --prompt 'a b c'"


def test_start_session_raises_when_tmux_fails():
    run = _FakeRun(returncodes={"new-session": 1})
    with pytest.raises(RuntimeError, match="new-session"):
        TmuxControl(run=run).start_session("s", ["claude"])


def test_has_session_true_on_zero_returncode():
    run = _FakeRun(returncodes={"has-session": 0})
    assert TmuxControl(run=run).has_session("s") is True
    assert run.calls == [["tmux", "has-session", "-t", "s"]]


def test_has_session_false_on_nonzero_returncode():
    run = _FakeRun(returncodes={"has-session": 1})
    assert TmuxControl(run=run).has_session("s") is False


def test_kill_session_builds_argv():
    run = _FakeRun()
    TmuxControl(run=run).kill_session("telegraph-operator")
    assert run.calls == [["tmux", "kill-session", "-t", "telegraph-operator"]]


# --- relaunch_operator: evict-then-recreate via the injected edge ----------


def test_relaunch_evicts_existing_session_then_recreates():
    session = FakeSession(exists=True)
    relaunch_operator(session, "telegraph-operator", ["claude", "--channels", "x"])
    assert session.killed == ["telegraph-operator"]
    assert session.started == [("telegraph-operator", ["claude", "--channels", "x"])]


def test_relaunch_when_no_session_only_starts():
    session = FakeSession(exists=False)
    relaunch_operator(session, "telegraph-operator", ["claude"])
    assert session.killed == []
    assert session.started == [("telegraph-operator", ["claude"])]

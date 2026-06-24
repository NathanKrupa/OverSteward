# ABOUTME: Tests for the Telegraph supervisor's single-instance eviction algorithm.
# ABOUTME: SIGTERM->poll->SIGKILL escalation, PID-file ownership, ancestor-walk orphan reaper.

from __future__ import annotations

import signal

import pytest

from oversteward.telegraph.eviction import (
    EvictionConfig,
    EvictionResult,
    ProcInfo,
    claim_single_instance,
    evict_pid,
    is_orphaned_operator,
)


class FakeProcessTable:
    """In-memory stand-in for the OS process table and signal delivery.

    ``alive`` maps pid -> remaining ``kill(pid, 0)`` polls before the process
    disappears; a deaf poller that ignores SIGTERM is modelled with a huge
    count. ``ppid`` and ``name`` describe the ancestry chain for the reaper.
    Each ``poll_alive`` decrements the countdown, modelling time passing.
    """

    def __init__(self):
        self.alive: dict[int, int] = {}
        self.ppid: dict[int, int] = {}
        self.name: dict[int, str] = {}
        self.signals: list[tuple[int, int]] = []
        self.sleeps: list[float] = []

    def send_signal(self, pid: int, sig: int) -> None:
        self.signals.append((pid, sig))
        if sig == signal.SIGKILL and pid in self.alive:
            self.alive[pid] = 0

    def poll_alive(self, pid: int) -> bool:
        remaining = self.alive.get(pid, 0)
        if remaining <= 0:
            return False
        self.alive[pid] = remaining - 1
        return True

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def proc_info(self, pid: int) -> ProcInfo | None:
        if pid not in self.ppid and pid not in self.name:
            return None
        return ProcInfo(ppid=self.ppid.get(pid), name=self.name.get(pid, ""))


def _cfg(**over) -> EvictionConfig:
    base = dict(term_timeout_s=3.0, poll_interval_s=0.1, operator_cmd_substr="claude")
    base.update(over)
    return EvictionConfig(**base)


# --- evict_pid: SIGTERM -> poll -> SIGKILL escalation ----------------------


def test_polite_process_dies_on_sigterm_without_sigkill():
    proc = FakeProcessTable()
    proc.alive[42] = 2  # survives the first two polls, then gone
    result = evict_pid(42, proc, _cfg())
    assert result == EvictionResult.TERMINATED
    assert (42, signal.SIGTERM) in proc.signals
    assert (42, signal.SIGKILL) not in proc.signals


def test_wedged_process_escalates_to_sigkill():
    proc = FakeProcessTable()
    proc.alive[42] = 10_000  # never dies on SIGTERM (deaf poller)
    result = evict_pid(42, proc, _cfg(term_timeout_s=0.3, poll_interval_s=0.1))
    assert result == EvictionResult.KILLED
    assert (42, signal.SIGTERM) in proc.signals
    assert (42, signal.SIGKILL) in proc.signals
    # Capped at ~term_timeout_s / poll_interval_s polls before escalating.
    assert len(proc.sleeps) <= 4


def test_evict_absent_pid_is_a_noop():
    proc = FakeProcessTable()
    result = evict_pid(999, proc, _cfg())
    assert result == EvictionResult.ALREADY_GONE
    assert proc.signals == []


# --- ancestor-walk orphan reaper -------------------------------------------


def test_chain_ending_at_pid1_is_orphan():
    proc = FakeProcessTable()
    # 500 -> 300 -> 1  (no live claude ancestor)
    proc.ppid = {500: 300, 300: 1}
    proc.name = {500: "node", 300: "bun"}
    assert is_orphaned_operator(500, proc, _cfg()) is True


def test_chain_reaching_live_claude_is_spared():
    proc = FakeProcessTable()
    # 500 -> 300 -> 200(claude) -> ...  a real session owns it
    proc.ppid = {500: 300, 300: 200, 200: 100}
    proc.name = {500: "node", 300: "bun", 200: "claude"}
    proc.alive = {200: 99}  # the claude ancestor is a live session
    assert is_orphaned_operator(500, proc, _cfg()) is False


def test_ppid_one_directly_is_orphan_not_missed_by_wrapper():
    # A plain PPID==1 check would catch this, but the wrapper case below would
    # be missed — both must resolve correctly.
    proc = FakeProcessTable()
    proc.ppid = {700: 1}
    proc.name = {700: "node"}
    assert is_orphaned_operator(700, proc, _cfg()) is True


def test_wrapper_outlives_session_chain_still_climbs_to_pid1():
    # The `bun run` wrapper outlives the session; PPID==1 would miss this.
    proc = FakeProcessTable()
    # 800 -> 600(bun wrapper) -> 1   (session gone, wrapper reparented to init)
    proc.ppid = {800: 600, 600: 1}
    proc.name = {800: "node", 600: "bun"}
    assert is_orphaned_operator(800, proc, _cfg()) is True


def test_reaper_terminates_on_missing_parent_without_infinite_loop():
    proc = FakeProcessTable()
    proc.ppid = {900: 850}  # 850 has no recorded parent -> chain ends
    proc.name = {900: "node"}
    assert is_orphaned_operator(900, proc, _cfg()) is True


def test_reaper_is_cycle_safe():
    proc = FakeProcessTable()
    proc.ppid = {10: 11, 11: 10}  # pathological cycle
    proc.name = {10: "node", 11: "node"}
    # Must terminate (treated as orphan) rather than spin forever.
    assert is_orphaned_operator(10, proc, _cfg()) is True


# --- claim_single_instance: PID-file ownership -----------------------------


def test_claim_when_no_pidfile_writes_own_pid(tmp_path):
    proc = FakeProcessTable()
    pidfile = tmp_path / "operator.pid"
    owned = claim_single_instance(pidfile, 1234, proc, _cfg())
    assert owned is True
    assert pidfile.read_text().strip() == "1234"
    assert proc.signals == []


def test_claim_evicts_live_stale_owner_then_takes_over(tmp_path):
    proc = FakeProcessTable()
    proc.alive[555] = 1  # stale owner alive, dies on SIGTERM
    pidfile = tmp_path / "operator.pid"
    pidfile.write_text("555")
    owned = claim_single_instance(pidfile, 1234, proc, _cfg())
    assert owned is True
    assert (555, signal.SIGTERM) in proc.signals
    assert pidfile.read_text().strip() == "1234"


def test_claim_over_dead_stale_pid_just_takes_over(tmp_path):
    proc = FakeProcessTable()  # 555 not alive
    pidfile = tmp_path / "operator.pid"
    pidfile.write_text("555")
    owned = claim_single_instance(pidfile, 1234, proc, _cfg())
    assert owned is True
    assert (555, signal.SIGKILL) not in proc.signals
    assert pidfile.read_text().strip() == "1234"


def test_claim_over_corrupt_pidfile_takes_over(tmp_path):
    proc = FakeProcessTable()
    pidfile = tmp_path / "operator.pid"
    pidfile.write_text("not-a-pid")
    owned = claim_single_instance(pidfile, 1234, proc, _cfg())
    assert owned is True
    assert pidfile.read_text().strip() == "1234"


def test_claim_is_idempotent_for_own_pid(tmp_path):
    proc = FakeProcessTable()
    proc.alive[1234] = 99
    pidfile = tmp_path / "operator.pid"
    pidfile.write_text("1234")
    owned = claim_single_instance(pidfile, 1234, proc, _cfg())
    assert owned is True
    # Never signals itself.
    assert proc.signals == []


# --- config guard ----------------------------------------------------------


def test_negative_timeout_rejected():
    with pytest.raises(ValueError, match="term_timeout_s"):
        _cfg(term_timeout_s=-1.0)

# ABOUTME: Tests for the Telegraph operator supervisor decision service (deaf-detector Shape 1).
# ABOUTME: Pure decision engine — detection fusion, four anti-flap guards, proactive recycle.

from __future__ import annotations

import pytest

from oversteward.telegraph.supervisor import (
    Action,
    Observation,
    SupervisorConfig,
    SupervisorState,
    decide,
    load_supervisor_state,
    reset_for_process_start,
    save_supervisor_state,
)


def _cfg(**over) -> SupervisorConfig:
    base = dict(
        poll_interval_s=15.0,
        hysteresis=2,
        cooldown_s=21600.0,
        startup_grace_s=30.0,
        restart_budget=3,
        restart_window_s=3600.0,
        max_idle_s=14400.0,
    )
    base.update(over)
    return SupervisorConfig(**base)


def _obs(now=1000.0, pending=0, heartbeat_ok=True) -> Observation:
    return Observation(now=now, pending_update_count=pending, heartbeat_ok=heartbeat_ok)


# --- startup-grace ---------------------------------------------------------


def test_within_startup_grace_suppresses_detection():
    cfg = _cfg()
    state = SupervisorState(launched_at=1000.0)
    # Bad pending AND failed heartbeat, but still inside the grace window.
    obs = _obs(now=1000.0 + cfg.startup_grace_s - 1, pending=5, heartbeat_ok=False)
    decision = decide(obs, state, cfg)
    assert decision.action == Action.NONE
    assert "grace" in decision.reason.lower()
    # Streak counters do not accumulate during grace.
    assert decision.state.pending_streak == 0
    assert decision.state.heartbeat_fail_streak == 0


# --- pending_update_count debounce (hysteresis) ----------------------------


def test_single_pending_probe_does_not_trip():
    cfg = _cfg(hysteresis=2)
    state = SupervisorState(launched_at=0.0)
    decision = decide(_obs(now=100.0, pending=3), state, cfg)
    assert decision.action == Action.NONE
    assert decision.state.pending_streak == 1


def test_two_consecutive_pending_probes_declare_deaf_and_relaunch():
    cfg = _cfg(hysteresis=2)
    state = SupervisorState(launched_at=0.0, pending_streak=1)
    decision = decide(_obs(now=100.0, pending=4), state, cfg)
    assert decision.action == Action.RELAUNCH
    assert "pending" in decision.reason.lower()


def test_drained_queue_resets_pending_streak():
    cfg = _cfg()
    state = SupervisorState(launched_at=0.0, pending_streak=1)
    decision = decide(_obs(now=100.0, pending=0), state, cfg)
    assert decision.state.pending_streak == 0


# --- heartbeat round-trip --------------------------------------------------


def test_heartbeat_failure_trips_even_when_queue_empty():
    # The core idle-wake bug: pending stays 0 but the round-trip never returns.
    cfg = _cfg(hysteresis=2)
    state = SupervisorState(launched_at=0.0, heartbeat_fail_streak=1)
    decision = decide(_obs(now=100.0, pending=0, heartbeat_ok=False), state, cfg)
    assert decision.action == Action.RELAUNCH
    assert "heartbeat" in decision.reason.lower()


def test_single_heartbeat_failure_does_not_trip():
    cfg = _cfg(hysteresis=2)
    state = SupervisorState(launched_at=0.0)
    decision = decide(_obs(now=100.0, heartbeat_ok=False), state, cfg)
    assert decision.action == Action.NONE
    assert decision.state.heartbeat_fail_streak == 1


def test_successful_heartbeat_resets_fail_streak():
    cfg = _cfg()
    state = SupervisorState(launched_at=0.0, heartbeat_fail_streak=1)
    decision = decide(_obs(now=100.0, heartbeat_ok=True), state, cfg)
    assert decision.state.heartbeat_fail_streak == 0


# --- cooldown ledger -------------------------------------------------------


def test_relaunch_within_cooldown_is_suppressed():
    cfg = _cfg(cooldown_s=21600.0, hysteresis=2)
    # A relaunch happened 1h ago; cooldown is 6h.
    state = SupervisorState(
        launched_at=0.0, pending_streak=1, last_relaunch_at=100.0 - 3600.0
    )
    decision = decide(_obs(now=100.0, pending=4), state, cfg)
    assert decision.action == Action.NONE
    assert "cooldown" in decision.reason.lower()


def test_relaunch_after_cooldown_elapsed_fires():
    cfg = _cfg(cooldown_s=3600.0, hysteresis=2)
    state = SupervisorState(
        launched_at=0.0, pending_streak=1, last_relaunch_at=100.0 - 7200.0
    )
    decision = decide(_obs(now=100.0, pending=4), state, cfg)
    assert decision.action == Action.RELAUNCH


# --- restart-loop-breaker --------------------------------------------------


def test_restart_budget_exhausted_alerts_instead_of_relaunching():
    cfg = _cfg(restart_budget=3, restart_window_s=3600.0, hysteresis=2, cooldown_s=0.0)
    # Three restarts already inside the window.
    now = 5000.0
    state = SupervisorState(
        launched_at=0.0,
        pending_streak=1,
        restart_timestamps=(now - 100.0, now - 200.0, now - 300.0),
    )
    decision = decide(_obs(now=now, pending=4), state, cfg)
    assert decision.action == Action.ALERT_LOOP
    assert "budget" in decision.reason.lower()
    # Does NOT record a new relaunch.
    assert len(decision.state.restart_timestamps) == 3


def test_old_restarts_outside_window_do_not_count_against_budget():
    cfg = _cfg(restart_budget=3, restart_window_s=3600.0, hysteresis=2, cooldown_s=0.0)
    now = 100000.0
    state = SupervisorState(
        launched_at=0.0,
        pending_streak=1,
        # All three are far older than the window.
        restart_timestamps=(10.0, 20.0, 30.0),
    )
    decision = decide(_obs(now=now, pending=4), state, cfg)
    assert decision.action == Action.RELAUNCH
    # The new relaunch is recorded; stale ones are pruned.
    assert now in decision.state.restart_timestamps
    assert 10.0 not in decision.state.restart_timestamps


def test_relaunch_records_timestamp_and_clears_streaks():
    cfg = _cfg(hysteresis=2, cooldown_s=0.0)
    state = SupervisorState(launched_at=0.0, pending_streak=1, heartbeat_fail_streak=1)
    decision = decide(_obs(now=900.0, pending=4), state, cfg)
    assert decision.action == Action.RELAUNCH
    assert decision.state.last_relaunch_at == 900.0
    assert 900.0 in decision.state.restart_timestamps
    assert decision.state.pending_streak == 0
    assert decision.state.heartbeat_fail_streak == 0


# --- proactive recycle (cheap hardening) -----------------------------------


def test_idle_uptime_past_max_triggers_proactive_recycle():
    cfg = _cfg(max_idle_s=14400.0, cooldown_s=0.0)
    now = 20000.0
    state = SupervisorState(launched_at=now - 14401.0)
    decision = decide(_obs(now=now, pending=0, heartbeat_ok=True), state, cfg)
    assert decision.action == Action.RECYCLE
    assert "uptime" in decision.reason.lower()


def test_healthy_young_session_is_left_alone():
    cfg = _cfg()
    state = SupervisorState(launched_at=900.0)
    decision = decide(_obs(now=2000.0, pending=0, heartbeat_ok=True), state, cfg)
    assert decision.action == Action.NONE


def test_deafness_takes_priority_over_proactive_recycle():
    # An old AND deaf session relaunches (deaf reason), not a polite recycle.
    cfg = _cfg(max_idle_s=14400.0, hysteresis=2, cooldown_s=0.0)
    now = 20000.0
    state = SupervisorState(launched_at=now - 99999.0, pending_streak=1)
    decision = decide(_obs(now=now, pending=4), state, cfg)
    assert decision.action == Action.RELAUNCH


def test_proactive_recycle_respects_cooldown():
    cfg = _cfg(max_idle_s=14400.0, cooldown_s=21600.0)
    now = 20000.0
    state = SupervisorState(launched_at=now - 14401.0, last_relaunch_at=now - 100.0)
    decision = decide(_obs(now=now, pending=0, heartbeat_ok=True), state, cfg)
    assert decision.action == Action.NONE


# --- process-start reset (cross-process vs cross-tick memory) --------------


def test_reset_clears_grace_anchor_and_streaks():
    stale = SupervisorState(
        launched_at=10.0,
        pending_streak=5,
        heartbeat_fail_streak=5,
    )
    fresh = reset_for_process_start(stale, now=1000.0)
    assert fresh.launched_at == 1000.0
    assert fresh.pending_streak == 0
    assert fresh.heartbeat_fail_streak == 0


def test_reset_preserves_the_cooldown_ledger():
    stale = SupervisorState(
        launched_at=10.0,
        heartbeat_fail_streak=9,
        last_relaunch_at=42.0,
        restart_timestamps=(40.0, 41.0),
    )
    fresh = reset_for_process_start(stale, now=1000.0)
    # The cooldown ledger survives a supervisor restart (crash-loop guard).
    assert fresh.last_relaunch_at == 42.0
    assert fresh.restart_timestamps == (40.0, 41.0)


def test_restart_with_stale_failures_does_not_relaunch_healthy_operator():
    # A prior dead run left spent grace + maxed streaks; the fresh process must
    # still get a clean grace window and not relaunch a now-healthy operator.
    cfg = _cfg(startup_grace_s=30.0, hysteresis=2)
    stale = SupervisorState(
        launched_at=10.0,
        pending_streak=9,
        heartbeat_fail_streak=9,
    )
    fresh = reset_for_process_start(stale, now=1000.0)
    decision = decide(_obs(now=1005.0, pending=0, heartbeat_ok=True), fresh, cfg)
    assert decision.action == Action.NONE
    assert "grace" in decision.reason.lower()


# --- config guard ----------------------------------------------------------


def test_hysteresis_below_one_is_rejected():
    with pytest.raises(ValueError, match="hysteresis"):
        _cfg(hysteresis=0)


def test_poll_interval_non_positive_is_rejected():
    with pytest.raises(ValueError, match="poll_interval_s"):
        _cfg(poll_interval_s=0.0)


# --- state persistence -----------------------------------------------------


def test_load_missing_state_seeds_launched_at(tmp_path):
    state = load_supervisor_state(tmp_path / "absent.json", default_launched_at=500.0)
    assert state == SupervisorState(launched_at=500.0)


def test_load_corrupt_state_seeds_launched_at(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    state = load_supervisor_state(p, default_launched_at=500.0)
    assert state.launched_at == 500.0


def test_state_roundtrips_through_disk(tmp_path):
    p = tmp_path / "nested" / "state.json"
    original = SupervisorState(
        launched_at=10.0,
        pending_streak=2,
        heartbeat_fail_streak=1,
        last_relaunch_at=9.0,
        restart_timestamps=(1.0, 2.0, 3.0),
    )
    save_supervisor_state(p, original)
    assert load_supervisor_state(p, default_launched_at=0.0) == original

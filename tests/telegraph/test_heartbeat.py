# ABOUTME: Tests for the heartbeat round-trip freshness check (the idle-wake-bug detector).
# ABOUTME: Pure freshness decision over an injected mtime reader; no real files or network.

from __future__ import annotations

from oversteward.telegraph.heartbeat import heartbeat_is_fresh


def test_fresh_when_operator_touched_after_sentinel_within_window():
    # sentinel sent at t=100; operator touched the file at t=103; now=105; window=10
    assert heartbeat_is_fresh(touched_at=103.0, sentinel_sent_at=100.0, now=105.0, window_s=10.0)


def test_stale_when_file_never_advanced_past_sentinel():
    # operator never processed inbound: last touch predates the sentinel send
    assert not heartbeat_is_fresh(touched_at=90.0, sentinel_sent_at=100.0, now=105.0, window_s=10.0)


def test_stale_when_round_trip_exceeds_window():
    # touched, but only after the window elapsed → counts as a miss
    assert not heartbeat_is_fresh(touched_at=121.0, sentinel_sent_at=100.0, now=125.0, window_s=10.0)


def test_missing_touch_is_stale():
    assert not heartbeat_is_fresh(touched_at=None, sentinel_sent_at=100.0, now=105.0, window_s=10.0)


def test_exactly_at_window_boundary_is_fresh():
    assert heartbeat_is_fresh(touched_at=110.0, sentinel_sent_at=100.0, now=111.0, window_s=10.0)

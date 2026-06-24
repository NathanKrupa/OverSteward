# ABOUTME: Heartbeat round-trip detector — catches the core idle-wake bug pending_count can't see.
# ABOUTME: Pure freshness decision + an inner edge that sends the sentinel and reads the touch file.
"""Prove the operator is still *receiving*, not just *connected*.

``getWebhookInfo().pending_update_count`` cannot see the core idle-wake defect
(claude-code #44380 / #36477): the queue drains but the session never wakes to
process the update. The only signal that catches it is a **round-trip**: the
supervisor sends a sentinel inbound message, and the operator — instrumented to
``touch`` a heartbeat file whenever it processes inbound — advances that file's
mtime. If the file does not advance past the sentinel send within a window, the
operator received nothing: deaf (OverSteward #115).

:func:`heartbeat_is_fresh` is the pure decision (injected timestamps, no IO).
:func:`probe_heartbeat` is the inner edge: it sends the sentinel via the Bot API
and reads the touch-file mtime. The operator-side instrumentation is documented
in the supervisor README.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path


def heartbeat_is_fresh(
    touched_at: float | None,
    sentinel_sent_at: float,
    now: float,
    window_s: float,
) -> bool:
    """True if the operator touched the heartbeat file after the sentinel, in time.

    Fresh means the touch (a) post-dates the sentinel send (the operator
    processed *this* probe, not a stale one) and (b) landed within ``window_s``
    of the send (the round-trip completed promptly).
    """
    if touched_at is None:
        return False
    if touched_at < sentinel_sent_at:
        return False
    return (touched_at - sentinel_sent_at) <= window_s


def read_touch_mtime(path: Path) -> float | None:
    """Heartbeat file mtime in epoch seconds, or ``None`` if it does not exist."""
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None


def probe_heartbeat(
    touch_file: Path,
    send_sentinel: Callable[[], None],
    *,
    wait: Callable[[float], None],
    now: Callable[[], float],
    window_s: float,
) -> bool:
    """Send the sentinel, wait for the round-trip window, report freshness.

    ``send_sentinel`` (Bot-API ``sendMessage`` of the sentinel text), ``wait``
    (sleep), and ``now`` (clock) are injected so the round-trip is testable
    without a network. Returns whether the operator processed the sentinel.
    """
    sent_at = now()
    send_sentinel()
    wait(window_s)
    touched = read_touch_mtime(touch_file)
    return heartbeat_is_fresh(touched, sent_at, now(), window_s)

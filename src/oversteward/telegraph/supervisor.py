# ABOUTME: Telegraph operator supervisor — the deaf-detector decision engine (Shape 1).
# ABOUTME: Pure state machine: fuse detection signals, apply anti-flap guards, emit one action.
"""Decide whether the always-on Telegraph operator session has gone deaf.

The operator (``claude --channels plugin:telegram``) intermittently goes **deaf
to inbound** — it stays alive and can still *send*, but stops *receiving*
Telegram messages. The cause is a cluster of still-open upstream defects
(claude-code ``--channels`` stdio #37482 / #40207 / #44380 / #36477, telegram
plugin #2229) whose core idle-wake variant is clearable **only by restart**. An
external supervisor is the only reliable fix (OverSteward #115).

This module is the **middle-layer service**: given one :class:`Observation` (what
the inner edges measured this tick), the carried :class:`SupervisorState`, and
the :class:`SupervisorConfig` thresholds, it returns the single next
:class:`Decision`. It performs **no** I/O — polling ``getWebhookInfo``, the
heartbeat round-trip, ``sendMessage``, and the relaunch/eviction are inner edges
the CLI supplies. Every clock value arrives as ``Observation.now`` (monotonic
seconds), so the whole engine is exhaustively testable without a network, real
time, or a real process.

Two detection signals feed the verdict, fused by OR:
  - **pending-update debounce** — ``getWebhookInfo().pending_update_count`` stays
    non-zero for ``hysteresis`` consecutive ticks (Hermes PR #42959 algorithm);
    Telegram is holding updates the poller is not draining.
  - **heartbeat round-trip** — a self-message that must round-trip to a visible
    reply fails for ``hysteresis`` consecutive ticks. ``pending_update_count``
    does **not** see the core idle-wake bug; the round-trip probe does.

Four anti-flap guards (logic shape lifted from gbrain restart-sweep /
supervisor) keep it from thrashing:
  - **startup-grace** — suppress the staleness clock for ``startup_grace_s``
    after each (re)launch, or every relaunch self-triggers.
  - **hysteresis** — ``hysteresis`` consecutive bad ticks before acting.
  - **cooldown ledger** — no second relaunch within ``cooldown_s``.
  - **restart-loop-breaker** — more than ``restart_budget`` relaunches inside
    ``restart_window_s`` → alert, do not loop.

Plus cheap hardening: a healthy session older than ``max_idle_s`` is recycled
proactively (uptime degrades the session — httpx pool / fd leak, session age).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path


class Action(str, Enum):
    """The single next thing the supervisor should do this tick."""

    NONE = "none"              # healthy, or a guard is suppressing action
    RELAUNCH = "relaunch"      # confirmed deaf → SIGKILL + relaunch the operator
    RECYCLE = "recycle"        # healthy but stale → proactive restart
    ALERT_LOOP = "alert_loop"  # restart budget spent → alert Nathan, do not loop


@dataclass(frozen=True)
class SupervisorConfig:
    """Thresholds for the decision engine (injected; never read from globals)."""

    poll_interval_s: float = 15.0
    hysteresis: int = 2
    cooldown_s: float = 21600.0        # 6h
    startup_grace_s: float = 30.0      # ~2x poll interval
    restart_budget: int = 3
    restart_window_s: float = 3600.0   # 1h
    max_idle_s: float = 14400.0        # 4h proactive recycle

    def __post_init__(self) -> None:
        if self.hysteresis < 1:
            raise ValueError("hysteresis must be >= 1")
        if self.poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")


@dataclass(frozen=True)
class SupervisorState:
    """Cross-tick memory carried between probes (persisted as JSON by the CLI)."""

    launched_at: float                                  # monotonic ts of last (re)launch
    pending_streak: int = 0                             # consecutive non-zero pending probes
    heartbeat_fail_streak: int = 0                      # consecutive heartbeat round-trip failures
    last_relaunch_at: float | None = None               # cooldown anchor
    restart_timestamps: tuple[float, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Observation:
    """What the inner edges measured this tick."""

    now: float                      # monotonic seconds
    pending_update_count: int = 0
    heartbeat_ok: bool = True


@dataclass(frozen=True)
class Decision:
    """The action to take plus the state to persist for the next tick."""

    action: Action
    reason: str
    state: SupervisorState


def _secs(value: float) -> str:
    """Render a duration as whole seconds for a reason string (e.g. ``"42s"``)."""
    return f"{value:.0f}s"


def _advance_streaks(obs: Observation, state: SupervisorState) -> SupervisorState:
    """Roll the two detection streaks forward from this tick's evidence."""
    pending = state.pending_streak + 1 if obs.pending_update_count > 0 else 0
    heartbeat = state.heartbeat_fail_streak + 1 if not obs.heartbeat_ok else 0
    return replace(state, pending_streak=pending, heartbeat_fail_streak=heartbeat)


def _deaf_reason(obs: Observation, state: SupervisorState, cfg: SupervisorConfig) -> str | None:
    """Return why the operator is deaf this tick, or ``None`` if it is responsive."""
    if state.pending_streak >= cfg.hysteresis:
        return (
            f"{obs.pending_update_count} update(s) pending across "
            f"{state.pending_streak} consecutive probes (>= hysteresis {cfg.hysteresis})"
        )
    if state.heartbeat_fail_streak >= cfg.hysteresis:
        return (
            f"heartbeat round-trip failed {state.heartbeat_fail_streak} consecutive "
            f"probes (>= hysteresis {cfg.hysteresis})"
        )
    return None


def _recent_restarts(state: SupervisorState, cfg: SupervisorConfig, now: float) -> tuple[float, ...]:
    """Restart timestamps still inside the loop-breaker window."""
    cutoff = now - cfg.restart_window_s
    return tuple(ts for ts in state.restart_timestamps if ts >= cutoff)


def _in_cooldown(state: SupervisorState, cfg: SupervisorConfig, now: float) -> bool:
    """True while a prior relaunch is still inside the cooldown ledger window."""
    if state.last_relaunch_at is None:
        return False
    return (now - state.last_relaunch_at) < cfg.cooldown_s


def _record_relaunch(state: SupervisorState, cfg: SupervisorConfig, now: float) -> SupervisorState:
    """Stamp a relaunch: anchor cooldown, prune+append the window, clear streaks."""
    recent = _recent_restarts(state, cfg, now)
    return replace(
        state,
        launched_at=now,
        last_relaunch_at=now,
        restart_timestamps=(*recent, now),
        pending_streak=0,
        heartbeat_fail_streak=0,
    )


def _handle_deaf(state: SupervisorState, cfg: SupervisorConfig, now: float, reason: str) -> Decision:
    """Apply the cooldown and loop-breaker guards to a confirmed-deaf verdict."""
    if _in_cooldown(state, cfg, now):
        elapsed = now - (state.last_relaunch_at or now)
        return Decision(Action.NONE, f"deaf ({reason}) but in cooldown ({_secs(elapsed)})", state)
    if len(_recent_restarts(state, cfg, now)) >= cfg.restart_budget:
        return Decision(
            Action.ALERT_LOOP,
            f"deaf ({reason}) but restart budget {cfg.restart_budget} spent in window",
            replace(state, restart_timestamps=_recent_restarts(state, cfg, now)),
        )
    return Decision(Action.RELAUNCH, f"deaf: {reason}", _record_relaunch(state, cfg, now))


def decide(obs: Observation, state: SupervisorState, cfg: SupervisorConfig) -> Decision:
    """Return the next :class:`Decision` from this tick's observation and prior state.

    Priority: startup-grace first (no detection yet), then a confirmed-deaf
    relaunch (subject to cooldown + loop-breaker), then a proactive uptime
    recycle (subject to cooldown), else nothing.
    """
    if (obs.now - state.launched_at) < cfg.startup_grace_s:
        return Decision(Action.NONE, "within startup grace window", state)

    advanced = _advance_streaks(obs, state)
    reason = _deaf_reason(obs, advanced, cfg)
    if reason is not None:
        return _handle_deaf(advanced, cfg, obs.now, reason)

    if (obs.now - advanced.launched_at) >= cfg.max_idle_s and not _in_cooldown(advanced, cfg, obs.now):
        age = obs.now - advanced.launched_at
        return Decision(
            Action.RECYCLE,
            f"proactive recycle: uptime {_secs(age)} >= max_idle {_secs(cfg.max_idle_s)}",
            _record_relaunch(advanced, cfg, obs.now),
        )

    return Decision(Action.NONE, "healthy", advanced)


# --- state persistence (carried between one-shot ticks) --------------------


def load_supervisor_state(path: Path, *, default_launched_at: float) -> SupervisorState:
    """Read the carried state; a missing or corrupt file starts fresh.

    ``default_launched_at`` seeds ``launched_at`` on a fresh start so the very
    first tick is inside the startup-grace window. The path is resolved before
    use so a ``..`` traversal cannot redirect the read.
    """
    resolved = Path(path).resolve()
    try:
        raw = json.loads(resolved.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return SupervisorState(launched_at=default_launched_at)
    return SupervisorState(
        launched_at=float(raw.get("launched_at", default_launched_at)),
        pending_streak=int(raw.get("pending_streak", 0)),
        heartbeat_fail_streak=int(raw.get("heartbeat_fail_streak", 0)),
        last_relaunch_at=(
            None if raw.get("last_relaunch_at") is None else float(raw["last_relaunch_at"])
        ),
        restart_timestamps=tuple(float(t) for t in raw.get("restart_timestamps", [])),
    )


def save_supervisor_state(path: Path, state: SupervisorState) -> None:
    """Persist the state for the next tick."""
    resolved = Path(path).resolve()
    data = asdict(state)
    data["restart_timestamps"] = list(state.restart_timestamps)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(data))

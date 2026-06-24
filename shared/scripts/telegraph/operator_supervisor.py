#!/usr/bin/env python3
# ABOUTME: The Telegraph operator supervisor CLI — external deaf-detector watchdog (Shape 1).
# ABOUTME: Operator-side only (NOT byte-copied); wires the oversteward decision service to real IO.
"""Supervise the always-on Telegraph operator session and rescue it when deaf.

This is the **thin outer entry point** for OverSteward #115. It runs *outside*
the operator session (an in-session watchdog cannot rescue a session whose own
code has stopped running) and supervises ``claude --channels plugin:telegram``.

It holds **no decision logic** — every judgement lives in the unit-tested
services:
  - :mod:`oversteward.telegraph.supervisor` — detection fusion + the four
    anti-flap guards + proactive recycle.
  - :mod:`oversteward.telegraph.eviction` — SIGTERM→SIGKILL eviction, PID-file
    single-instance, ancestor-walk orphan reaper.
  - :mod:`oversteward.telegraph.heartbeat` — the round-trip freshness probe.

This CLI only wires those services to real edges: the Telegram Bot API (reusing
``channel_watchdog``'s ``getWebhookInfo`` / ``sendMessage`` calls), the POSIX
``/proc`` process table (``PosixProcessControl``), the relaunch command, and the
JSON state file.

Unlike the portable relay primitives in this directory, this file is
**operator-side only** and is *not* byte-copied to sibling repos — it depends on
the ``oversteward`` package. Run it via the ``--user`` systemd unit
(``operator-supervisor.service``); see ``operator_supervisor.README.md``.

Credential hygiene: the bot token is read from the environment by the factory and
never printed.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess  # list-form argv, never shell
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from oversteward.telegraph.eviction import EvictionConfig, claim_single_instance
from oversteward.telegraph.heartbeat import probe_heartbeat
from oversteward.telegraph.proc_control import PosixProcessControl
from oversteward.telegraph.supervisor import (
    Action,
    Observation,
    SupervisorConfig,
    decide,
    load_supervisor_state,
    save_supervisor_state,
)

_CHANNEL_BASE = Path.home() / ".claude" / "channels" / "telegram"
_HEARTBEAT_SENTINEL = "​[telegraph-heartbeat]"  # zero-width-prefixed, low-noise


def _load_bot_api():
    """Load ``channel_watchdog``'s Bot-API helpers by path (no duplication)."""
    path = Path(__file__).resolve().parent / "channel_watchdog.py"
    spec = importlib.util.spec_from_file_location("channel_watchdog", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load channel_watchdog from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@dataclass(frozen=True)
class SupervisorSettings:
    """Everything the CLI needs, assembled by the factory from env + args."""

    token: str
    chat_id: str
    state_file: Path
    pid_file: Path
    heartbeat_file: Path
    relaunch_cmd: list[str]
    config: SupervisorConfig
    eviction: EvictionConfig
    heartbeat_window_s: float


def build_settings(args: argparse.Namespace, env: dict[str, str]) -> SupervisorSettings:
    """Factory: read the token from ``env`` (never printed), assemble settings."""
    token = env.get(args.token_env, "")
    if not token:
        raise ValueError(f"${args.token_env} is not set")
    return SupervisorSettings(
        token=token,
        chat_id=args.chat_id,
        state_file=Path(args.state_file),
        pid_file=Path(args.pid_file),
        heartbeat_file=Path(args.heartbeat_file),
        relaunch_cmd=args.relaunch_cmd,
        config=SupervisorConfig(
            poll_interval_s=args.poll_interval,
            hysteresis=args.hysteresis,
            cooldown_s=args.cooldown,
            startup_grace_s=args.startup_grace,
            restart_budget=args.restart_budget,
            restart_window_s=args.restart_window,
            max_idle_s=args.max_idle,
        ),
        eviction=EvictionConfig(
            term_timeout_s=args.term_timeout,
            poll_interval_s=args.evict_poll_interval,
            operator_cmd_substr=args.operator_cmd_substr,
        ),
        heartbeat_window_s=args.heartbeat_window,
    )


def _observe(settings: SupervisorSettings, bot_api, now: float) -> Observation:
    """Read both detection signals from the live edges into one Observation."""
    pending = bot_api.fetch_pending_update_count(settings.token)
    heartbeat_ok = probe_heartbeat(
        settings.heartbeat_file,
        send_sentinel=lambda: bot_api.send_alert(
            settings.token, settings.chat_id, _HEARTBEAT_SENTINEL
        ),
        wait=time.sleep,
        now=time.monotonic,
        window_s=settings.heartbeat_window_s,
    )
    return Observation(now=now, pending_update_count=pending, heartbeat_ok=heartbeat_ok)


def _act(action: Action, reason: str, settings: SupervisorSettings, bot_api, proc) -> None:
    """Carry out the supervisor's decision through the live edges.

    A relaunch/recycle evicts the wedged operator (single-instance ownership of
    the PID file) and then starts a fresh one; a spent restart budget alerts
    Nathan that manual intervention is needed.
    """
    if action in (Action.RELAUNCH, Action.RECYCLE):
        bot_api.send_alert(
            settings.token,
            settings.chat_id,
            f"\U0001f501 Telegraph supervisor: {action.value} — {reason}",
        )
        claim_single_instance(settings.pid_file, os.getpid(), proc, settings.eviction)
        subprocess.Popen(settings.relaunch_cmd, start_new_session=True)  # noqa: S603
    elif action == Action.ALERT_LOOP:
        bot_api.send_alert(
            settings.token,
            settings.chat_id,
            f"⚠️ Telegraph supervisor: restart budget spent — {reason}. "
            "Manual intervention needed.",
        )


def run_tick(settings: SupervisorSettings, bot_api, proc) -> str:
    """One supervision tick: observe, decide, act, persist. Returns the action."""
    now = time.monotonic()
    state = load_supervisor_state(settings.state_file, default_launched_at=now)
    obs = _observe(settings, bot_api, now)
    decision = decide(obs, state, settings.config)
    _act(decision.action, decision.reason, settings, bot_api, proc)
    save_supervisor_state(settings.state_file, decision.state)
    return f"{decision.action.value}: {decision.reason}"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Telegraph operator supervisor (deaf-detector Shape 1).")
    p.add_argument("--chat-id", required=True, help="Telegram chat id for alerts + heartbeat")
    p.add_argument("--relaunch-cmd", nargs=argparse.REMAINDER, default=None,
                   help="command to relaunch the operator (everything after this flag)")
    p.add_argument("--token-env", default="TELEGRAM_BOT_TOKEN")
    p.add_argument("--state-file", default=str(_CHANNEL_BASE / "supervisor_state.json"))
    p.add_argument("--pid-file", default=str(_CHANNEL_BASE / "operator.pid"))
    p.add_argument("--heartbeat-file", default=str(_CHANNEL_BASE / "operator_heartbeat"))
    p.add_argument("--poll-interval", type=float, default=15.0)
    p.add_argument("--hysteresis", type=int, default=2)
    p.add_argument("--cooldown", type=float, default=21600.0)
    p.add_argument("--startup-grace", type=float, default=30.0)
    p.add_argument("--restart-budget", type=int, default=3)
    p.add_argument("--restart-window", type=float, default=3600.0)
    p.add_argument("--max-idle", type=float, default=14400.0)
    p.add_argument("--term-timeout", type=float, default=3.0)
    p.add_argument("--evict-poll-interval", type=float, default=0.1)
    p.add_argument("--operator-cmd-substr", default="claude")
    p.add_argument("--heartbeat-window", type=float, default=8.0)
    p.add_argument("--loop", action="store_true", help="run continuously (else a single tick)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.relaunch_cmd:
        sys.stderr.write("supervisor: --relaunch-cmd <command...> is required\n")
        return 2
    try:
        settings = build_settings(args, dict(os.environ))
    except ValueError as exc:
        sys.stderr.write(f"supervisor: {exc}\n")
        return 2

    bot_api = _load_bot_api()
    proc = PosixProcessControl()
    runner: Callable[[], str] = lambda: run_tick(settings, bot_api, proc)
    if not args.loop:
        print(runner())
        return 0
    while True:
        try:
            print(runner())
        except (RuntimeError, OSError) as exc:
            sys.stderr.write(f"supervisor: tick failed: {exc}\n")
        time.sleep(settings.config.poll_interval_s)


if __name__ == "__main__":
    sys.exit(main())

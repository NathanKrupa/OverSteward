# ABOUTME: Tests for the operator supervisor CLI wiring (factory + tick flow with fakes).
# ABOUTME: No live Telegram, no real token, no real tmux — every edge is injected/faked.

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

from oversteward.telegraph.supervisor import SupervisorState, save_supervisor_state

# A fixed wall-clock epoch the tick tests pin time.time() to, so the heartbeat
# round-trip (judged against the touch file's wall-clock mtime) is deterministic.
_FIXED_NOW = 1_700_000_000.0


def _load_cli():
    rel = Path("shared") / "scripts" / "telegraph" / "operator_supervisor.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("operator_supervisor", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod
    raise AssertionError(f"could not locate {rel}")


cli = _load_cli()


def _args(**over) -> argparse.Namespace:
    base = dict(
        chat_id="123",
        relaunch_cmd=["claude", "--channels", "plugin:telegram"],
        token_env="TELEGRAM_BOT_TOKEN",
        state_file="/tmp/x/state.json",
        heartbeat_file="/tmp/x/hb",
        session_name="telegraph-operator",
        poll_interval=15.0,
        hysteresis=2,
        cooldown=21600.0,
        startup_grace=30.0,
        restart_budget=3,
        restart_window=3600.0,
        max_idle=14400.0,
        heartbeat_window=8.0,
    )
    base.update(over)
    return argparse.Namespace(**base)


class _FakeBotApi:
    """Stand-in for channel_watchdog's Bot-API helpers."""

    def __init__(self, pending: int, heartbeat_touches: bool):
        self.pending = pending
        self.heartbeat_touches = heartbeat_touches
        self.alerts: list[str] = []
        self.sends: list[tuple[str, bool]] = []  # (text, silent) for every send_alert
        self.deleted: list[int] = []
        self._next_message_id = 1000
        self._hb_path: Path | None = None

    def fetch_pending_update_count(self, token: str) -> int:
        return self.pending

    def send_alert(self, token: str, chat_id: str, text: str, *, silent: bool = False) -> int:
        self.alerts.append(text)
        self.sends.append((text, silent))
        # Model a responsive operator: receiving the sentinel touches the file
        # with a fresh (wall-clock) mtime, completing the round-trip. The mtime is
        # pinned to the patched clock so freshness is deterministic on any fs.
        if self.heartbeat_touches and self._hb_path is not None:
            self._hb_path.write_text("beat")
            stamp = time.time()
            os.utime(self._hb_path, (stamp, stamp))
        self._next_message_id += 1
        return self._next_message_id

    def delete_message(self, token: str, chat_id: str, message_id: int) -> None:
        self.deleted.append(message_id)


class _FakeSession:
    """In-memory ``SessionControl`` — records evict/start, no real tmux."""

    def __init__(self, exists: bool = False):
        self._exists = exists
        self.killed: list[str] = []
        self.started: list[tuple[str, list[str]]] = []

    def has_session(self, name):
        return self._exists

    def kill_session(self, name):
        self.killed.append(name)
        self._exists = False

    def start_session(self, name, command):
        self.started.append((name, list(command)))
        self._exists = True


# --- factory: credential hygiene -------------------------------------------


def test_factory_reads_token_from_env():
    settings = cli.build_settings(_args(), {"TELEGRAM_BOT_TOKEN": "SECRET"})
    assert settings.token == "SECRET"
    assert settings.chat_id == "123"
    assert settings.config.hysteresis == 2
    assert settings.session_name == "telegraph-operator"


def test_factory_raises_when_token_absent():
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        cli.build_settings(_args(), {})


def test_factory_never_puts_token_in_repr():
    settings = cli.build_settings(_args(), {"TELEGRAM_BOT_TOKEN": "SECRET"})
    assert "SECRET" not in repr(settings.config)


# --- run_tick flow ---------------------------------------------------------


def test_tick_healthy_does_not_alert_or_relaunch(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: _FIXED_NOW)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    settings = cli.build_settings(
        _args(
            state_file=str(tmp_path / "state.json"),
            heartbeat_file=str(tmp_path / "hb"),
            startup_grace=0.0,
        ),
        {"TELEGRAM_BOT_TOKEN": "SECRET"},
    )
    bot = _FakeBotApi(pending=0, heartbeat_touches=True)
    bot._hb_path = tmp_path / "hb"
    session = _FakeSession(exists=True)
    result = cli.run_tick(settings, bot, session)
    assert result.startswith("none")
    assert session.started == []  # healthy → never relaunched
    assert all("supervisor:" not in a for a in bot.alerts)


def test_tick_deletes_its_own_heartbeat_sentinel(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: _FIXED_NOW)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    settings = cli.build_settings(
        _args(
            state_file=str(tmp_path / "state.json"),
            heartbeat_file=str(tmp_path / "hb"),
            startup_grace=0.0,
        ),
        {"TELEGRAM_BOT_TOKEN": "SECRET"},
    )
    bot = _FakeBotApi(pending=0, heartbeat_touches=True)
    bot._hb_path = tmp_path / "hb"
    session = _FakeSession(exists=True)
    cli.run_tick(settings, bot, session)
    # The probe sent the sentinel and then deleted it (silent in the chat).
    assert bot.deleted, "heartbeat sentinel was never deleted"
    assert bot.deleted[-1] in range(1001, 100000)


def test_tick_deaf_pending_relaunches_via_tmux(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: _FIXED_NOW)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    settings = cli.build_settings(
        _args(
            state_file=str(tmp_path / "state.json"),
            heartbeat_file=str(tmp_path / "hb"),
            startup_grace=0.0,
            hysteresis=1,  # trip on the first bad probe
        ),
        {"TELEGRAM_BOT_TOKEN": "SECRET"},
    )
    bot = _FakeBotApi(pending=5, heartbeat_touches=True)
    bot._hb_path = tmp_path / "hb"
    session = _FakeSession(exists=True)
    result = cli.run_tick(settings, bot, session)
    assert result.startswith("relaunch")
    # Evicted the wedged session, then recreated the canonical one.
    assert session.killed == ["telegraph-operator"]
    assert session.started == [("telegraph-operator", settings.relaunch_cmd)]
    assert any("relaunch" in a for a in bot.alerts)


def test_tick_persists_state_between_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: _FIXED_NOW)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    settings = cli.build_settings(
        _args(
            state_file=str(tmp_path / "state.json"),
            heartbeat_file=str(tmp_path / "hb"),
            startup_grace=0.0,
            hysteresis=2,
        ),
        {"TELEGRAM_BOT_TOKEN": "SECRET"},
    )
    bot = _FakeBotApi(pending=5, heartbeat_touches=True)
    bot._hb_path = tmp_path / "hb"
    session = _FakeSession(exists=True)
    first = cli.run_tick(settings, bot, session)
    assert first.startswith("none")  # streak 1/2
    assert (tmp_path / "state.json").exists()


# --- process-start boot reset (bug 3) --------------------------------------


def test_boot_resets_stale_grace_but_keeps_cooldown(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: 5000.0)
    save_supervisor_state(
        tmp_path / "state.json",
        SupervisorState(
            launched_at=1.0,
            pending_streak=9,
            heartbeat_fail_streak=9,
            last_relaunch_at=42.0,
            restart_timestamps=(40.0, 41.0),
        ),
    )
    settings = cli.build_settings(
        _args(state_file=str(tmp_path / "state.json")),
        {"TELEGRAM_BOT_TOKEN": "SECRET"},
    )
    booted = cli._boot(settings)
    assert booted.launched_at == 5000.0
    assert booted.pending_streak == 0
    assert booted.heartbeat_fail_streak == 0
    # Cooldown ledger survives the restart.
    assert booted.last_relaunch_at == 42.0
    assert booted.restart_timestamps == (40.0, 41.0)


# --- buzz fix: the heartbeat sentinel is silent, real alerts notify (bug A) ---


def test_heartbeat_sentinel_is_sent_silently(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: _FIXED_NOW)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    settings = cli.build_settings(
        _args(
            state_file=str(tmp_path / "state.json"),
            heartbeat_file=str(tmp_path / "hb"),
            startup_grace=0.0,
        ),
        {"TELEGRAM_BOT_TOKEN": "SECRET"},
    )
    bot = _FakeBotApi(pending=0, heartbeat_touches=True)
    bot._hb_path = tmp_path / "hb"
    session = _FakeSession(exists=True)
    cli.run_tick(settings, bot, session)
    # Exactly one send this healthy tick: the sentinel, and it went out silent
    # (disable_notification) so it never buzzes Nathan's phone.
    assert bot.sends == [(cli._HEARTBEAT_SENTINEL, True)]


def test_real_relaunch_alert_notifies(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: _FIXED_NOW)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    settings = cli.build_settings(
        _args(
            state_file=str(tmp_path / "state.json"),
            heartbeat_file=str(tmp_path / "hb"),
            startup_grace=0.0,
            hysteresis=1,
        ),
        {"TELEGRAM_BOT_TOKEN": "SECRET"},
    )
    bot = _FakeBotApi(pending=5, heartbeat_touches=True)
    bot._hb_path = tmp_path / "hb"
    session = _FakeSession(exists=True)
    cli.run_tick(settings, bot, session)
    # The sentinel is silent; the relaunch alert is NOT (a real, rare event).
    silent_by_text = dict(bot.sends)
    assert silent_by_text[cli._HEARTBEAT_SENTINEL] is True
    relaunch_alerts = [(t, s) for (t, s) in bot.sends if "relaunch" in t]
    assert relaunch_alerts and all(s is False for _, s in relaunch_alerts)


# --- relaunch target is the real session + full command, not "none"/truncated (bug C) ---


def test_relaunch_uses_full_command_and_real_session_name(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: _FIXED_NOW)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    full_cmd = ["claude", "--channels", "plugin:telegram@claude-plugins-official"]
    settings = cli.build_settings(
        _args(
            state_file=str(tmp_path / "state.json"),
            heartbeat_file=str(tmp_path / "hb"),
            startup_grace=0.0,
            hysteresis=1,
            session_name="telegraph-operator",
            relaunch_cmd=full_cmd,
        ),
        {"TELEGRAM_BOT_TOKEN": "SECRET"},
    )
    bot = _FakeBotApi(pending=5, heartbeat_touches=True)
    bot._hb_path = tmp_path / "hb"
    session = _FakeSession(exists=True)
    cli.run_tick(settings, bot, session)
    assert session.started == [("telegraph-operator", full_cmd)]
    started_name, started_cmd = session.started[0]
    assert started_name != "none"  # not the stale default-session bug
    assert started_cmd == full_cmd  # full command, not truncated to ["claude"]


def test_remainder_parsing_captures_whole_relaunch_command():
    # argparse REMAINDER must keep every token after --relaunch-cmd, including
    # the operator's own flags, rather than swallowing only the first word.
    args = cli._build_parser().parse_args(
        [
            "--chat-id", "1",
            "--session-name", "telegraph-operator",
            "--relaunch-cmd", "claude", "--channels", "plugin:telegram@claude-plugins-official",
        ]
    )
    assert args.session_name == "telegraph-operator"
    assert args.relaunch_cmd == [
        "claude", "--channels", "plugin:telegram@claude-plugins-official",
    ]


# --- log rate-limiting so a stuck state can't flood journald (bug D) ---


def test_changed_line_always_emits():
    assert cli._should_emit("relaunch: deaf", "none: healthy", 0)


def test_identical_line_suppressed_between_intervals():
    # Same line repeating: emit on the boundary, suppress in between.
    assert not cli._should_emit("none: in cooldown", "none: in cooldown", 1, every=40)
    assert not cli._should_emit("none: in cooldown", "none: in cooldown", 39, every=40)
    assert cli._should_emit("none: in cooldown", "none: in cooldown", 40, every=40)


# --- arg parsing -----------------------------------------------------------


def test_main_requires_relaunch_cmd(capsys):
    rc = cli.main(["--chat-id", "1"])
    assert rc == 2
    assert "relaunch-cmd" in capsys.readouterr().err

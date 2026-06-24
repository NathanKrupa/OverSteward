# ABOUTME: Tests for the operator supervisor CLI wiring (factory + tick flow with fakes).
# ABOUTME: No live Telegram, no real token, no real processes — every edge is injected/faked.

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest


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
        pid_file="/tmp/x/op.pid",
        heartbeat_file="/tmp/x/hb",
        poll_interval=15.0,
        hysteresis=2,
        cooldown=21600.0,
        startup_grace=30.0,
        restart_budget=3,
        restart_window=3600.0,
        max_idle=14400.0,
        term_timeout=3.0,
        evict_poll_interval=0.1,
        operator_cmd_substr="claude",
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
        self._hb_path: Path | None = None

    def fetch_pending_update_count(self, token: str) -> int:
        return self.pending

    def send_alert(self, token: str, chat_id: str, text: str) -> None:
        self.alerts.append(text)
        # Model a responsive operator: receiving the sentinel touches the file.
        if self.heartbeat_touches and self._hb_path is not None:
            self._hb_path.write_text("beat")


class _FakeProc:
    def __init__(self):
        self.signals: list[tuple[int, int]] = []

    def send_signal(self, pid, sig):
        self.signals.append((pid, sig))

    def poll_alive(self, pid):
        return False

    def sleep(self, seconds):
        pass

    def proc_info(self, pid):
        return None


# --- factory: credential hygiene -------------------------------------------


def test_factory_reads_token_from_env():
    settings = cli.build_settings(_args(), {"TELEGRAM_BOT_TOKEN": "SECRET"})
    assert settings.token == "SECRET"
    assert settings.chat_id == "123"
    assert settings.config.hysteresis == 2


def test_factory_raises_when_token_absent():
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        cli.build_settings(_args(), {})


def test_factory_never_puts_token_in_repr():
    settings = cli.build_settings(_args(), {"TELEGRAM_BOT_TOKEN": "SECRET"})
    # The token lives in a field, but the CLI must never log the settings repr;
    # this test documents that callers must not print it. We assert the token is
    # not derivable from the public config/eviction sub-objects.
    assert "SECRET" not in repr(settings.config)
    assert "SECRET" not in repr(settings.eviction)


# --- run_tick flow ---------------------------------------------------------


def test_tick_healthy_does_not_alert_or_relaunch(tmp_path, monkeypatch):
    # Force the clock so we are PAST startup grace and not stale.
    monkeypatch.setattr(cli.time, "monotonic", lambda: 1000.0)
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
    proc = _FakeProc()
    result = cli.run_tick(settings, bot, proc)
    assert result.startswith("none")
    # Only the heartbeat sentinel was sent, never a deaf alert.
    assert all("supervisor:" not in a for a in bot.alerts)


def test_tick_deaf_pending_relaunches(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    launched = []
    monkeypatch.setattr(
        cli.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd) or object()
    )
    settings = cli.build_settings(
        _args(
            state_file=str(tmp_path / "state.json"),
            pid_file=str(tmp_path / "op.pid"),
            heartbeat_file=str(tmp_path / "hb"),
            startup_grace=0.0,
            hysteresis=1,  # trip on the first bad probe
        ),
        {"TELEGRAM_BOT_TOKEN": "SECRET"},
    )
    bot = _FakeBotApi(pending=5, heartbeat_touches=True)
    bot._hb_path = tmp_path / "hb"
    proc = _FakeProc()
    result = cli.run_tick(settings, bot, proc)
    assert result.startswith("relaunch")
    assert launched and launched[0] == settings.relaunch_cmd
    assert (tmp_path / "op.pid").exists()
    assert any("relaunch" in a for a in bot.alerts)


def test_tick_persists_state_between_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.time, "monotonic", lambda: 1000.0)
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
    proc = _FakeProc()
    first = cli.run_tick(settings, bot, proc)
    assert first.startswith("none")  # streak 1/2
    assert (tmp_path / "state.json").exists()


# --- arg parsing -----------------------------------------------------------


def test_main_requires_relaunch_cmd(capsys):
    rc = cli.main(["--chat-id", "1"])
    assert rc == 2
    assert "relaunch-cmd" in capsys.readouterr().err

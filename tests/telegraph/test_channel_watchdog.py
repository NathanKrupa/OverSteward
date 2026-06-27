# ABOUTME: Tests for the Telegraph channel watchdog — the getWebhookInfo deaf-detector.
# ABOUTME: Pure health-assessment truth table + state roundtrip + probe flow with injected IO.

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_watchdog():
    """Load the canonical shared script by file path (no install needed)."""
    rel = Path("shared") / "scripts" / "telegraph" / "channel_watchdog.py"
    for parent in Path(__file__).resolve().parents:
        candidate = parent / rel
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("channel_watchdog", candidate)
            assert spec and spec.loader
            mod = importlib.util.module_from_spec(spec)
            # Register before exec: the module defines dataclasses, and under
            # `from __future__ import annotations` dataclass type resolution
            # looks the module up in sys.modules.
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            return mod
    raise AssertionError(f"could not locate {rel}")


wd = _load_watchdog()


# --- assess_channel_health: the deaf-detector truth table ------------------


def test_drained_queue_is_healthy_and_resets_state():
    prior = wd.WatchState(consecutive_pending=3, already_alerted=True)
    verdict = wd.assess_channel_health(0, prior)
    assert verdict.status == "healthy"
    assert verdict.should_alert is False
    assert verdict.state == wd.WatchState(consecutive_pending=0, already_alerted=False)


def test_first_pending_probe_is_degraded_not_yet_alerting():
    verdict = wd.assess_channel_health(2, wd.WatchState(), threshold=2)
    assert verdict.status == "degraded"
    assert verdict.should_alert is False
    assert verdict.state == wd.WatchState(consecutive_pending=1, already_alerted=False)


def test_threshold_crossing_declares_wedged_and_alerts_once():
    prior = wd.WatchState(consecutive_pending=1, already_alerted=False)
    verdict = wd.assess_channel_health(2, prior, threshold=2)
    assert verdict.status == "wedged"
    assert verdict.should_alert is True
    assert verdict.state == wd.WatchState(consecutive_pending=2, already_alerted=True)


def test_wedged_does_not_re_alert_while_already_alerted():
    prior = wd.WatchState(consecutive_pending=2, already_alerted=True)
    verdict = wd.assess_channel_health(5, prior, threshold=2)
    assert verdict.status == "wedged"
    assert verdict.should_alert is False
    assert verdict.state.consecutive_pending == 3
    assert verdict.state.already_alerted is True


def test_recovery_after_wedged_resets_alert_latch():
    prior = wd.WatchState(consecutive_pending=4, already_alerted=True)
    verdict = wd.assess_channel_health(0, prior)
    assert verdict.status == "healthy"
    assert verdict.state.already_alerted is False


def test_threshold_one_alerts_on_first_pending():
    verdict = wd.assess_channel_health(1, wd.WatchState(), threshold=1)
    assert verdict.status == "wedged"
    assert verdict.should_alert is True


# --- state persistence -----------------------------------------------------


def test_load_state_missing_file_returns_default(tmp_path):
    assert wd.load_state(tmp_path / "absent.json") == wd.WatchState()


def test_load_state_corrupt_file_returns_default(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    assert wd.load_state(p) == wd.WatchState()


def test_save_then_load_roundtrips(tmp_path):
    p = tmp_path / "state.json"
    wd.save_state(p, wd.WatchState(consecutive_pending=2, already_alerted=True))
    assert wd.load_state(p) == wd.WatchState(consecutive_pending=2, already_alerted=True)
    assert json.loads(p.read_text())["consecutive_pending"] == 2


# --- resolve_state_path confinement ---------------------------------------


def test_resolve_state_path_accepts_path_within_base(tmp_path):
    resolved = wd.resolve_state_path(tmp_path / "watchdog_state.json", base=tmp_path)
    assert resolved == (tmp_path / "watchdog_state.json").resolve()


def test_resolve_state_path_rejects_escape(tmp_path):
    import pytest

    with pytest.raises(ValueError, match="escapes allowed base"):
        wd.resolve_state_path(tmp_path / ".." / "elsewhere.json", base=tmp_path)


# --- run_probe flow with injected IO --------------------------------------


def test_run_probe_alerts_on_wedged_transition():
    alerts: list[str] = []
    verdict = wd.run_probe(
        token="t",
        chat_id="123",
        state=wd.WatchState(consecutive_pending=1, already_alerted=False),
        threshold=2,
        fetch=lambda: 4,
        alert=alerts.append,
    )
    assert verdict.status == "wedged"
    assert len(alerts) == 1
    assert "4" in alerts[0]


def test_run_probe_silent_when_healthy():
    alerts: list[str] = []
    verdict = wd.run_probe(
        token="t",
        chat_id="123",
        state=wd.WatchState(),
        threshold=2,
        fetch=lambda: 0,
        alert=alerts.append,
    )
    assert verdict.status == "healthy"
    assert alerts == []


# --- IO parsing (injected urlopen) ----------------------------------------


class _FakeResp:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_pending_update_count_reads_webhook_info():
    captured = {}

    def fake_urlopen(url, timeout=0):
        captured["url"] = url
        return _FakeResp({"ok": True, "result": {"pending_update_count": 7}})

    assert wd.fetch_pending_update_count("SECRET", urlopen=fake_urlopen) == 7
    assert captured["url"].endswith("/botSECRET/getWebhookInfo")


def test_fetch_pending_update_count_raises_on_not_ok():
    def fake_urlopen(url, timeout=0):
        return _FakeResp({"ok": False, "description": "unauthorized"})

    try:
        wd.fetch_pending_update_count("SECRET", urlopen=fake_urlopen)
    except RuntimeError as exc:
        assert "unauthorized" in str(exc)
    else:
        raise AssertionError("expected RuntimeError on ok=false")


def test_send_alert_returns_message_id_from_response():
    def fake_urlopen(req, timeout=0):
        return _FakeResp({"ok": True, "result": {"message_id": 4242}})

    message_id = wd.send_alert("SECRET", "123", "hi", urlopen=fake_urlopen)
    assert message_id == 4242


def test_send_alert_returns_none_when_response_omits_message_id():
    def fake_urlopen(req, timeout=0):
        return _FakeResp({"ok": True, "result": {}})

    assert wd.send_alert("SECRET", "123", "hi", urlopen=fake_urlopen) is None


def test_delete_message_posts_chat_and_message_id():
    captured = {}

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return _FakeResp({"ok": True, "result": True})

    wd.delete_message("SECRET", "123", 4242, urlopen=fake_urlopen)
    assert captured["url"].endswith("/botSECRET/deleteMessage")
    assert b"4242" in captured["data"]
    assert b"123" in captured["data"]

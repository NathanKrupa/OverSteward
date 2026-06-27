#!/usr/bin/env python3
# ABOUTME: The Telegraph's channel watchdog — detect a deaf operator session and ring the bell.
# ABOUTME: Canonical in OverSteward shared/scripts/telegraph/; stdlib-only, Bot-API-backed.
"""Detect a wedged Telegram poller and alert Nathan out-of-band.

A Telegraph operator session can go **deaf to inbound** while staying alive and
able to send: the poller wedges, or Claude Code's MCP transport stops delivering
events (anthropics/claude-code #36411 / #37482 / #40207). Telegram keeps the
messages queued; the session never sees them. Outbound still works — which is
exactly the lever this watchdog pulls.

Design borrowed from the Hermes harness (NousResearch/hermes-agent):
- **#42909 / PR #42959** — the deaf-detector: poll ``getWebhookInfo``'s
  ``pending_update_count``. If it stays > 0 across consecutive probes, Telegram
  has updates the poller is not draining → wedged.
- **#40199** — "connected" is not "receiving"; act on queue evidence, not
  process liveness.

Run it as a one-shot (cron / ``/loop``); a small JSON state file carries the
consecutive-pending count and an alert latch between runs, so the alert fires
once on the transition into "wedged", not on every probe.

Pure assessment is split from the Bot-API IO so the decision logic is
unit-tested without a network. Stdlib-only by design: this file is byte-copied
to repos that do not have the ``oversteward`` package installed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_THRESHOLD = 2
API_BASE = "https://api.telegram.org"
_TIMEOUT_S = 15


@dataclass(frozen=True)
class WatchState:
    """Cross-probe memory: how many consecutive probes saw a non-empty queue,
    and whether we have already rung the bell for the current wedge."""

    consecutive_pending: int = 0
    already_alerted: bool = False


@dataclass(frozen=True)
class HealthVerdict:
    """Outcome of one probe: a status, whether to alert now, why, and the
    ``WatchState`` to persist for the next probe."""

    status: str  # "healthy" | "degraded" | "wedged"
    should_alert: bool
    reason: str
    state: WatchState


def assess_channel_health(
    pending_update_count: int,
    state: WatchState,
    threshold: int = DEFAULT_THRESHOLD,
) -> HealthVerdict:
    """Decide channel health from the pending-update count and prior state.

    A drained queue (``pending == 0``) is healthy and clears the latch. A
    non-empty queue that persists for ``threshold`` consecutive probes means the
    poller is not consuming updates — wedged. The alert fires only on the
    transition into wedged (``already_alerted`` latch), never repeatedly.
    """
    if pending_update_count <= 0:
        return HealthVerdict(
            status="healthy",
            should_alert=False,
            reason="queue drained (pending=0)",
            state=WatchState(consecutive_pending=0, already_alerted=False),
        )

    consec = state.consecutive_pending + 1
    if consec >= threshold:
        should_alert = not state.already_alerted
        reason = (
            f"poller wedged: {pending_update_count} update(s) pending across "
            f"{consec} consecutive probes (>= threshold {threshold})"
        )
        return HealthVerdict(
            status="wedged",
            should_alert=should_alert,
            reason=reason,
            state=WatchState(consecutive_pending=consec, already_alerted=True),
        )

    return HealthVerdict(
        status="degraded",
        should_alert=False,
        reason=(
            f"pending={pending_update_count}, {consec}/{threshold} "
            "consecutive probes — watching"
        ),
        state=WatchState(consecutive_pending=consec, already_alerted=False),
    )


# --- state persistence -----------------------------------------------------

_STATE_BASE = Path.home() / ".claude" / "channels" / "telegram"


def resolve_state_path(raw: str | Path, *, base: Path = _STATE_BASE) -> Path:
    """Confine the operator-supplied state path to ``base``; reject escapes.

    The CLI boundary validates untrusted ``--state-file`` input here before it
    reaches the file-IO sinks, so a ``../`` traversal cannot redirect writes
    outside the channel state directory.
    """
    base_r = Path(base).resolve()
    candidate = Path(raw).resolve()
    if candidate != base_r and base_r not in candidate.parents:
        raise ValueError(f"state file {candidate} escapes allowed base {base_r}")
    return candidate


def load_state(path: Path) -> WatchState:
    """Read the cross-probe state; a missing or corrupt file resets to default."""
    try:
        raw = json.loads(Path(path).resolve().read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return WatchState()
    return WatchState(
        consecutive_pending=int(raw.get("consecutive_pending", 0)),
        already_alerted=bool(raw.get("already_alerted", False)),
    )


def save_state(path: Path, state: WatchState) -> None:
    """Persist the state for the next one-shot probe."""
    Path(path).resolve().write_text(
        json.dumps(
            {
                "consecutive_pending": state.consecutive_pending,
                "already_alerted": state.already_alerted,
            }
        )
    )


# --- Bot API IO (injected urlopen) ----------------------------------------


def _get_json(url: str, urlopen: Callable) -> dict:
    with urlopen(url, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_method(token: str, method: str, fields: dict, urlopen: Callable) -> dict:
    """POST ``fields`` to a Bot-API ``method``; return the parsed body or raise."""
    payload = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"{API_BASE}/bot{token}/{method}", data=payload, method="POST")
    with urlopen(req, timeout=_TIMEOUT_S) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(f"{method} failed: {body.get('description', body)}")
    return body


def fetch_pending_update_count(
    token: str, *, urlopen: Callable = urllib.request.urlopen
) -> int:
    """Return Telegram's ``pending_update_count`` via ``getWebhookInfo``."""
    data = _get_json(f"{API_BASE}/bot{token}/getWebhookInfo", urlopen)
    if not data.get("ok"):
        raise RuntimeError(f"getWebhookInfo failed: {data.get('description', data)}")
    return int(data["result"].get("pending_update_count", 0))


def send_alert(
    token: str,
    chat_id: str,
    text: str,
    *,
    urlopen: Callable = urllib.request.urlopen,
) -> int | None:
    """Send via ``sendMessage`` (outbound survives a deaf inbound); return its id.

    Returns the Telegram ``message_id`` of the sent message so a caller can delete
    it again (the supervisor's heartbeat sentinel), or ``None`` if the response
    omits one. A failed send raises.
    """
    body = _post_method(token, "sendMessage", {"chat_id": chat_id, "text": text}, urlopen)
    message_id = body.get("result", {}).get("message_id")
    return int(message_id) if message_id is not None else None


def delete_message(
    token: str,
    chat_id: str,
    message_id: int,
    *,
    urlopen: Callable = urllib.request.urlopen,
) -> None:
    """Delete a previously-sent message via ``deleteMessage``.

    The supervisor uses this to remove its own heartbeat sentinel right after
    sending it: Telegram has already queued the inbound update for the operator's
    ``getUpdates`` poll at send time, and ``deleteMessage`` does not purge an
    already-queued update — so the round-trip still works while the message
    disappears from the chat. A best-effort op: a vanished message is not an error.
    """
    _post_method(token, "deleteMessage", {"chat_id": chat_id, "message_id": message_id}, urlopen)


def _alert_text(reason: str) -> str:
    return (
        f"🔔 Telegraph channel watchdog: {reason}. "
        "The operator session has likely gone deaf to inbound — relaunch it "
        "(claude --channels plugin:telegram@claude-plugins-official, then /telegraph-operator)."
    )


def run_probe(
    token: str,
    chat_id: str,
    state: WatchState,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    fetch: Callable[[], int] | None = None,
    alert: Callable[[str], None] | None = None,
) -> HealthVerdict:
    """One probe: read the queue, assess, and alert on a wedged transition.

    ``fetch``/``alert`` are injected for testing; they default to the real
    Bot-API calls bound to ``token``/``chat_id``.
    """
    fetch = fetch or (lambda: fetch_pending_update_count(token))
    alert = alert or (lambda text: send_alert(token, chat_id, text))
    pending = fetch()
    verdict = assess_channel_health(pending, state, threshold)
    if verdict.should_alert:
        alert(_alert_text(verdict.reason))
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Telegraph channel watchdog (getWebhookInfo deaf-detector)."
    )
    parser.add_argument("--chat-id", required=True, help="Telegram chat id to alert")
    parser.add_argument(
        "--token-env", default="TELEGRAM_BOT_TOKEN", help="env var holding the bot token"
    )
    parser.add_argument(
        "--state-file",
        default=str(Path.home() / ".claude" / "channels" / "telegram" / "watchdog_state.json"),
        help="JSON file carrying cross-probe state",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=DEFAULT_THRESHOLD,
        help="consecutive pending probes before wedged",
    )
    parser.add_argument(
        "--once", action="store_true", help="run a single probe (the only supported mode)"
    )
    args = parser.parse_args(argv)

    token = os.environ.get(args.token_env, "")
    if not token:
        sys.stderr.write(f"watchdog: ${args.token_env} is not set\n")
        return 2

    try:
        state_path = resolve_state_path(args.state_file)
    except ValueError as exc:
        sys.stderr.write(f"watchdog: {exc}\n")
        return 2
    state = load_state(state_path)
    try:
        verdict = run_probe(token, args.chat_id, state, threshold=args.threshold)
    except (RuntimeError, OSError) as exc:
        sys.stderr.write(f"watchdog: probe failed: {exc}\n")
        return 2
    save_state(state_path, verdict.state)
    print(f"{verdict.status}: {verdict.reason}")
    return 1 if verdict.status == "wedged" else 0


if __name__ == "__main__":
    sys.exit(main())

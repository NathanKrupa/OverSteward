# Telegraph operator supervisor (deaf-detector, Shape 1)

ABOUTME: Install + operate the external watchdog that rescues a deaf Telegraph operator.
ABOUTME: Covers the systemd `--user` unit, config, and the heartbeat instrumentation the operator must emit.

The always-on Telegraph operator (`claude --channels plugin:telegram`)
intermittently goes **deaf to inbound** — it stays alive and can still *send*,
but stops *receiving* Telegram messages. The cause is a cluster of still-open
upstream defects (claude-code `--channels` stdio #37482 / #40207 / #44380 /
#36477, telegram plugin #2229) whose core idle-wake variant clears **only on
restart**. An in-session watchdog cannot rescue a session whose own code has
stopped running, so this supervisor runs **outside** the operator
(OverSteward #115).

## What it does each tick

1. **DETECT** — two signals, fused by OR:
   - `getWebhookInfo().pending_update_count` non-zero for N consecutive ticks
     (the queue is filling because the poller is not draining).
   - a **heartbeat round-trip**: it sends a sentinel message and checks that the
     operator advanced a heartbeat file (catches the idle-wake bug the pending
     count cannot see).
2. **Anti-flap guards** — startup-grace (suppress detection right after a
   relaunch), hysteresis (N consecutive bad ticks), a cooldown ledger (no second
   relaunch within ~6h), and a restart-loop-breaker (over-budget restarts in a
   window → alert, don't loop).
3. **ALERT** — a one-shot `sendMessage` to Nathan via the bot token **directly**
   (outbound survives a deaf inbound).
4. **RELAUNCH + single-instance** — evict the wedged operator
   (SIGTERM → poll `kill(pid,0)` every 100ms up to 3s → SIGKILL), claim a PID
   file so a zombie poller cannot 409-fight the relaunch, then start a fresh
   operator. An ancestor-walk reaper distinguishes a true orphan (PPID chain ends
   at PID 1) from a process a live `claude` session still owns.
5. **Proactive recycle** — a healthy session older than `--max-idle` is recycled
   (uptime degrades the session: httpx pool / fd leak, session age).

Decision logic, eviction, and the heartbeat freshness rule are unit-tested with
fakes in `tests/telegraph/` — no live Telegram, no real token, no real process.

## Operator-side instrumentation (required)

Detection #2 needs the operator to prove it processed inbound. The operator must
**`touch` a heartbeat file every time it handles an inbound message** (including
the supervisor's sentinel `​[telegraph-heartbeat]`). Default path:

```
~/.claude/channels/telegram/operator_heartbeat
```

In the Telegraph operator skill, on each inbound turn:

```bash
touch ~/.claude/channels/telegram/operator_heartbeat
```

(or the Python equivalent `Path(...).touch()`). If the operator does not advance
this file, every heartbeat probe reads as a miss and the supervisor will relaunch
on the hysteresis threshold — so wire the instrumentation before enabling the
unit. The sentinel is near-invisible (zero-width-prefixed) but still arrives as a
message; mute that thread if desired.

## Install (systemd `--user`)

```bash
mkdir -p ~/.config/systemd/user ~/.claude/channels/telegram

# 1. Config + token (NEVER commit this file; chmod 600).
cat > ~/.claude/channels/telegram/supervisor.env <<'EOF'
TELEGRAM_BOT_TOKEN=123456:your-bot-token
TELEGRAPH_CHAT_ID=000000000
EOF
chmod 600 ~/.claude/channels/telegram/supervisor.env

# 2. Install + enable the unit.
cp ~/OverSteward/shared/scripts/telegraph/operator-supervisor.service \
   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now operator-supervisor.service

# 3. Keep the --user manager running across logout (headless box).
loginctl enable-linger "$USER"
```

Check it: `systemctl --user status operator-supervisor.service` and
`journalctl --user -u operator-supervisor.service -f`.

`Restart=always` relaunches the **supervisor** if it ever dies; the supervisor in
turn relaunches the **operator** when it goes deaf. Two layers, each watching the
one below.

## Running it by hand

A single tick (what a systemd timer or `/loop` would call):

```bash
TELEGRAM_BOT_TOKEN=… python3 ~/OverSteward/shared/scripts/telegraph/operator_supervisor.py \
  --chat-id 000000000 \
  --relaunch-cmd claude --channels plugin:telegram@claude-plugins-official
```

Continuous mode adds `--loop`. Everything after `--relaunch-cmd` is the operator
launch command. Tunables (all have sane defaults): `--poll-interval`,
`--hysteresis`, `--cooldown`, `--startup-grace`, `--restart-budget`,
`--restart-window`, `--max-idle`, `--term-timeout`, `--heartbeat-window`.

## Credential hygiene

The bot token is read from the environment (`--token-env`, default
`TELEGRAM_BOT_TOKEN`) by the settings factory and **never printed**. Keep it in
`supervisor.env` (chmod 600), never in the unit file, never in git. Do not
`source .env` to inspect it.

## Scope

Shape 1 only: detect → alert → relaunch + single-instance eviction. **Out of
scope** (tracked separately): Shape 2 (a dumb poller that *owns* the Telegram
queue so messages can never be silently lost) and switching the MCP transport off
stdio (a partial cure that does not fix the core idle-wake bug).

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
4. **RELAUNCH + single-instance (via tmux)** — evict the wedged operator with
   `tmux kill-session -t telegraph-operator`, then start a fresh one with
   `tmux new-session -d -s telegraph-operator '<relaunch_cmd>'`. The detached
   tmux session allocates a **pty**, so `claude --channels …` runs *interactive*
   (under systemd there is no controlling terminal, and a bare process would drop
   into `--print` mode and die immediately). The **fixed session name** gives
   single-instance for free — tmux refuses a duplicate name, so a hand-started
   operator and the supervised one converge on ONE canonical session, and the
   supervisor adopts a manually-launched operator instead of spawning a rival
   that would 409-fight over `getUpdates`. The tmux *server* keeps the session
   alive independently of supervisor restarts and logout (linger).
5. **Proactive recycle** — a healthy session older than `--max-idle` is recycled
   (uptime degrades the session: httpx pool / fd leak, session age).

Decision logic, the tmux relaunch/adopt service, and the heartbeat freshness rule
are unit-tested with fakes in `tests/telegraph/` — no live Telegram, no real
token, no real tmux.

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
unit. The supervisor **deletes its own sentinel** immediately after sending it
(`deleteMessage`), so it does not appear in Nathan's chat — but Telegram has
already queued the inbound update for the operator's poll at send time, and the
deletion does not purge an already-queued update, so the round-trip still works.

## Install (systemd `--user`)

Prerequisite: `tmux` on `PATH` (the supervisor launches the operator inside a
detached tmux session). Confirm with `command -v tmux`.

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

## Launching the operator by hand

The canonical way to start the operator — whether by hand or via the supervisor —
is inside the fixed-name detached `telegraph-operator` tmux session:

```bash
tmux new-session -d -s telegraph-operator \
  'claude --channels plugin:telegram@claude-plugins-official'
# then, from inside that session, run /telegraph-operator once
```

Because the session name is fixed, the supervisor **adopts** this session (it
checks `tmux has-session -t telegraph-operator`, not a PID file) instead of
spawning a rival, and a second `tmux new-session -s telegraph-operator` is refused
— single-instance for free. Attach to watch it with
`tmux attach -t telegraph-operator` (detach again with `Ctrl-b d`).

## Running the supervisor by hand

A single tick (what a manual check would call):

```bash
TELEGRAM_BOT_TOKEN=… python3 ~/OverSteward/shared/scripts/telegraph/operator_supervisor.py \
  --chat-id 000000000 \
  --relaunch-cmd claude --channels plugin:telegram@claude-plugins-official
```

Continuous mode adds `--loop` (the systemd unit uses this); on each process start
the supervisor resets its grace window + detection streaks while preserving the
cooldown ledger. Everything after `--relaunch-cmd` is the operator launch command.
Tunables (all have sane defaults): `--session-name` (default `telegraph-operator`),
`--poll-interval`, `--hysteresis`, `--cooldown`, `--startup-grace`,
`--restart-budget`, `--restart-window`, `--max-idle`, `--heartbeat-window`.

## Credential hygiene

The bot token is read from the environment (`--token-env`, default
`TELEGRAM_BOT_TOKEN`) by the settings factory and **never printed**. Keep it in
`supervisor.env` (chmod 600), never in the unit file, never in git. Do not
`source .env` to inspect it.

## Scope

Shape 1 only: detect → alert → relaunch the operator inside its `telegraph-operator`
tmux session (single-instance via the fixed session name). **Out of
scope** (tracked separately): Shape 2 (a dumb poller that *owns* the Telegram
queue so messages can never be silently lost) and switching the MCP transport off
stdio (a partial cure that does not fix the core idle-wake bug).

---
name: telegraph-operator
description: "Operating playbook for the always-on Telegraph control session. Invoke ONCE at the start of a `claude --channels plugin:telegram@claude-plugins-official` session to enter operator mode — thereafter every inbound Telegram message is parsed per the routing grammar and acted on with the auto-file / confirm-dispatch autonomy model. Use when standing up the Telegraph membrane, when Nathan says \"telegraph operator\" / \"operator mode\", or runs /telegraph-operator."
---

# /telegraph-operator — the membrane's operating mode

The Telegraph turns one Telegram chat (`@KrannocBot`, chat id `8742962362`) into Nathan's single front door to every repo, so he stops copy-pasting between windows. This skill is the **resident behavior** of the control session: invoke it once, and for the rest of the session you act as the operator on every `telegram` channel event. Design: `documentation/designs/the-telegraph.md` §3.

Run this session from the **OverSteward** working tree (it needs `registry.yaml`, the dispatch skills, and the relay primitive).

## Pre-flight (once, on invocation)

1. Confirm the Telegram channel is attached (the session was started with `--channels plugin:telegram@claude-plugins-official`). If not, tell Nathan to relaunch with the channel — you cannot receive without it.
2. Confirm the allowlist is locked: `/telegram:access policy allowlist` with only chat `8742962362` paired. The plugin gates senders server-side; you **also** verify the sender id on every event as defense-in-depth (§R5). Drop anything not from `8742962362` silently.
3. Reply to Nathan on Telegram: `Telegraph operator online. Send "help" for the grammar.`

## How you communicate

**Every** user-facing response goes back through the channel's **reply tool** (the Telegram plugin exposes a reply/send tool while the channel is active). Your normal terminal output is invisible to Nathan on his phone — if you don't call the reply tool, he hears nothing. One reply per handled message: the result, kept short.

## Heartbeat — proving you're awake (supervisor contract)

An external watchdog — the **operator supervisor** (`shared/scripts/telegraph/operator_supervisor.py`, OverSteward #115) — rescues this session when it goes **deaf to inbound** (the upstream `--channels` idle-wake bug: the session stays alive and can still *send* but stops *receiving*). Its heartbeat probe can only tell a live session from a deaf one if you leave a mark each time you actually process an inbound message.

**On every inbound turn, before parsing the message, touch the heartbeat file:**

```bash
touch ~/.claude/channels/telegram/operator_heartbeat
```

If you stop advancing this file the supervisor reads every probe as a miss and will evict + relaunch this session on its hysteresis threshold — so once the unit is enabled this is not optional.

**The supervisor's sentinel.** The probe sends a near-invisible sentinel message — `[telegraph-heartbeat]` (zero-width-prefixed) — and checks that you advanced the file. When an inbound message *is* that sentinel: touch the heartbeat (above) and **stop** — do not parse it as a verb, do not reply, do not route it. It is the watchdog taking your pulse, not Nathan.

## Routing grammar

Parse each inbound message into one verb. Repo shorthand resolves via the `id`/`dispatch_target` rows in `registry.yaml`:

| Shorthand | Repo slug |
|---|---|
| `AG` | `NathanKrupa/aigranthelper` |
| `GS` | `NathanKrupa/grantspider` |
| `WP` | `NathanKrupa/wphelper` |
| `FI` | `NathanKrupa/Fiscus` |
| `EX` | `NathanKrupa/exchequer` |
| `ai-assistants` | `NathanKrupa/ai-assistants` |

### Auto-fire verbs (no confirmation — reversible or read-only)

- **`<REPO>: <description>`** — file a scoped issue.
  Run the relay primitive:
  `shared/scripts/telegraph/file_cross_repo_issue.py --repo <slug> --title "<short title from the description>" --body "<description>"`
  (no `--source-repo`: this is Nathan filing directly, so a clean `needs-scoping` issue with no `from:` provenance footer.)
  Reply with the issue URL.
  - Suffix **`!ready`** on the message → add `--label ready-for-agent` instead of the default `needs-scoping` (still only *queues* it as dispatch-eligible; it does not dispatch).
- **`status`** — run `/project-status`; reply with the table (trim to the headline counts if long).
- **`questions`** / **`what's waiting`** — run `/questions`; reply with the compact list.
- **`help`** — reply with this grammar.

### Confirm-first verbs (spend tokens / open PRs / post to a thread)

Echo the intended action and wait for an affirmative reply *before* acting. Only proceed on a clear "yes" that follows your confirm; any other message abandons the pending action.

- **`dispatch <REPO> <N>`** — reply `About to dispatch <REPO>#<N> — reply "yes" to proceed.` On yes, run `/dispatch <repo> <N>`; reply the terminal state (MERGED / CI_FAILED / STOPPED_FOR_INPUT / …).
- **`answer <REPO> <N>: <text>`** — reply `Post this answer to <REPO>#<N>?\n"<text>"\nReply "yes" to send.` On yes, run `/answer <repo> <N>` with `<text>`; reply confirmation.
- A reply to a question you pushed (see below) is shorthand for `answer` on that issue — still echo a one-line confirm before posting.

## Pushing to Nathan (outbound bell)

When the session learns an agent is blocked or a dispatch finishes, push proactively via the reply tool (and `PushNotification` for anything he'd want off his phone's lock screen):
- `needs-input` raised → `🔔 <REPO>#<N> needs input: <question excerpt>` — Nathan can reply to answer.
- dispatch reached a terminal state → one line with the outcome + PR link.
Keep pushes rare and actionable (the PushNotification discipline): a block, a finish, a failure — not routine progress.

## Safety rails

- **Sender check every time** — act only on chat `8742962362`.
- **Never guess** — if the repo prefix is unknown, the verb is ambiguous, or an issue number is missing, reply asking for clarification; do not act.
- **Confirm means confirm** — never run a confirm-first verb without the affirmative reply, even if intent seems obvious.
- **One verb per message** — if a message contains two intents, handle the first and ask about the rest.
- **Honest failures** — if a tool errors (gh failure, dispatch refusal), reply the actual error, not a guess.

## Relationship to the rest of the Telegraph

This skill is the **interactive channel adapter** (§3.3). It shares the relay primitive (`file_cross_repo_issue.py`) with the future ambient cross-repo filer and the Epic Conductor — same primitive, different front-end. The conductor (Phase 3) will run as a separate concern in this same session, holding epic state on a GitHub tracking issue.

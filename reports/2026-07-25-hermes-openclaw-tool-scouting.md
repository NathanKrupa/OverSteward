# Tool Scouting: Hermes Agent & OpenClaw

_Deep-research inventory of two open-source personal-agent codebases, mining for
tools and architecture the estate could adopt. Compiled 2026-07-25._

Full per-repo dossiers (kept in the session scratchpad, not committed):
`hermes-dossier.md`, `openclaw-dossier.md`. This report is the synthesis.

---

## The two subjects, in one breath

| | **Hermes Agent** | **OpenClaw** |
|---|---|---|
| Repo | `NousResearch/hermes-agent` | `openclaw/openclaw` |
| Is | Nous Research's daily-driver personal agent | Steinberger's personal-assistant gateway (Warelay→Clawdbot→Moltbot→OpenClaw) |
| Core language | **Python** (TS is only the TUI shell) | **TypeScript/Node** (pnpm monorepo) |
| License | **MIT** | **MIT** (no AGPL/GPL — safe for AG) |
| Maturity | Very high; battle-scarred, issue-numbered | Very high; ~82k LOC core, heavy CI/security |
| Portability to us | **Byte-copy candidate** (same stack) | **Idea-mine only** (TS → reimplement) |

Both are MIT, so nothing here carries a copyleft burden. The lineage note: Hermes'
source references OpenClaw as a predecessor/sibling — they are cousins, and it
shows (both use a `MEMORY.md` file, a heartbeat/cron cadence, a pairing membrane,
fence-safe chunking). We are scouting **two independent takes on the same
problems we have.**

---

## The convergence — where BOTH point at an estate pain

The striking result: the two codebases, built independently, land on the **same
answers to our three stated reliability pains.** That convergence is the strongest
signal in this report.

### Pain 1 — "Railway daemon hangs without self-healing"

Both have purpose-built hang-killers, and together they spell out the complete recipe:

- **Hermes `shutdown_watchdog.py` (~429 LOC):** an **OS thread** (can't be frozen
  by a wedged asyncio loop) probes the loop every 30s via `call_soon_threadsafe`;
  after 3 misses it dumps all tracebacks (`faulthandler`) then `os._exit(code)` so
  the supervisor restarts. **This is the genuine hang-detector our daemon lacks.**
- **Hermes `mcp_stdio_watchdog.py` (157 LOC, stdlib-only, POSIX):** wraps a child
  in its own process group, polls `os.getppid()` every 2s, SIGTERM→SIGKILL on
  parent death. Kills orphaned children — maps directly to "Railway kills the
  parent, child lingers."
- **Hermes `restart_loop_guard.py` (150 LOC):** counts restart-interrupted boots
  in a 60s window, skips auto-resume after 3, fails open — breaks a
  supervisor-driven respawn loop.
- **OpenClaw `doctor-gateway-daemon-flow.ts` (505 LOC):** the intelligent side —
  inspects service state, checks the port has expected listeners, **reads the last
  error line from the diagnostics log**, and gates any restart on an **actual
  health probe** (not "process exists"). Honors an external-supervisor policy so
  it won't fight Railway.
- **OpenClaw `restart-handoff.ts`:** writes a "recently restarted + healthy → skip
  re-restart" record to **break supervisor-vs-repairer restart loops** — the single
  most important idea, and the thing hang-prone daemons omit.

**Synthesized recipe for our daemons (GS crawler, any asyncio service):**
1. OS-thread liveness watchdog → `os._exit(non-zero)` on hang (Hermes).
2. Let Railway `restartPolicy: ON_FAILURE` catch the non-zero exit — **verify our
   exact GS Railway config triggers on `os._exit`** (open question).
3. Restart-handoff record + health-probe-gated restart to avoid restart loops
   (OpenClaw).
4. Orphan-killer on any long-lived child process (Hermes `mcp_stdio_watchdog`).

### Pain 2 — "Cloud schedulers unreliable / laptop sleep kills in-session work"

- **OpenClaw heartbeat-runner (2,776 LOC):** a supervised **proactive-turn cadence
  engine** — wakes the agent on a schedule with **active-hours gating** (no 3am
  wake), **busy-lane skip** (never double-drives a running session), **ack tokens**
  (provable completion), and **restart-recoverable pending delivery.** This is our
  dream-cycle + operator-watchdog fused into one daemon instead of a fragile
  in-session drain.
- **Hermes cron scheduler (`cron/scheduler.py`, 4,298 LOC):** a real in-process
  persistent scheduler with tick file-lock, an **execution ledger** (SQLite WAL),
  and `recover_interrupted()` that compares stored PID+start-time against live OS
  to mark provably-dead runs `unknown` (honest — won't blindly retry
  side-effecting work). Catch-up window = ½ period, clamped.

**Honest caveat (both):** neither *solves* laptop-sleep death — their answer is
"run on a supervised host (VPS/systemd)." The reusable pieces are the
**execution-ledger + recover-on-restart** semantics, not the ticker. We'd still
need a durable host or external trigger. Confirm before assuming either "fixes" sleep.

### Pain 3 — "Scheduled cloud agents fail silently"

- **OpenClaw cron failure alerting (`types.cron.ts`):** after N failures, announce
  to a channel or POST a webhook, with cooldown. Turns silent scheduler death into
  a notification. **Low effort, directly addresses a stated law.**
- **Hermes `[SILENT]` / `no_agent` cron pattern:** run a cheap script first; only
  wake the LLM (and only notify) when something changed. Kills notification spam
  and LLM cost — **perfect for the Vintner pipeline-health monitor.**

---

## Ranked adoption shortlist (cross-repo)

Effort legend: **byte-copy** (Python, drop in) / **adapt** (port a slice) /
**idea** (take the design, write fresh). Source in brackets.

| # | Candidate | Estate gap | Effort | Source |
|---|---|---|---|---|
| 1 | **Daemon self-heal recipe** — OS-thread hang-watchdog + orphan-killer + restart-handoff + health-probe-gated restart | Railway daemon hangs; watchdog dies with VS Code | **byte-copy** (Hermes files) + **idea** (OpenClaw doctor) | both |
| 2 | **Footprint Ladder** — 6-rung "where does a capability belong" decision framework | Sharpens our OUTER/MIDDLE/INNER + skill-vs-tool-vs-MCP calls | **idea** (prose → architecture-principles.md) | Hermes |
| 3 | **Cron failure alerting + `[SILENT]`/no-agent monitors** | Schedulers fail silently; Vintner cost/spam | **idea** (low) | both |
| 4 | **Self-hosted pairing/allowlist membrane** — unknown sender → code → operator-approve → SQLite allowlist | Telegraph rides a *public* Happy relay with implicit trust | **idea** (medium) | OpenClaw |
| 5 | **`threat_patterns.py`** — prompt-injection/C2/exfil regex scanner (NFKC-normalized, FP-tuned) | Screen untrusted issue/PR content + agent-written memory before it drives an agent | **byte-copy** (self-contained) | Hermes |
| 6 | **Code-execution-via-RPC** — model writes Python calling allowlisted tools over a socket; only final stdout re-enters context | Token savings on metered dispatch pipelines | **idea** (medium; new surface) | Hermes |
| 7 | **Frozen-snapshot memory discipline** — inject `MEMORY.md` once at session start; mid-session writes hit disk but don't re-inject (preserve prompt cache) | Our MEMORY.md handling; cache-stable memory | **idea** (low) | Hermes |
| 8 | **Fence/surrogate-safe adaptive chunking + streaming draft** | Long/markdown replies break on the phone relay | **idea** (low; clean algorithm) | OpenClaw |
| 9 | **FTS5+BM25 session search** — indexed search over past transcripts, demotes cron/system chatter | Dream cycle greps markdown; no ranked recall | **adapt** (medium) | Hermes |
| 10 | **Curator skill-hygiene loop** — usage-telemetry-driven auto-archive of stale *agent-created* skills; never-delete; pin-exempt; provenance-scoped | Complements the dream cycle; no skill staleness pass today | **idea** (medium) | Hermes |
| 11 | **Sensitive-URL redactor** — strip token/key/password query params + userinfo from logged URLs | Complements credential-hygiene gate (which only blocks `.env` sourcing) | **idea/byte-copy** (low) | OpenClaw |
| 12 | **Skill dependency self-declaration** — `metadata.*.requires.bins` + install recipes + `primaryEnv` | Skills assume host bins exist | **idea** (low; additive to SKILL.md) | OpenClaw |

**Highest ROI / lowest risk:** #2 (Footprint Ladder — pure prose) and #3 (cron
alerting — low effort, kills a stated pain). **Highest value:** #1 (daemon
self-heal — the direct fix for the hanging-daemon problem). **Cheap quick wins:**
#5, #7, #11.

---

## Skill-format compatibility (bonus)

Both projects use `SKILL.md` with YAML frontmatter + Markdown — **the same shape as
Claude Code skills.** Hermes' bundled `skills/` and `optional-skills/` trees
(github, mlops, research, devops, email…) may be **directly loadable into
`.claude/skills/`** with light frontmatter reconciliation (they carry
Hermes-specific `metadata.hermes.*` keys — needs a spike to confirm our loader
ignores unknown keys). OpenClaw adds a nice dependency-declaration block worth
copying into our format regardless.

---

## What to leave on the shelf

- **The whole runtime of either** — both are complete competing agent products with
  their own model loop, provider stack, and messaging gateway. We are Claude-Code-
  native; adopting a platform forks our world. Mine slices, don't import platforms.
- **Hermes `delegate_task` / Kanban board** — real and nice, but in-process thread
  isolation (weaker than our Claude Code subagents) and a parallel non-GitHub task
  board (competes with our issue-label dispatch bus). Borrow the *failure-limit
  auto-block* + *heartbeat-wired-to-liveness* ideas only.
- **Hermes browser stack (212KB + Camoufox anti-detect)** — GS already has a
  politeness/IP-tuned Playwright crawler; this is a net complexity add.
- **OpenClaw's 159-extension channel fleet + native companion apps** — Happy is our
  phone path; we don't need WhatsApp/Discord/iMessage transports. Steal the
  membrane seam + chunking + pairing, not the transports.
- **OpenClaw's trust model wholesale** — it *assumes* one trusted operator;
  `sessionKey` is routing, not auth. Fine for a solo assistant, **wrong for
  aigranthelper (paid multi-tenant).** Steal the *mechanisms* (pairing, sandbox,
  exec approval), never the tenancy assumption.
- **Hermes `tirith_security.py`** — auto-downloads a third-party Rust binary from
  GitHub releases; our threat model (Nathan talking to his own agent) doesn't
  warrant it.

---

## Open questions before committing to anything

1. **Does GS's Railway `restartPolicy: ON_FAILURE` actually fire on `os._exit(non-zero)`?**
   The whole hang-watchdog plan hinges on this. (Cross-ref standing memory:
   "no self-heal on hang.") Needs a one-off verification.
2. **Neither scheduler survives host death (laptop sleep / WSL2 suspend).** Reusable
   piece = execution-ledger + recover-on-restart, not the ticker. Do we pair this
   with a durable host or external trigger?
3. **Code-execution-RPC blast radius** — if adopted, what's the tool allowlist, and
   is `terminal` in it for our threat model?
4. **Skill-format fidelity** — do Hermes/OpenClaw `SKILL.md` files load cleanly in
   our loader (unknown-key tolerance)? A spike before claiming "byte-copy."
5. **MIT attribution hygiene** — any file we adapt (`mcp_stdio_watchdog.py`,
   `threat_patterns.py`) should carry a short attribution header. Cheap, don't forget.

---

## Recommendation (SUPERSEDED — see Part II)

_The three-tier recommendation that stood here was written before red-teaming the
ideas against the estate's actual code. Four read-only recon agents ground-truthed
every landing zone and most of the shortlist did not survive contact. **Part II
below is the operative plan.** The original tiers are retained in git history only._

---

# Part II — Red-Team Revision (operative)

_Compiled 2026-07-25 after four adversarial recon passes over grantspider +
OverSteward (daemon/scheduler, dream/memory, Telegraph/Vintner, dispatch/security).
Each proposed adoption was tested against real code, not memory. This section
supersedes the shortlist above._

## The verdict in one line

**9 of 12 candidates are rejected or moot.** Most were Hermes/OpenClaw-shaped
solutions to Hermes/OpenClaw's problems (untrusted web/MCP ingestion, metered-API
token economics, a self-hosted gateway, an accreting pile of agent-generated
skills). The estate has none of those problems. What survived is small, and the
two highest-value actions the exercise produced **didn't come from either codebase
at all** — they're pre-existing gaps the recon surfaced by looking hard at our own
systems.

## Kill list (with the ground-truth reason)

| Idea | Verdict | Why it dies against our reality |
|---|---|---|
| (A) OS-thread `os._exit` hang-watchdog | **Duplicates + breaks** | No bespoke asyncio daemon exists — it's Dagster's daemon on Railway. GS already runs `daemon-watchdog` **out-of-band on a different container**, precisely because incident #1545 proved an *in-process* sensor "froze exactly when needed." An in-thread `os._exit` reintroduces that, and burns the `restartPolicyMaxRetries=10` budget on a hang-loop. |
| (C) `getppid()` orphan-killer | **No such problem** | Nothing here spawns long-lived stdio children. Prod runs on Railway (not the laptop), and on WSL2 suspend parent+child freeze together so it never fires. |
| (D) PID+start-time execution-ledger | **Duplicates; PID is worse** | `zombie_reaper` (event-log-silence) + enrichment lease-reaper already recover dead runs. Post-#1829 workers are in a different PID namespace — the daemon can't even see their PID. GS deliberately rejected PID liveness. |
| (E) Frozen-snapshot memory | **Moot — can't control the layer** | Memory injection is owned entirely by the Claude Code harness (the store is a symlinked dir it auto-loads). We hold no lever to "freeze" it. The real lever — a lean `MEMORY.md` — is already solved by the OS#203 Standing Orders split. |
| (G) Curator skill-hygiene | **Non-problem** | 9 hand-authored, git-tracked skills, zero `created_by` provenance, no agent-at-volume generation. Git *is* the never-delete archive. Nothing to curate. |
| (H) Pairing/allowlist membrane | **No place to live + no attack surface** | Inbound is ordinary user turns from Happy; no `<channel>` envelope, no sender id. TweetNaCl pairing makes the phone the *single trusted principal* — an unknown sender can't reach the session. We run no gateway for an allowlist DB to sit in. The correct defense (injection asking to widen trust) is already a hard-coded prompt rule. |
| (I) Adaptive message chunking | **No place to live** | We don't own outbound rendering — Happy + Claude Code do. There's no send-function in our code to wrap. Fix belongs upstream in Happy. |
| (L) `threat_patterns.py` dispatch screen | **Rejected — FP hazard + duplicate** | Issues are Nathan-authored (single-author repos); no untrusted web/MCP surface like the one Hermes built this for. Injection is already handled by the untrusted-data boundary (invariant I-3) + deterministic effect-denial. And the patterns trip on normal estate vocabulary — `heartbeat`, `register as a node`, `edit CLAUDE.md` — blocking legit dispatches. |
| (M) Code-execution-via-RPC | **Rejected — hook-invisible + uncharged cost** | Optimizes token cost we don't pay (Max, not metered; the real constraint is quota-window exhaustion). Duplicates subagent + Bash. Worst of all, a private-socket code channel **bypasses the entire PreToolUse hook stack** (`guard_main_worktree`, `check_destructive_command`, `guard_neon`) — a large net-negative security surface. |

## Survivors (scoped down from the pitch)

1. **Vintner failure-alerting — BUILD IT.** _(from J, the alerting half only)_
   The one clean win. The Vintner's report spine exists; the **alerting layer is
   designed but unbuilt** — no `.github/workflows` cron, no `pipeline-health` issue
   writer, no watch-the-watcher heartbeat. The design (A6/A7) already specifies the
   exact shape: 30-min cron → severity-routed to a rolling `pipeline-health` GitHub
   issue + push, de-duped by transition. OpenClaw's "announce-after-N-failures with
   cooldown" maps onto it cleanly. **This is adopting a design we already wrote, not
   importing OpenClaw.** Highest value, lowest risk. _(Note: the "cheap-check-first /
   only-wake-on-change" pattern is NOT new — it's already stricter Vintner doctrine.)_

2. **GS daemon-watchdog durability + retry-budget fix — the emergent real gap.**
   _(from B's narrow wedge; NOT an adoption)_ The recon found two genuine holes the
   code itself admits: (a) `WatchdogState` is **in-process only**, so if the
   webserver hosting the watchdog restarts, restart history is lost and the circuit
   breaker resets; (b) `restartPolicyMaxRetries=10` is a hard platform ceiling that
   the watchdog's *own* restarts also consume — a crash-loop can silently exhaust it
   while the circuit breaker (3/60min) is still "closed," leaving a window where
   neither layer restarts. **Fix: persist `WatchdogState` (SQLite/Dagster instance)
   + make the retry-budget interaction explicit.** This is a GS reliability issue on
   its own merits — Hermes/OpenClaw only pointed the flashlight.

3. **architecture-principles.md micro-edit.** _(from K, the 2 net-new ideas only)_
   Fold in (a) the **least-permanent-surface ordering** (prefer the reversible/cheap
   surface first) and (b) the **"3+ PRs of the same category → extract an ABC"**
   trip-wire, as a sharpening of the existing Duplication Signal — **reconciling the
   threshold** (our signal fires at 2 files, the trip-wire at 3; pick one). **Do not**
   import the 6-rung taxonomy — 4 rungs reference plugin/MCP-catalog machinery we
   don't have. A few lines, not a framework.

4. **Standalone transcript-search tool — optional, re-scoped.** _(from F, rescoped)_
   FTS5/BM25 over the dream cycle is pointless (it processes transcripts exhaustively
   by hash — there's no search to replace). But ad-hoc "what did we decide about X"
   across multi-MB JSONL transcripts is **genuinely unserved** today (you hand-grep).
   If wanted, that's a *new small standalone tool* (even ripgrep-backed), not a dream-
   cycle change. Nice-to-have, low priority.

## Bonus: two stale memories the recon caught (highest-confidence actions)

These are the most certain items in the whole exercise — verified against shipped code:

- **`feedback_dream_finalize_run_clobbers...` is STALE.** The flag-clobber bug was
  fixed by OS#134's durable `FlaggedStore` open-set (`cycle.py`); the memory still
  says "never let finalize_run run automatically," contradicting the fix. Update it.
- **`user_..._operator_watchdog_lifecycle` is STALE.** The operator supervisor/watchdog
  it describes was **removed 2026-07-02** (OS#180 → PRs #186/#187) when Happy was
  adopted; it was never actually installed even before removal. Graveyard or rewrite it.

## Revised recommendation

- **Do (real wins):** (1) build the **Vintner alerting layer** (design is waiting);
  (2) file a GS reliability issue for **watchdog-state durability + retry-budget
  exhaustion**; (3) **update the two stale memories** (cheap, certain).
- **Do if idle (tiny):** the **architecture-principles.md** ordering + ABC-trip-wire
  edit, threshold reconciled.
- **Optional:** a **standalone transcript-search tool** if the hand-grep pain is real.
- **Reject:** A, C, D, E, G, H, I, L, M — logged above with reasons so they're not
  re-proposed.

**The meta-lesson:** the estate is further along its own reliability/security/memory
curve than the scouted projects are on the axes that matter to us. The value of the
scouting wasn't a parts bin to copy — it was a mirror that made us re-examine our own
systems and find two real gaps (Vintner alerting, watchdog durability) we'd have kept
walking past.

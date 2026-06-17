ABOUTME: Design doc for The Telegraph — a single chat-shaped membrane through which Nathan directs any repo, repos file work to each other, and coordinated cross-repo epics run under a supervised conductor, so Nathan stops being the copy-paste transport between windows.
ABOUTME: Draft for review 2026-06-17; no code yet — design gate first, per estate doctrine.

# The Telegraph — One Wire for the Whole Estate

**Status:** **Scope approved 2026-06-17.** No implementation yet — Phase 0 (design gate) clears to Phase 1 on Nathan's sign-off of the three proposed decisions in §9. A future **email ingestion channel** is captured as deferred intent (§3.4, §9 item 10).

**Name:** **The Telegraph** — a telegraph network has many *stations* (the repos), one *operator key* from which the steward can send to any station (Nathan's single chat), *station-to-station relay* that needs no operator at the desk (repos filing work to each other), and a *bell that sounds on receipt* (a push when Nathan is actually needed). The central *telegraph office* routes traffic and, for a coordinated operation across several stations, runs the line under a single hand. It also puns gently on **Telegram**, the chosen front-door channel.

**Author:** Chestertron, 2026-06-17.

**Kinship:** The concrete realization of the **"Tier 2 / Project Director Agent"** deferred in [`multi-agent-dev-orchestration.md`](../multi-agent-dev-orchestration.md) (April 2026). That doc named the shape — a director that "decomposes intent into discrete, sequenced tasks, routes tasks to the appropriate specialist agent, tracks decisions across sessions." The Telegraph builds it on the substrate the estate has since grown: `/dispatch`, the scoped `<repo>-dev` agents, the label state machine, and GitHub issues as the bus. Sibling to **The Vintner** (shares the GitHub-issue + push notification nervous system, §6) and downstream of **Gaudí** (the quality gate every dispatched leg still passes).

**Anchors in existing governance:** generalizes the single live cross-repo seam (`grantspider → aigranthelper` via `repository_dispatch` + human-gated draft PR) into a many-to-many pattern; reuses the `ready-for-agent → agent-in-progress → needs-input → answered` label cycle verbatim; preserves the foreground-only dispatch discipline forced by [claude-code#47936](https://github.com/anthropics/claude-code/issues/47936).

**Decisions locked by Nathan (2026-06-17):**
- Front door = **Claude Code Channels with the official Telegram plugin** (a running control session receives chat), not a standalone bot.
- Ambient cross-repo filing = **lands as `needs-scoping`** (Nathan gates every unplanned cross-repo issue).
- **Build a conducted mode** on top: an AG↔GS pair that works back-and-forth to accomplish a *scoped epic requiring coordination*, autonomous *within the blessed plan*.

---

## 0. The reframe (read this first)

The pain Nathan reported is "copy-pasting between windows." The architecturally precise statement of that pain:

> **Nathan is currently the message bus.** An agent in repo A surfaces work that belongs to repo B → Nathan's eyeballs → Nathan's clipboard → repo B's window. He is the transport layer. Separately, *directing* work means opening the right window and typing — there is no single front door. And *knowing he is needed* means remembering to run `/questions` and `/project-status` — pure polling, no push.

The substrate to fix this **already exists and is correct**: GitHub issues + labels are a durable, queryable, human-visible message bus, and OverSteward is already the broker (`registry.yaml`, `/dispatch`, `/project-status`, `/answer`). The estate even has one working station-to-station wire: GS→AG via `repository_dispatch` and a human-gated draft PR.

So the Telegraph is **not** a new substrate (no Redis, no Kafka, no chat app as system-of-record — that is the big-fleet pattern and is YAGNI for six repos and one principal). It is a **chat-shaped membrane bolted onto the bus the estate already runs**, plus a generalized relay so repos stop routing through Nathan, plus a supervised conductor for coordinated epics. GitHub stays the bus. Telegram is a *view* onto it, not a replacement for it.

---

## 1. Current-state map (verified 2026-06-17)

| Capability | Today | Reference |
|---|---|---|
| **Direct one repo** | Open that repo's window, type. No single source. | — |
| **Cross-repo handoff** | Nathan copy-pastes between windows. Exactly one automated wire: GS→AG `repository_dispatch` → AG draft PR (human-gated). | `architecture.md §2` seams; invariant I-19 |
| **Issue state machine** | `ready-for-agent → agent-in-progress →` (success clears labels) `or needs-input →` (`/answer`) `→ ready-for-agent`. Labels are the state. | `dispatch` playbook; `answer/SKILL.md` |
| **Dispatch execution** | `/dispatch <repo> <issue>` → scoped `<repo>-dev` agent in an isolated worktree, **foreground, Max subscription** (never background — bug #47936). Polls to terminal state. | `dispatch/SKILL.md` + `playbook.md` |
| **Visibility** | **Pull-only.** Nathan runs `/questions`, `/project-status`, `/answer` ad-hoc. No push of any kind. | `project-status`, `questions` skills |
| **Cross-machine inbox** | `~/.claude/shared/inbox.md` — local to each machine, drift-prone, manual. Retired the older Obsidian round-trip in PR #16. | `CLAUDE.md`; OVERSTEWARD.md §Inbox |

**The gap, distilled:** the bus is sound; the *membrane* (a single chat front door), the *relay* (repos file to each other), and the *bell* (push when needed) are missing. Nathan supplies all three by hand.

---

## 2. The two-mode trust model

Nathan's two answers are not two policies — they are **one mechanism at two trust levels**, and the dividing line is a single question: *is there a plan Nathan already blessed?*

| | **Ambient cross-repo** (the floor) | **Conducted epic** (the new capability) |
|---|---|---|
| **Trigger** | An agent incidentally discovers work for a sibling repo. | Nathan blesses a multi-leg plan with explicit acceptance criteria. |
| **What happens** | File an issue in the sibling labeled `needs-scoping, from:<src>`, backlinked. Lands in Nathan's queue. | The conductor runs the legs across both repos automatically, in dependency order. |
| **Where the gate is** | **Per issue.** Nathan scopes every one before it can be dispatched. | **Per plan.** Nathan approves the whole epic once, up front; legs then flow without per-leg approval. |
| **Autonomy** | None beyond filing. | Bounded autonomy *inside the fence* (acceptance criteria + max-rounds + needs-input circuit-breaker). |

The crucial property: **the gate never disappears; it relocates.** Ambient mode keeps Nathan's conservative per-issue gate (his explicit choice). Conducted mode moves the gate to plan-approval time — which is exactly how the estate's one existing cross-repo wire already behaves (the GS→AG draft PR is auto-*opened* but human-*merged*). Both honour the governing principle: **remove the mechanical labour, keep the human judgment.**

Both modes call the **same primitive** (§4, the cross-repo filer) and the **same executor** (`/dispatch`). Conducted mode is ambient mode with a referee and a pre-approved DAG.

---

## 3. The membrane — control session + Telegram channel

### 3.1 What it is
A single long-lived **OverSteward control session** running with the official Telegram channel plugin attached:

```
claude --channels plugin:telegram@<official-marketplace>
```

[Channels](https://code.claude.com/docs/en/channels.md) push external events *into* a running session. This one session is simultaneously:
- **the front door** — Nathan types `AG: rate-limit the export endpoint`; the session routes it to the right repo (§3.2);
- **the bell** — agent questions and terminal states arrive as Telegram messages; `PushNotification` fires for anything needing Nathan;
- **the conductor** — it holds the baton for conducted epics (§5).

One session serves all three because Channels *requires* a live session anyway and a conducted epic *requires* a brain holding state — so they coincide rather than compete.

### 3.2 Routing (what the session does with a chat line)
The session is a thin router, not an author. A message maps to a verb by a small, explicit grammar:

| Nathan types | Session does |
|---|---|
| `AG: <description>` | `gh issue create --repo …/aigranthelper --label needs-scoping` (or `ready-for-agent` if Nathan tags `!ready`) |
| `dispatch GS 170` | runs `/dispatch grantspider 170` (foreground, as today) |
| `answer AG 148: <text>` | runs the `/answer` flow → posts comment, swaps labels |
| `status` | runs `/project-status`, returns the table |
| reply to a `needs-input` push | resolves to the originating issue → `/answer` |

Repo prefixes resolve through `registry.yaml` (the existing `dispatch_target` set), so the grammar needs no separate config.

### 3.3 Channels are adapters (the core is channel-agnostic)
The membrane's core is "turn an inbound request into a routed verb / a filed issue." Telegram is the **first** adapter onto that core; it is not the only conceivable one. Adapters fall into two kinds, and the distinction matters for trust:

- **Interactive channels** (Telegram now; Discord/iMessage available) — push into the *live* control session, are bound to **Nathan** (one chat ID), and may use the full verb grammar (§3.2), including privileged verbs (`dispatch`, `answer`). Trusted because authenticated to the principal.
- **Async ingestion adapters** (a future email inbox, §3.4; webhooks) — feed the filer *without* requiring the live session, come from **outside parties**, and are confined to the lowest-trust verb only: *file a `needs-scoping` issue*. Never dispatch, never answer.

Designing the filer (§4) as the shared convergence point is what keeps this open: a new adapter is a new front-end on the same primitive, not a new system.

### 3.4 Deferred: an email ingestion channel (outside pinging for scoping)
A dedicated inbox (e.g. `scope@…`) that turns inbound mail into `needs-scoping` issues, so people *outside* the estate (or Nathan, async from anywhere) can lob a scoping request into the queue without a chat client. **Captured now, built later (§9 item 10).** Design constraints, fixed here so the rest of the architecture accommodates it:

- **Async ingestion adapter, not a Channel.** Email is not an official Channel type, and an external inbox should *not* depend on the live control session. Implement as a headless IMAP/forwarding **poller** (the Vintner-cron shape — plain Python, runs even when the control session is down) that calls the §4 filer. This also isolates an untrusted surface from the privileged session.
- **Lowest trust, always.** Email-sourced items land **only** as `needs-scoping`, labelled `from:email` (or `from:external`), never `ready-for-agent`, never auto-dispatched. The sender is a stranger until Nathan says otherwise.
- **Abuse-bounded.** Optional sender allowlist; rate limiting; spam/empty filtering; subject→repo routing is a *hint* Nathan confirms at scoping time, never an instruction the system obeys blindly. Body becomes the issue body with the sender recorded.

### 3.5 The operational caveat (stated honestly)
Channels needs the session **running**. Two consequences, each with a mitigation:
- **It can die.** Mitigation — **the session holds no state; all state lives on GitHub.** A restarted control session re-reads open issues and any in-flight epic tracking issue (§5.2) and resumes. *Stateless conductor, durable bus.* Run it under a supervisor (tmux + restart, or the web/desktop session).
- **It costs tokens** to have the model mediate routing. Mitigation — the routing grammar (§3.2) is deliberately mechanical; the model is doing classification, not reasoning, for the front-door path. (A future optimization is a dumb pre-router; out of scope for v1.)

---

## 4. The cross-repo filer (the shared primitive)

A single sanctioned way for any agent to put work into a sibling repo's queue — the generalization of the GS→AG seam from one hard-wired edge to many-to-many. Implemented as a small shared helper (a script in `shared/scripts/` deployed estate-wide, or a thin MCP tool — decided in §9), so the scoped `<repo>-dev` agents can call it without ad-hoc `gh` invocations.

**Contract:**
```
file_cross_repo_issue(target_repo, title, body, *, label="needs-scoping", source_repo, backlink)
  → gh issue create --repo <target_repo>
        --label "<label>,from:<source_repo>"
        --body "<body>\n\n---\nFiled by <source_repo> agent. Origin: <backlink>"
```

- **Default label is `needs-scoping`** (Nathan's choice — ambient lands in his queue).
- **`from:<source-repo>`** label makes cross-repo provenance queryable and lets `/project-status` show "filed by a sibling" items distinctly.
- **The conductor calls the same helper** with `label="ready-for-agent"` and a `depends_on` reference — the *only* difference between the two modes at the primitive level (§2).
- **No agent ever dispatches another agent.** Agents *file*. The conductor or Nathan *dispatches*. This is the load-bearing safety invariant (§5.3).

---

## 5. The Epic Conductor (the new capability)

### 5.1 The problem it solves
Some work genuinely spans both repos with an ordering dependency and a feedback loop. Canonical example — *expose a new grant-entity field end-to-end*: GS must add it to the ontology and publish (additive-first), then AG consumes it; and AG may discover mid-stream that it needs the field shaped differently, sending a correction back to GS. Today Nathan relays every leg of that by hand. The conductor runs it.

Two agents bouncing work at each other with no referee is the field's known failure mode — *"when AI systems start talking to each other… things can get unpredictable."* The conductor exists to make the back-and-forth **bounded, supervised, and human-interruptible.**

### 5.2 State lives on a tracking issue, not in the session
One **epic tracking issue** in OverSteward (GitHub native sub-issues), holding everything:

```
EPIC (OverSteward #N): expose `funder_ein` field end-to-end
  goal: AG match results carry funder_ein, sourced from GS ontology
  acceptance:
    - [ ] GS research schema exposes funder_ein (additive)
    - [ ] research_schema.lock bumped + AG pin updated
    - [ ] AG reader returns funder_ein; surfaced in match output
  max_rounds: 3            # hard ceiling on back-and-forth round-trips
  legs:
    - leg 1  GS   add funder_ein to ontology (additive)        [ready]
    - leg 2  GS   publish + bump research_schema.lock           [blocked-by 1]
    - leg 3  AG   consume funder_ein in reader + surface         [blocked-by 2]
```

Each leg is a child issue in its repo, linked `blocks`/`blocked-by`. The conductor session holds **no** epic state — it reads it from this issue every tick (verification doctrine: never trust memory). A dead session resumes from here.

### 5.3 The loop
```
1. Read the epic issue. Find the next leg whose depends_on are all done and status == ready.
2. /dispatch <leg.repo> <leg.child_issue>          # foreground, Max sub, isolated worktree — exactly as today
3. On MERGED:
     - check the leg's box on the epic issue
     - flip dependents blocked → ready
     - if the merged work revealed a NEW requirement for the sibling,
       the working agent files ONE new leg back via the §4 helper        # the back-and-forth
       (this consumes one of max_rounds)
4. On STOPPED_FOR_INPUT (either repo):
     - FREEZE the whole epic, PushNotification to Telegram, wait for /answer
5. Terminate when: all acceptance criteria checked  OR  max_rounds hit  OR  Nathan halts.
     - push a summary either way
```

### 5.4 The three rails (why it can't run away)
1. **Bounded rounds.** `max_rounds` caps the back-and-forth. Hitting it does not loop silently — it escalates to Nathan with a push. (A loop with no ceiling is the single most expensive failure mode; this is the throttle.)
2. **No agent dispatches another agent.** Agents only flip labels / file legs on the bus (§4). The *conductor* reads the bus and dispatches the next leg. One referee, one throttle point — and it keeps dispatch foreground-only (#47936 stays dodged; nothing is spawned in the background).
3. **Acceptance criteria are checked by the conductor, not self-declared** by the working agents. A leg merging is necessary, not sufficient; the epic closes only when the conductor confirms the criteria.

Plus the **human circuit-breaker**: any `needs-input` on any leg freezes the entire epic and pushes to Nathan. Coordinated autonomy never means uninterruptible autonomy.

### 5.5 Relationship to existing pieces
- The GS→AG `repository_dispatch` wire becomes **one edge** in a conductor DAG, not a special case.
- A conductor "leg" is just a `/dispatch` — same agent, same billing, same worktree isolation. The conductor adds only *sequencing, a referee, and a budget*.
- This is [LangGraph's StateGraph](https://www.augmentcode.com/tools/open-source-agent-orchestrators) idea (a supervised state machine over a task DAG) implemented on the estate's own substrate — no new runtime, human-visible state, reuses `/dispatch` wholesale.

---

## 6. Notifications (the bell)

Replace polling with push, reusing the estate's existing nervous system (and the Vintner's, §Kinship):

| Event | Channel |
|---|---|
| Any leg / issue hits `needs-input` | `PushNotification` (in-session → phone via Remote Control) **and** a Telegram message Nathan can reply to in-thread |
| Conducted epic freezes or completes | Telegram summary + push |
| `needs-input` older than 48h | satisfies the existing success criterion ("no `needs-input` sits >48h unseen") *mechanically*, not by Nathan's memory |

A scheduled delta-digest (only *new* needs-input / stale / CI-fail) is a Phase-3 nicety, shareable with the Vintner's `pipeline-health` push path so the estate has **one** push channel, not two.

---

## 7. Phased rollout

Each phase is independently shippable and ordered by ascending trust. **The membrane alone (Phase 1) kills the copy-paste and the polling** — the conductor is deliberately last because it is the highest-trust piece and benefits from the rest being solid.

| Phase | Scope | Exit criterion |
|---|---|---|
| **0 (this doc)** | Design gate | Nathan approves architecture, two-mode model, names, rollout |
| **1 — the membrane** | Control session + Telegram channel; routing grammar (§3.2); `PushNotification` on `needs-input` | Nathan directs any repo and answers any block **from Telegram**, no window-switching; pushes arrive on the phone |
| **2 — the relay** | `file_cross_repo_issue` helper (§4), deployed estate-wide; `from:<src>` label + `/project-status` surfacing | A GS agent files an AG `needs-scoping` issue with backlink; it appears in Nathan's queue and the status table, untouched by Nathan |
| **3 — the conductor** | Epic tracking-issue schema (§5.2); the loop (§5.3) + three rails (§5.4); run **one** real AG↔GS epic end-to-end | A coordinated epic (e.g. the `funder_ein` worked example) merges across both repos with Nathan blessing the plan once and answering only genuine `needs-input`; max_rounds + freeze both demonstrably fire on a forced case |
| **4 — polish** | Delta-digest push (shared with Vintner channel); dumb pre-router to cut front-door tokens | Optional; adopt only if Phase 1 token cost or notification noise warrants |
| **5 — email ingestion** *(deferred, §3.4)* | A `scope@…` inbox → `needs-scoping` issues for outside pinging. Headless poller, lowest-trust, abuse-bounded | Optional; an outside party emails the inbox and a `from:email` scoping candidate appears in Nathan's queue, untouched |

---

## 8. Risks

- **R1 — Conductor loop / runaway cost.** Two agents ping-ponging burns tokens and wall-clock. *Mitigation:* `max_rounds` hard ceiling (§5.4 rail 1); freeze-on-needs-input; the conductor is the sole throttle point (rail 2).
- **R2 — Cross-repo cascade.** A broken change in A auto-propagates into B. *Mitigation:* ambient mode lands as `needs-scoping` (never auto-dispatched); conducted mode runs only a Nathan-blessed plan; legs still pass Gaudí + CI like any `/dispatch`; mirrors the existing draft-PR human gate.
- **R3 — Control session dies mid-epic.** *Mitigation:* stateless conductor — all state on the GitHub epic issue (§3.3, §5.2); restart re-reads and resumes; run under tmux/web supervision.
- **R4 — Background-agent reliability (#47936).** *Mitigation:* the conductor never spawns background agents; every leg is a foreground `/dispatch` (rail 2). No regression of the foreground-only doctrine.
- **R5 — Telegram as an unauthenticated command surface.** A chat that can create issues and dispatch agents is a privileged surface. *Mitigation:* the Telegram bot is bound to Nathan's single chat ID (allowlist of one); the channel plugin authenticates the session, not arbitrary senders; destructive verbs (dispatch, answer) require the explicit verb grammar, not bare prose.
- **R6 — Front-door token cost.** A model mediating every chat line costs subscription tokens. *Mitigation:* mechanical routing grammar (§3.2); optional dumb pre-router in Phase 4; the high-value paths (conducting, answering) are worth the tokens, the low-value path (issue filing) can be cheapened later.
- **R7 — Two notification systems (Telegram vs Vintner's `pipeline-health`).** *Mitigation:* §6 — share one push channel; the Telegraph carries *agent/dispatch* events, the Vintner carries *pipeline-health* events, but both ring the same bell.
- **R8 — Scope creep into a general orchestration platform.** *Mitigation:* it does exactly three things — route Nathan's word to a repo, let repos file to each other, conduct a blessed epic. No dashboards, no general workflow engine, no per-repo DSL. YAGNI.

---

## 9. Decisions & open questions

**Locked (2026-06-17, by Nathan):**
1. ✅ Front door = **Channels + official Telegram plugin** (running control session), not a standalone bot.
2. ✅ Ambient cross-repo filing **lands as `needs-scoping`** (per-issue gate retained).
3. ✅ **Build the conducted mode** — supervised AG↔GS epic coordination.

**Proposed, pending Nathan:**
4. **System name = "The Telegraph"** (metaphor in header). Alternatives if it doesn't sit right: *The Annunciator* (the manor bell-board — leans toward the notification face), *The Speaking-Tube* (room-to-room voice pipes — leans toward the relay face), *The Footman* (carries notes between houses). The Vintner precedent treats naming as a Nathan decision.
5. **Filer implementation = shared script vs MCP tool (§4).** Recommendation: **start as a `shared/scripts/` helper** (byte-copy-deployed estate-wide, zero new runtime, lints under the strictest deploy target) and graduate to an MCP tool only if the agents need it as a first-class callable surface. Confirm.
6. **Home of the conductor logic.** Recommendation: **OverSteward** `src/oversteward/telegraph/` (broker already lives here; independent of watched repos; same call the Vintner made). Confirm.

**Deferred (not blocking Phase 1):**
7. Whether any *trusted class* of ambient cross-repo issue should auto-promote to `ready-for-agent` (Nathan's third option, "decide later"). Revisit after observing real cross-repo traffic from Phase 2.
8. Delta-digest cadence and whether it shares the Vintner's exact push channel (§6, §7 Phase 4).
9. Always-on hosting of the control session — local tmux vs a web/desktop session vs a Railway-hosted headless session. Decide when Phase 1 bring-up starts.
10. **Email ingestion channel (§3.4) — wanted by Nathan, deferred to a later phase.** A `scope@…` inbox → `needs-scoping` issues for outside pinging. Async ingestion adapter (headless IMAP/forwarding poller, Vintner-cron shape), lowest-trust (`from:email`, never auto-dispatched), abuse-bounded. Sequence as an optional **Phase 5** after the membrane and relay (Phases 1–2) prove the filer convergence point. Decide the inbox provider (forwarding address vs hosted mailbox vs Railway) at build time.

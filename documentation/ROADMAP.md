ABOUTME: OverSteward roadmap — what's been done, what's in flight, what's next, what's shelved.
ABOUTME: Pulls from registry.yaml, OVERSTEWARD.md horizons, MASTER_TODO/TODO_BACKLOG, open issues, script stubs, and recent architectural moves.

# OverSteward Roadmap

**As of 2026-08-10** (second dream-produced reconciliation, OS#231's intent pass). Authoritative for "what we're trying to do, what's been done, and what's next." Pull-based — refresh whenever a horizon item lands or a new one promotes from backlog. **Read §3.8 then §3.7 then §3.6 then §3.5 first** for current state — the June–July 2026 program lives there; §2–§4 cover through early May and some of their "next up" items have since shipped (corrections in §3.5/§3.6). Maintenance of this file is becoming a dream-cycle responsibility (§13.4 intent pass, OS#231); `/refresh-docs` sweeps it monthly as the backstop.

Source files this roadmap consolidates:
- `OVERSTEWARD.md` (vision, two pillars, phase plan)
- `MASTER_TODO.md` (Horizon 1) + `TODO_BACKLOG.md` (Horizons 2-3)
- `architecture.md` §5 recent moves
- Open Oversteward issues (`gh issue list`)
- Script stubs (`scripts/{coordinator,gather,diff,sow,sweep}.py`)
- `IDEA_STORE.md` (parking lot — not a commitment)

---

## §1 What this project is

OverSteward is a **two-pillar steward** for the House of Krupa Claude Code estate:

1. **Governance (sync).** Keep the `CLAUDE.md`, soul, persona, and shared-skill state of all 14 managed contexts aligned with the canonical `shared/` source. Today: manual sync. Goal: scripted with safety gates.
2. **Orchestration (dispatch + visibility).** Send scoped agents to work GitHub-issue queues across the five pickup repos (aigranthelper, grantspider, wphelper, ai-assistants, fiscus). Provide the inbox / status surface so Nathan never becomes the queue bottleneck.

Both pillars share the same posture: **propose, don't impose**. Nathan is the principal; OverSteward is the gentleman's gentleman.

**Strategic frame.** OverSteward is the supporting infrastructure for a broader workflow-as-IP thesis: the model is the chip, the workflow is the firmware, the product is the appliance. Customer-facing IP lives in Grant Helper Pro (Sphere I, with Matchmaker as the design lead). OverSteward owns Sphere II (Internal/DevOps — pickup playbook, drift checks, ontology surface, governance sync) and provides the cross-repo plumbing that Sphere I depends on. Full strategic blueprint in [DETERMINISTIC_AGENTS.md](DETERMINISTIC_AGENTS.md).

**Sibling project landed.** [Fiscus](file:///c:/Users/natha/OneDrive/Tech/Python/Fiscus/) (Latin: *imperial treasury* — "our learning is our treasure") was scaffolded 2026-05-14 as the dedicated observation-and-kaizen platform — separate repo, peer to OverSteward and aigranthelper, multi-subject scope, six subjects registered (ghp-matchmaker, ghp-general, dispatch, grantspider-crawler, research-drift, fiscus-meta). All five open questions from [captures/kaizen-architecture.md](captures/kaizen-architecture.md) §9 resolved. Two AG issues filed for the producer side ([aigranthelper#514](https://github.com/NathanKrupa/aigranthelper/issues/514) feedback button, [aigranthelper#515](https://github.com/NathanKrupa/aigranthelper/issues/515) general telemetry endpoint). Now registered in `registry.yaml` and `architecture.md` §1.

---

## §2 Done — Phase 1 (Governance foundation)

Complete since 2026-02-26. Captured in `Stewards_Ledger.md` session log.

- All 14 contexts registered in `registry.yaml` (5 local VS Code + 2 Obsidian + 7 GitHub-only).
- Canonical souls deployed: `chestertron.md`, `macgregor.md`. MacGregor soul-protected — never leaks.
- Canonical personas deployed: `angelico.md` (Creative Director), `herald.md` (Marketing Counselor).
- `~/.claude/shared/` deployed working copy populated and stable.
- `@file` import composition working in Home_Obsidian, GH_Obsidian, all VS Code repos.
- `[oversteward:managed]` / `[oversteward:local]` ownership markers in all migrated `CLAUDE.md` files.
- First manual sync check ran 2026-02-26 → `reports/2026-02-26.md`. All 6 local contexts pass.
- Skill distribution wired: `shared/skills/create-todoist-task.md` → 9 contexts.
- `billions` David-soul exception captured as `soul_in_local: true` registry field.
- Registry schema v2 pinned in `documentation/registry-schema.md`.

---

## §3 Done — Phase 2 (Orchestration shipping)

Heavy delivery between 2026-04-15 and 2026-05-07. Center of gravity moved here.

### Dispatch surface (now in mid-life)

- `/dispatch <repo> <n>` — scoped subagent worker (PRs #4, #5, #9–#19, #23–#27).
- Four repo-scoped subagents in `shared/agents/`: `aigranthelper-dev`, `grantspider-dev`, `wphelper-dev`, `ai-assistants-dev`.
- Universal playbook v1.9 (`.claude/skills/dispatch/playbook.md`) — 19 steps, worktree isolation, structured YAML final report, harness-dropped detection, baseline-snapshot pattern, full-suite test gate.
- Self-critique gate (PR #4) — pre-PR coherence audit against past failure modes.
- `dispatch-paused` kill-switch (PR #15) — repo-level abort if a paused issue is open.
- Worktree non-negotiables hardened (PRs #18, #19, #24, #25) after grantspider #426 / #538 / #543 postmortems.
- **In-session pickup the default since 2026-05-06.** `/dispatch` retired in `architecture.md` §5; workflow content survives as `documentation/issue-to-pr-workflow.md` and `documentation/repos/*.md`. Driven by Anthropic Claude Code harness silent-termination bug (#47931 / #47936) and the April 2026 metered-Managed-Agents launch — in-session work on the existing Max subscription is the cheapest reliable path. The skill files are still on disk pending a deliberate retirement PR.

### Visibility surface

- `/project-status` — Python-backed (`scripts/project_status.py`), four-repo parallel fetch, ~2-3s runtime. 30-day metrics + stale `needs-input` counter (PR #13). Scoping surface folded in (PR #10) — surfaces oldest unscoped issue per repo when ready queue thins.
- `/questions` — ad-hoc list of `needs-input` issues across all dispatch targets, flags >=48h items.
- `/answer <repo> <n>` — GH-native per-issue reply (PR #16). Replaced retired Inbox round-trip (`/morning-digest` + `/answer-flow` removed H1-5).
- `data/pipeline_history.jsonl` — daily snapshot row per repo.
- `data/tool_registry.md` — generated catalogue for "what tools live where" (universal pattern across pickup repos; `scripts/tools/generate_tool_registry.py`).

### Cross-repo data contracts (oversteward-owned governance artifacts)

- `documentation/data-contract-grantspider-aigranthelper.md` v1.2 (PRs #17, #20, #28, #30) — producer/consumer surface, snapshot/cache distinction, dual-write rules.
- `architecture.md` (PRs #21, #22, #31, #35) — machine-readable cross-repo state snapshot (§3 invariants, §4 known liabilities, §5 recent moves). Scope/plan-time read.

---

## §3.5 June 2026 — Sphere II expansion (reconciled by the first dream cycle, 2026-06-24)

> §2–§3 cover through early May. The center of gravity since has been a wave of
> Sphere-II (internal/DevOps) capability. This section is the intent-reconciliation
> pass's output: intent → built → in-flight, plus the started-not-landed gap.

### Shipped (June)

- **The Telegraph** — one Telegram chat (`@KrannocBot`) as Nathan's single front
  door to every repo, ending copy-paste-between-windows. Operator skill
  (`/telegraph-operator`), cross-repo issue relay, two-mode trust (ambient
  needs-scoping vs conducted per-plan). Validated 2026-06-18 running a full
  multi-repo dev day from his phone. **Deaf-detector watchdog (PR#116) merged
  2026-06-24.** Nathan's favorite invention.
- **Sleep-time consolidation (the dream cycle)** — cold-path session→memory +
  nightly reconciliation. Design PR#94; engine components a–d merged
  (#106/#108/#110/#112/#113); `steward-memory` private repo is the git-tracked
  memory source-of-truth, deployed to `~/.claude` by `scripts/deploy_memory.py`.
  **First full cycle ran 2026-06-24 — this refresh is its output.**
- **OverSteward became a dispatch target** (#100) with an `oversteward-dev` agent
  (pytest + gaudi gates, no CI/ruff). Now appears in `/project-status` + `/questions`.
- **exchequer** — private back-office counting-house (cost/MRR ingestion via
  `exchequer pull`, CSV ledgers, monthly close; zero LLM tokens at runtime).
  Created 2026-06-08; GA4 + Anthropic/Stripe/Neon/Railway seams.
- **The Vintner** — runtime pipeline-health monitor for Grant Helper Pro; design
  approved PR#71, read-only Neon roles live on both projects; Phase-1 spine in build.
- **WSL2 port** — all 7 repos migrated to WSL2; uv adopted in Fiscus/Gaudi/
  OverSteward; OneDrive copies dormant. WSL-resilience process added after the
  2026-06-17 update-wipe (integrity gate + safe-update-with-rollback + backups).
- **Estate-wide git hygiene** — merge-commit-only locked on all 6 code repos
  (2026-06-19; squash+rebase off); session-per-worktree discipline (guard hook +
  `new-session.sh`); `sync_repos.py` (#92) keeps dev checkouts current; GS
  master→main rename with `main ⊆ staging` invariant.

### Started, not yet landed (the gap to watch)

| Item | Where | State |
|---|---|---|
| Telegraph Epic Conductor (Phase 3) | OverSteward | scoped, supervised multi-repo epic execution; not built |
| Dream-cycle trigger (component e) | OS#114 | engine exists; nothing fires it automatically — today's cycle was hand-run |
| The Vintner Phase-1 spine | OverSteward | design approved (PR#71), implementation in progress |
| GS Tuesday-night enrichment trigger | GS#1526 | in-session trigger filed 2026-06-24 |
| GS enrich-drain counter bug | GS#1525 | `totalApplied` undercount filed 2026-06-24 |
| Memory SoT write-back | steward-memory | hot-path writes land only in deployed `~/.claude`; the dream cycle reconciles each run (did 2026-06-24), but there is no automatic between-cycle write-back |

### Stale-but-now-true corrections to §2–§9 below

- §5 listed `/sync-status` and `scripts/gather.py` as "next up" — **both shipped.**
- §1's "five pickup repos" is now **six** (oversteward added as a control-plane
  pickup target, #100) plus **exchequer** as a seventh dispatch target.
- §7's "Phase 2 governance scripts stubbed" liability has partially cleared
  (gather + sync-status exist; diff/sow still pending).

---

## §3.6 July 2026 — hardening + the dream grows hands (reconciled 2026-07-26)

> Second reconciliation pass, hand-run. The June §3.5 wave built Sphere-II
> capability; July's center of gravity was **hardening** (security, credential
> hygiene, budget discipline) and **completing the dream cycle's Phase 1**.
> The trigger for this pass: Nathan caught the roadmap a month stale — the
> §13 reconciliation passes were designed but never built (epic OS#230 now
> tracks building them; OS#231 intent/roadmap pass, OS#232 ought-vs-actual).

### Shipped (late June–July)

- **Happy adopted as the phone connection; Telegram removed entirely**
  (Nathan-law 2026-07-02, reversing the pilot-don't-replace verdict). Transport
  + machinery out (#180), `telegraph-operator` slimmed to a transport-agnostic
  skill (#184). The Telegraph *membrane* survives; the bot does not. Open:
  OS#193 (self-host the relay — currently on Happy's public relay).
- **Dream cycle Phase 1 complete and running.** Trigger component (e) shipped
  (OS#114 closed: sign-off primary + Stop-hook + cron backstop). Split-brain
  memory store reconciled onto git-backed `steward-memory` with the harness
  path symlinked in (OS#195) — this also closes §3.5's "memory SoT write-back"
  gap row. Standing-Orders memory architecture per Nathan-law: dream-generated
  two-axis tiers + strict classifier (OS#203), laws gate (OS#206), graveyard
  gate (OS#208), durable FlaggedStore open set (OS#134). Cycles run routinely
  (last: 2026-07-25).
- **Security wave — estate red-team process** (epic OS#219): Tier-1 secret-scan
  gate (gitleaks) wired estate-wide with `/sync-status` drift check (OS#221);
  linked-worktree scans fail closed (#225-fix); estate **secrets registry** +
  new-secret process (`documentation/secrets-registry.md`, OS#224); custom
  gitleaks rules (WP app-passwords); Cloudflare API/purge tokens registered.
  Guard-hook family: read-only Neon deny-by-default (#196), destructive-command
  guard (#176), hook-evasion hard-deny + untrusted-issue boundary (#173).
  Open: red-team Phase 0.5 excavation (OS#220), Phase 2 `/red-team` harness
  (OS#222), estate-wide hook registration (OS#192, OS#182).
- **The Vintner is live** — Phase-1 spine shipped: read-only `vintner_reader`
  role, `corpus_funnel_v` view, `/pipeline-status` skill (counts, coverage,
  velocity, AG-visible gap). Post-ship fixes: schema-drift verdict (#215 PR),
  stage-10 freshness keying (#216). Open: alerting layer (OS#229), batch-cadence
  freshness mis-flags (OS#218).
- **CLI connection standard** (OS#200) — GA4/GSC/Railway/Sentry/Neon connect
  via CLIs, not MCP servers (transport churn); canonical reference in
  `shared/references/cli-connection-standard.md`.
- **Dispatch surface now seven targets** — exchequer (private counting-house,
  created 2026-06-08) and OverSteward itself both dispatchable; registry list:
  aigranthelper, grantspider, wphelper, ai-assistants, fiscus, exchequer (+
  oversteward-dev for this repo).
- **Sphere I context (GS/AG, for the gap table):** GS Part XV backfill complete
  (~89k accepts-unsolicited signals); `funding_profile` mass-run producer merged
  (GS#1936/#1938), run paused at ~72.7k of ~136k by the **Neon budget freeze**
  (serve-only through 2026-07-31; resume + Dagster un-pause 2026-08-01). AG SEO
  epic (AG#1254) Phase 0 staged; edge-cache rollout (AG#1255) queued behind the
  enrichment full run per Nathan's no-cache-fill ruling.

### Corrections to §3.5's gap table

| §3.5 row | Now |
|---|---|
| Dream-cycle trigger (component e) | **shipped** — OS#114 closed |
| The Vintner Phase-1 spine | **shipped** — `/pipeline-status` live; alerting is the open half (OS#229) |
| Memory SoT write-back | **resolved** — OS#195 symlink cutover; one physical store |
| Telegraph Epic Conductor (Phase 3) | **parked** — Telegram removal + Happy adoption changed the substrate; re-scope only on demand |
| GS #1525 / #1526 | not re-verified in this pass — check on next sweep |

### Started, not yet landed (July watch-list)

| Item | Where | State |
|---|---|---|
| Dream Phase 2 — reconciliation passes | OS#230 (epic), OS#231, OS#232 | intent/roadmap pass in build 2026-07-26; ought-vs-actual queued |
| Red-team Phase 0.5 + Phase 2 | OS#220, OS#222 | filed, undispatched |
| Estate-wide guard-hook deploy | OS#192, OS#182 | hooks live in OverSteward only |
| Vintner alerting layer | OS#229 | report spine exists, alerter unbuilt |
| Happy relay self-host | OS#193 | on public relay; Tailscale plan filed |
| Neon unfreeze ritual | memory (2026-08-01) | resume mass-run + re-enable Dagster + merge GS#1941 |

---

## §3.7 Late July–August 2026 — the dream reconciles itself (reconciled 2026-08-02)

> First reconciliation produced BY the dream cycle rather than by hand — OS#231's
> intent pass, built in the previous wave, running on its own output. The period's
> center of gravity was **the byte-copy family growing teeth**: `/sync-status`
> learned to audit the whole canonical `shared/scripts/dev/` set against each
> repo's origin ref, and the format gates closed the residue gap that had been
> failing CI on merges nobody had touched.

### Shipped (2026-07-28 → 08-02)

- **The canonical-family audit is real** (#242 → PR #257, #241 decision recorded).
  `/sync-status` now reports every member of `shared/scripts/dev/` per repo as
  present-identical / drifted / absent / absent-but-doctrine-referenced, compared
  against each repo's **origin default branch** rather than the stale local
  checkouts — which is what let real drift slip past the old check. The
  formatter-exclusion decision (#241) is recorded in the byte-copy treaty so
  Python members can finally be byte-identical across repos with differing ruff
  line-lengths. Skill doc followed in PR #258.
- **Format gates: the formatted bytes are now the committed bytes** (#78 → PR
  #259). `format_staged.py` + `require_formatted_commit.py` joined the canonical
  family, so `verify` can no longer certify unformatted bytes — the exact
  residue that had been red-lighting CI on unrelated merges.
- **The worktree wrong-source trap is guarded and deployed** (#249 → PR #254,
  #240, #255 → PR #260). `new-session.sh` prints the *worktree's* PYTHONPATH
  rather than the primary checkout's (a `$PWD` expansion-timing bug with two
  consumers wanting opposite behaviour), `check_worktree_imports.py` is canonical
  and now byte-deployed into OverSteward itself, and `.envrc`/`.venv` are
  gitignored so session trees stop carrying strays.
- **Dream step 5 unblocked** (#250 → PR #256). The roadmap probe expanded to an
  invalid `cycle roadmap` command; it is a top-level `roadmap` subcommand. This
  section exists because that one-word fix landed.
- **The AG+GS audit capture is on master** (#243) — the four-Fable-auditor
  path-to-1000-customers audit, previously stranded in an unmerged worktree.
- **Dispatch heartbeat push reinstated** (#239) — foreground agents are not
  crash-safe, so the heartbeat commit is insurance the foreground move had
  wrongly retired.

### Corrections to the §3.6 watch-list

| §3.6 row | Correction as of 2026-08-02 |
|---|---|
| Dream Phase 2 — reconciliation passes | **Intent/roadmap pass LANDED and self-hosting** (OS#231 closed; this §3.7 is its first output). Ought-vs-actual (OS#232) still queued. |
| Neon unfreeze ritual | Superseded by the GS#1989 triage: eight of nine failing prod jobs fail **100%** of runs, so the fleet needs repair before any unfreeze reasoning applies (GS#2004–#2009). |

### Started, not yet landed (August watch-list)

| Item | Where | State |
|---|---|---|
| Canonical family drifts *upward* from its own home | OS#261 | canonical test members are strict subsets of OverSteward's own copies — every other repo runs the weaker suite |
| Commit-time gates not actually installed | OS#244, #246, #247 | `core.hooksPath` points at a nonexistent `.githooks`, so `.pre-commit-config.yaml` never runs; three PRs open since 07-29 |
| Routines + `/goal` harness adoption | OS#252, OS#253 | filed; #252 gated on the Max-vs-metered billing question |
| Guard hook vs env-mutating uv in a shared-venv worktree | OS#248 | needs-scoping |
| `/corrections` operator skill | OS#251 | the living-channel keystone (AG#1351) landed; the operator triage skill has not |
| Estate-wide guard-hook deploy | OS#192 | still OverSteward-only — carried unchanged from §3.6 |

> **Unfiled intent spotted in transcripts** (flagged, not filed, per OS#230
> decision 2): the B2 backup **drill** failed its first monthly slot, so the
> restore path is unverified estate-wide — the highest-consequence untracked item
> seen this period.

---

## §3.8 August 2026 — the estate starts opening its own defects (reconciled 2026-08-10)

> Second dream-produced pass. The period's center of gravity was **turning the
> session's opening minutes into a drain**: two deterministic session-start
> sweeps now run before the day's work — `/kaizen` (one recurring process defect,
> OS#332) and `/sentry-triage` (one production-error queue, OS#338). Both were
> built on the same shape, deliberately: a pass and not a gate, Nathan's assigned
> work first, a recorded verdict or the queue never drains, and an exit code that
> distinguishes "I found nothing" from "I could not look."
>
> The forcing evidence: the 2026-08-08 trajectory analysis found **nine error
> classes recurring across 9–11 distinct PRs each**, every one already written
> down in a note that nothing read. The lesson loop was severed at the read end,
> not the write end.

### Shipped (2026-08-03 → 08-10)

- **The kaizen session-start pass is live** (OS#332 → PR #333, #335). Ranks
  recurring-lesson clusters by measured recurrence out of Fiscus, plus
  `kaizen`-labelled issues; `kaizen resolve` records the verdict that retires an
  item (`promoted`/`declined`) or keeps it queued (`deferred`). `kaizen next`
  exits **2** on an empty pattern report over a large corpus — a broken
  instrument, never a quiet backlog. Wired into CLAUDE.md as the first act of
  every session.
- **The Sentry queue is a swept queue** (OS#338 → PR #340; OS#339 → PR #342).
  Deterministic zero-LLM sweep + `/sentry-triage` skill + session-start wiring;
  steady state is inbox zero on *issues*, not zero events, with every issue
  fixed, filed, or resolved-with-reason. A weekly systemd backstop runs the sweep
  headless. The 2026-08-10 queue was canonicalized into `MASTER_TODO.md` (PR
  #337) and the GS Sentry DSN recorded in the secrets registry, replacing a
  folklore line (PR #336).
- **The trajectory-promotion pass closes the lesson loop** (OS#325 → PR #331).
  Monthly dream pass that promotes recurring trajectory lessons into doctrine —
  the write-end complement to kaizen's read end. With the intent/roadmap pass
  (OS#231) this is the second of Phase 2's reconciliation passes to land; only
  ought-vs-actual (OS#232) remains.
- **The dream cycle became operable unattended** — `dream-cycle.service` names
  the Claude CLI by absolute path (OS#341 → PR #343), after the systemd `--user`
  PATH swallowed the bare `claude` invocation exactly as it had for the retired
  Telegraph supervisor unit (OS#119). The durable `flagged.jsonl` open set was
  migrated to the current schema in place this cycle; the round-trip defect that
  drops holds is still open (OS#334).
- **The worktree-discipline family reached its hardened form.** Per-worktree test
  databases (OS#276 → PR #277); teardown that destroys **last** and finds *every*
  database a worktree owns (OS#283, #286 → PR #290); refusal when the derivation
  is missing rather than a silent green (OS#305 → PR #311); never deleting a
  *tracked* `.envrc` (OS#308 → PR #310); and an orphan `sweep` that reconciles
  container databases against live worktrees (OS#296 → PR #301) after seven
  unnameable databases accumulated in one grantspider evening.
- **The guard hooks stopped being fooled by shell syntax.** `guard_shared_venv`
  now matches uv verbs by lexing rather than raw text (OS#267 → PR #271), refuses
  bare `uv run` because the implicit sync *is* the capture path (OS#294 → PR
  #295), and treats a backtick as a command position (OS#298 → PR #303); both
  regex guards — including the class-1 hard deny — are anchored at command
  substitutions (OS#302 → PR #306), and `_DB_CLIENT` sees a client inside one
  (OS#307 → PR #312).
- **Commit-time gates are installed, not merely configured** (OS#244, #246). The
  gaudi gate was scoped, installed and cleared, and the CI watchdog sits behind
  the commit-time gate — closing §3.7's "`core.hooksPath` points at a nonexistent
  `.githooks`" row.
- **Agent cards were re-verified against origin, and taught to stop asserting
  what rots** (OS#309 → PR #314, plus #300, #315, #316) — pip-in-a-uv-repo, a
  wrong Postgres major, an omitted docs-only CI passthrough, and AG's app DB
  misrecorded as Neon rather than Railway Postgres.
- **The docs-author agent shipped** (PR #319, #320, #321) — a client-facing
  help-centre author writing drafts only, with documentation reframed as a **UX
  triage instrument**: what is hard to document is usually hard to use.
- **Sphere I context (GS/AG, for the gap table):** the GS website-contamination
  arc closed end-to-end — diagnosis (GS#2160), resolver gates in the enrich drain
  (GS#2169), and cleanup applied to production (GS#2164, #2171, #2178), repairing
  **5,708 websites, 2.72M links, and 15,940 chunks**. The Haiku website verifier
  (GS#2172, #2173) was built, promoted, and is running. AG's documentation run
  wave 1 closed eight issues (AG#1472, #1480, #1490, #1506, #1512, #1516, #1517,
  #1527).

### Corrections to the §3.7 watch-list

| §3.7 row | Correction as of 2026-08-10 |
|---|---|
| Commit-time gates not actually installed (OS#244, #246, #247) | **resolved** — #244 and #246 merged; #247 closed, superseded by the guard-hook work |
| Guard hook vs env-mutating uv in a shared-venv worktree (OS#248) | **shipped** — PR #264, then hardened four times (OS#267, #294, #298, #302) |
| Canonical family drifts *upward* from its own home (OS#261) | unchanged — still open; canonical test members remain strict subsets of OverSteward's own copies |
| Routines + `/goal` harness adoption (OS#252, #253) | unchanged — filed, undispatched |
| `/corrections` operator skill (OS#251) | unchanged |
| Estate-wide guard-hook deploy (OS#192) | now measured — OS#304 names the specifics (GS lacks `guard_shared_venv`, AG wires no hooks at all); still OverSteward-only |
| **Unfiled B2 restore-drill flag** | **filed and closed** — GS#2009 covered `backup_drill` among four failing prod jobs (closed 2026-08-04). Residual: a per-DB backup failure still fails green (GS#2122, open) |

### Started, not yet landed (August 10 watch-list)

| Item | Where | State |
|---|---|---|
| Dream Phase 2 — ought-vs-actual pass | OS#232 (epic OS#230) | the last unbuilt reconciliation pass; intent/roadmap and trajectory-promotion both live |
| Dream flagged-set integrity | OS#334 | schema migrated in place this cycle; the migration round-trip still drops holds |
| Memory retrieval | OS#324 | capture works, retrieval does not — two facts were in the store and neither reached the session that needed them |
| Trajectory tagging | OS#329 | 52% of lessons untagged — this is the *input quality* of the kaizen queue |
| "A check that reports success must prove it can fail" | OS#327 | the canary law, generalized from kaizen's and sentry-triage's exit-2 rule; doctrine not yet written |
| Agent-card rot | OS#328, OS#270 | cards corrected this wave; the mechanism that rots them is untouched |
| Guard family estate-wide | OS#304, #192, #182, #272 | still OverSteward-only; OS#272 also carries the raw-text false-positive sweep |
| Credential-hygiene hook gap | OS#323 | `railway variables --kv` slipped a private key through a filtered pipeline |
| Estate-wide uv transition | OS#318 | GS CI is still 27 pip installs and a pip-era lock |
| GS worktree doctor unreachable | OS#322 | the checkout that owns the worktrees cannot reach the doctor |
| Tool-registry drift guard | OS#274 | generator discovery still rglob, not `git ls-files` |
| Red-team Phase 0.5 + Phase 2 | OS#220, OS#222 | carried unchanged from §3.6 |
| Vintner alerting layer | OS#229 | carried unchanged — report spine exists, alerter unbuilt |
| Happy relay self-host | OS#193 | carried unchanged — still on the public relay |

---

## §3.9 Mid-August 2026 — telling "down" from "quiet" (reconciled 2026-08-17)

> Third dream-produced pass. The week's through-line was **closing the gap
> between a clean report and a healthy estate**: Sentry inbox zero coexisted for
> two days with a CRASHED embedding service (no error event, no finding), a
> silently dead CI watchdog let a poisoned-index commit gut `master`, and a
> valid fast-forward pull rewrote the wrong trunk three times in one evening.
> Each got the same treatment as kaizen/sentry before it — a deterministic
> instrument whose exit codes distinguish "I measured nothing wrong" from "I
> could not look."

### Shipped (2026-08-11 → 08-17)

- **The liveness sweep is the third session-start pass** (OS#353 → PR #354).
  `service_liveness.py` reads every `registry.yaml` context carrying a
  `railway:` block and reports services that are down or unclassifiable —
  because a crashed Railway service emits **no Sentry issue at all**, and
  GrantSpider's `embedding` sat CRASHED for two days behind a clean triage
  sweep. A clean result names the count it checked ("all 20 accounted for");
  a project that cannot be read fails the whole sweep.
- **Trunk discipline became mechanical** (PR #346, #347, #348). `git pull
  <remote> <ref>` merges into whatever branch is *checked out* — a valid
  fast-forward, exit 0, no warning — which moved grantspider's `main` onto a
  staging commit three times in one evening. Now: `guard_trunk_pull.py`
  refuses the dangerous shape on a protected branch (defence in depth);
  `sync_repos.py` reads `primary_branch` from registry.yaml, repairs a
  stranded trunk when provably lossless (`git rev-list <branch> --not
  --remotes`), and runs nightly; and the doctrine "the primary checkout tracks
  what production runs — not the repo's default branch" is written down with
  the AG/GS table. Rollout to the remaining repos is OS#350.
- **The master tree was gutted and restored** (PR #366; OS#365 closed). PR
  #361's poisoned-index commit shipped a silent mass deletion of the tracked
  tree, and the CI watchdog that should have caught it was itself dead —
  GitHub Actions had silently stopped consuming events, so PR #361 got no CI
  run despite healthy triggers. The tree was restored and the
  read-git-status-unfiltered / compare-changedFiles-to-intent habit entered
  memory. The GIT_* scrub that PR #361 carried (hook-exported `GIT_DIR`
  hijacking `git -C`) survived the restore; its test residue is OS#363.
- **Inert controls entered doctrine** (PR #351, then PR #368). A guard the
  passing state shares with the forgotten state is not a control: fail closed
  and force a recorded decision in the same diff (grantspider#2101), and a
  prohibition is inert while the same document still prescribes the forbidden
  form (OS#297). The kaizen pass then promoted its 5×-recurrence cousin:
  a canonical byte-copy family's formatter exclusion lands **in the same diff
  as the family's first deploy**, never as a follow-up.
- **The byte-copy family audit got honest about its own blind spots** (OS#357
  → PR #359; OS#355 → PR #356). Fiscus is now tracked in the family (two venv
  captures had gone undetected because the doctor was never deployed there),
  a dead `local_path` reports as drift rather than silently vanishing from
  the audit, and the credential-hygiene hook allow-lists the loopback
  test-bench URL shapes it had blocked five measured times in GS.
- **Sphere I context (GS/AG, for the gap table):** the fiscal-synopsis arc
  promoted to GS `main` and its prod migration applied under the delegated
  arm; the promote→apply gap crashed the daemon-watchdog and the fix shipped
  same-day (GS PR#2263 — `tolerate_behind` for the watchdog entrypoint only;
  DB-ahead stays a hard refusal everywhere). The NTEE backfill closed **by
  vacuity** — the joinable cohort was already drained, and the remaining
  1.33M uncoded grants are structurally uncodable or absent from a BMF
  snapshot that may be filtered (GS#2256). AG's pin-bump bot was caught
  regenerating the model mirror under pip against a uv.lock world (AG#1579
  ruling: regenerate under the lock; Django 6.1 held for Nathan), and the
  Grant Studio ↔ Applications bridge was filed (AG#1583). The locked
  fiscal-synopsis sample PDF is committed as the format reference (PR #367).

### Corrections to the §3.8 watch-list

| §3.8 row | Correction as of 2026-08-17 |
|---|---|
| Dream flagged-set integrity (OS#334) | still open, and now measured twice — OS#345 adds that finalize crashes outright on pre-refactor holds |
| Guard family estate-wide (OS#304, #192, #182, #272) | one new member (`guard_trunk_pull`, PR #347) born OverSteward-only like the rest; rollout is OS#350 |
| Tool-registry drift guard (OS#274) | widened into OS#358 — 4 registries months stale, the generator family drifted to 5 distinct hashes, no automated cadence |
| Agent-card rot mechanism (OS#328, #270) | unchanged, and OS#360 adds a rotted doctrine row (the branch table said AG's default is `main`; it is `staging`) |
| Kaizen input quality (OS#329, #352) | unchanged — and OS#352's degraded-detector confidence gap remains open against the exit-2 law |
| All other rows | carried unchanged (OS#232, #324, #327, #323, #318, #322, #220/#222, #229, #193) |

### Started, not yet landed (August 17 watch-list)

| Item | Where | State |
|---|---|---|
| Dispatch subagents hang on settings.json writes | OS#364 | hook-registration work must become operator-only |
| GIT_DIR-exported test failures | OS#363 | 18 OverSteward-local tests fail; no gate exercises the class |
| Canonical test_worktree_guard gaudi debt | OS#362 | +5 findings over fiscus's copy — clean at source, then converge |
| Branch-table doctrine rot | OS#360 | AG default branch is `staging`, docs say `main` |
| Tool-registry regeneration estate-wide | OS#358 | subsumes OS#274 context: stale registries + drifted generators + no cadence |
| guard_trunk_pull rollout | OS#350 | OverSteward-only, like every guard at birth |
| Checkout sweep wedged by untracked file | OS#349 | permanent wedge, no override path |
| Dream flagged-set integrity | OS#334, #345 | the migration round-trip drops holds; finalize crashes on legacy holds |
| GrantSpiderFilingAssets B2 bucket | (operator) | account key cannot create buckets; blocks the 130k synopsis render batch |
| Django 6.1 decision | AG#1579 residue | mirror regenerates under the lock now; the bump itself held for Nathan |

---

## §3.10 Late August 2026 — the presses run and the seam goes live (reconciled 2026-08-24)

> Fourth dream-produced pass. The week's through-line was **turning built
> machinery into running production**: the 990-PF facsimile engine finished and
> its 475k-filing drain launched, the 130k fiscal-synopsis corpus completed with
> zero failures, the AG operator seam went from "tokens not minted" to live
> verdicts in production, and the help-centre docs loop closed to a single
> human act (Publish). Alongside it, the kaizen queue drained five items in one
> sitting — the doctrine promotions of the month all trace to measured 4-5×
> recurrences.

### Shipped (2026-08-18 → 08-24)

- **The kaizen quintet drained** (OS#375 → PR #383, OS#327 → PR #385, OS#328
  → PR #387, OS#352 → PR #389 + Fiscus PR#120, OS#329 → PR #390). The
  dispatch playbook now carries the trajectory-note step and a red-proof step;
  "a check that reports success must prove it can fail" entered doctrine with
  a self-audit issue (OS#384); agent cards state the command, not the number
  (rot-resistant form; residue OS#388); `kaizen next` discloses degraded
  clustering above the item and marks counts UNMEASURED; and trajectory
  `[category]` + `promote:` tags are enforced at commit time, forward-only
  (mutation-proven red 19 ways). Three sibling doctrine promotions rode the
  same week from 4×-recurrence clusters: a merged watchdog is not a live
  watchdog (PR #370), an invariant-asserting comment is security surface
  (PR #371), a regression test never seen red is not a regression test
  (PR #373).
- **Operator steps became a Todoist channel** (PR #372) with the closed
  add-then-verify-then-done loop, and the metered-API law got a fail-closed
  guard (OS#376 → PR #377): `grantspider enrich` and friends refuse from a
  Claude session unless explicitly armed.
- **The AG operator seam is live end to end** (OS#392 → PR #393, fix #394 →
  PR #395; producer epic AG#1719). `ag_ops_triage sweep` reads the
  `/internal/ops/` reports with honest `scanned` counts; the first production
  sweep surfaced Nathan's own beta comment, filed it (AG#1737), and recorded
  `responded` through the live verdict endpoint — a measured zero on
  re-sweep. The CLAUDE.md sentence describing exit-2-until-tokens-minted as
  "the state today" is now stale (tokens minted; seam answering).
- **The help-centre docs loop closed** (AG side, steered from here). Nathan
  approved AG#1728 — merged help-draft prose auto-applies to CMS drafts on
  promotion (PR#1732), revising the manual-only posture; the screenshot
  harness became self-healing (seed entitlement per run + misroute-goes-red
  PR#1718, viewport clamp PR#1724, per-route browser contexts PR#1727); the
  admin's three-part "published" illusion was fixed (PR#1730). Publish remains
  the one human act, by design. Account-and-billing draft held — its deletion
  section states the opposite of the shipped flow (AG#1715).
- **The 990-PF facsimile engine completed and the drain launched** (GS#2348
  epic, all legs merged 08-21→08-22). The 1,000-filing canary measured
  ~21 filings/min (965 rendered, 35 fidelity-guard refusals = 3.5%, filed
  GS#2376-2378); the full 475,371-filing drain launched 08-23 from a staging
  worktree (~16 days of laptop runtime, ~785 GB B2 ≈ $5/mo). One real bug
  found on the way: the 200 MB buffered-body cap aborted every large TEOS
  archive as a "transient" httpx_error — a deterministic failure wearing a
  transient's coat (GS#2373 → PR#2374, streaming path).
- **The fiscal-synopsis corpus finished**: 130,047/130,047 rendered to B2,
  zero failures. Every foundation with a 990-PF extract has its branded
  synopsis; the one remaining operator click is `RESEARCH_ASSETS_CDN_BASE_URL`
  on the AG web service.
- **Promotion discipline grew a closing step**: promote merge-commits are
  never absorbed back, so the `main ⊆ staging` invariant reddens as promote
  residue — the back-merge (tree-identical, verified) is now part of every GS
  and AG promote (GS PR#2364, AG PR#1736). The Tuesday AG promote also
  surfaced a self-poisoning staging smoke (demo-seeded org with an empty
  Stripe customer re-captures the smoke user every run — AG#1738/#1739), and
  a GitHub Actions billing outage was caught, funded, and verified green with
  real runs.
- **Sphere I measurement:** AG's Google indexation is at its pre-turn
  baseline — 138 impressions/28d, 0 clicks, and 94 of the 97 surfacing
  foundation pages are pre-#1663 thin-page residue rather than the 9,615-page
  enriched cohort (sitemap re-cut submitted only 08-20). Checkpoint
  mid-September: impressions should migrate onto enriched-cohort URLs.

### Corrections to the §3.9 watch-list

| §3.9 row | Correction as of 2026-08-24 |
|---|---|
| GrantSpiderFilingAssets B2 bucket | **resolved** — synopsis + facsimile PDFs share one B2 bucket; the 130k synopsis batch completed through it |
| Kaizen input quality (OS#329, #352) | **both closed** — tag gate merged (PR #390), degraded-mode honesty merged (PR #389 + Fiscus PR#120) |
| Agent-card rot mechanism (OS#328, #270) | OS#328 closed (PR #387); residue OS#388 (aigranthelper-dev `git stash` instruction) and OS#396 (docs-author card contradicts the #1728 world) |
| Dispatch subagents hang on settings.json (OS#364) | carried; new sibling OS#391 (playbook names only one of the two tags the new gate enforces) |
| All other rows | carried unchanged (OS#363, #362, #360, #358, #350, #349, #334/#345, Django 6.1) |

### Started, not yet landed (August 24 watch-list)

| Item | Where | State |
|---|---|---|
| 990-PF facsimile corpus drain | GS `filing_facsimiles` | in flight, newest-first; restarts must launch from the `facsimile-canary` worktree until the next staging→main promote carries PR#2374 |
| AG#1443 — repoint `get_filing_history` to `filing_history_v` | AG | unblocked; the one dispatch that lights the download buttons for everything already rendered |
| Fidelity-guard refusal classes | GS#2376-2378 | 3.5% of filings held; re-enter automatically once fixed |
| Team-flow smoke state leak | AG#1738, #1739 | re-reds the staging smoke every run until dispatched |
| Publish clicks | (operator) | getting-started + finding-funders drafts await the admin Publish action |
| GSC cohort migration | (measurement) | mid-September checkpoint — enriched cohort should displace thin-page residue |
| Telegraph operator watchdog | (unfiled intent) | the operator session can die silently; a systemd user-timer watchdog with a forced-failure test was designed but not filed |
| docs-author card vs #1728 | OS#396 | card claims drafts "never go through a pull request" — PRs are now the draft write path |

---

## §4 In flight

Active or partially-shipped items as of 2026-05-07.

| ID | What | Where | Status |
|---|---|---|---|
| H1-2 | Pipeline metrics on `/project-status` (cycle time, needs-input age, PR success rate, self-critique fire rate) | PR #13 base merged; full issue-creation→merge cycle time excluding `needs-input` stalls (needs timeline-event fetch) and self-critique fire rate (definition undecided) still open | partial |
| Drift check on AG | `research-drift-check` required status check on `main` for aigranthelper | Closed via AG #455 / #275 on 2026-05-07; first-ever green non-skipped run. Required gate now blocks divergent `_generated.py` PRs. | done |
| Dispatch retirement PR | `/dispatch` skill files + four `<repo>-dev` agent definitions still on disk despite in-session being default | Workflow content already migrated to `documentation/issue-to-pr-workflow.md` + `documentation/repos/*.md` (per architecture.md §5, 2026-05-02). Cleanup PR pending. | in flight |

---

## §5 Next up — Horizon 1 residue + Horizon 2 promotion

Pulled from `MASTER_TODO.md` Active and `TODO_BACKLOG.md` Horizon 2.

### H1 residue (cleanup)

- **Finish H1-2.** Add full issue-creation→merge cycle time to `/project-status` (timeline-event fetch); decide what self-critique fire rate counts as a "fire" and add it. Blocking criterion for declaring Horizon 1 "shipped."
- **Retire `/dispatch` skill on disk.** Remove `.claude/skills/dispatch/`, `.claude/skills/answer-flow/`, `.claude/skills/morning-digest/` (already retired in CLAUDE.md), and the four `.claude/agents/<repo>-dev.md` files. Update `registry.yaml` `agents_available` blocks. Companion to the in-session-default decision recorded in `architecture.md` §5 + memory `feedback_in_session_not_dispatch.md`.

### H2 — Regression catalog + scoped governance tooling

- **H2-1 — Regression catalog.** Audit `feedback_*` memory entries (~30 today). Classify per-repo applicability. Emit `shared/agent-playbooks/common-pitfalls.md` (cross-repo) + `shared/agent-playbooks/{repo}-pitfalls.md` (per-repo). Wire each pickup-context briefing to its file. Turns scar tissue into pre-flight checks rather than memory-only knowledge. Highest leverage of any H2 item — every pickup session benefits.
- **H2-2 — `scripts/gather.py`.** Read-only state extraction. For each registry context: read `CLAUDE.md`, extract managed block, compute hash, emit JSON state snapshot. Pure read; no writes.
- **H2-3 — `scripts/diff.py`.** Pure comparison. Take gather snapshot + registry expectations, emit structured change list. Pure compute; no writes.
- **H2-4 — `/sync-status` skill.** Runs gather + diff; presents drift across contexts in human-readable form. Governance's equivalent of `/project-status`. No writes — visibility only.
- **H2-5 — Defer `sow.py`.** Forcing-function gate: hold until a concrete sync task lands that manual sync can't absorb. Avoid building the dangerous-by-construction tool until there's a real demand for it.

### Open Oversteward issues (carried as Horizon 2 candidates)

- **Issue #2 — `/dispatch v2: sweeper agent`.** Scheduled task that clears stuck `agent-in-progress` labels. **Re-evaluate scope**: with in-session pickup as default since 2026-05-06, the original failure mode (crashed background agents leaving stuck labels) is rarer. Either retire the issue, or rescope as a one-shot `/sweep-stuck-labels` skill called manually when a label is observed stale.
- **Issue #3 — `/drain <repo>` skill.** Iterates `ready-for-agent` queue. **Re-evaluate scope**: also predates the in-session default. The new equivalent is "Nathan opens a session and works the queue manually." If we want autopilot, the form should match the new posture (e.g., a session-pickup checklist, not a background drainer).

These two issues are the only open Oversteward GH issues; both predate the dispatch retirement and need a scope decision before implementation. Recommendation: **close-or-rescope pass** rather than a build pass.

---

## §6 Horizon 3 — Compounding capabilities (trigger-gated)

Listed in `TODO_BACKLOG.md`. Each is gated on a real-world trigger, not a date.

- **H3-1 — Governance sow bundle.** Build `sow.py` + `sweep.py` + `coordinator.py` together when H2-5 trigger fires. Safety gates already pinned in `documentation/sow-safety-gates.md`: managed-block-only writes, never touch `[oversteward:local]`, never touch `skip_sow: true`, never inject soul for `soul_in_local: true`, dirty-tree bail, no stacking, dry-run default, lockfile, `oversteward/sync-YYYY-MM-DD` branch pattern, JSONL audit trail.
- **H3-2 — Cross-pillar integration.** When a governance sync detects a rule change affecting a pickup-target repo, append a brief to that repo's pickup context. Closes the loop between governance and orchestration.
- **H3-3 — Analyst persona.** Build via `/create-persona` when triggered by a real Stocks or OpportunityMiner use case. Already drafted in IDEA_STORE notes; deployment slots reserved in registry.
- **H3-4 — Self-critique audit log.** Every self-critique gate result logged to `data/pipeline_history.jsonl`. Monthly review identifies regressions catalogued vs missed.
- **H3-5 — GH Actions scheduled governance sync.** Phase 3 automation — cron/Actions-triggered coordinator. Gated on H3-1 actually existing.

---

## §7 Known liabilities carried by OverSteward

From `architecture.md` §4 — the rows OverSteward owns or shares ownership of.

| ID | Liability |
|---|---|
| H1-2 | Pipeline metrics on `/project-status` not yet fully shipped (cycle time + self-critique fire rate) |
| L-WD-1 | Windows + OneDrive worktree-husk fragility — fresh worktrees can register metadata without populating the checkout. Mitigated by playbook step 4 prune + step 6 viability probe; underlying race remains |
| L-DISP-1 | Branch-protection enforcement absent on private repos (GitHub Free tier). Discipline-only on 7 private repos |
| Phase 2 governance scripts stubbed since 2026-02-20 | Two months without implementation. Either build minimum-viable sow or formally retire the plan (H2-5 forces this question) |
| Partial dispatch metrics | See H1-2 row |

---

## §8 Shelved (parked in IDEA_STORE)

Captured in `IDEA_STORE.md` from gstack research and conversational drift. None on the roadmap; review quarterly. Highlights:

- PreToolUse hooks for managed-block edit warnings (gated on Phase 2 sow being live and managed blocks being effectively read-only).
- Repo mode detection (solo vs collaborative) influencing Chestertron proactiveness per-context.
- Cross-model adversarial review for critical PRs.
- QA skill with real Playwright browser (gated on aigranthelper deployment).
- Telemetry / event log expansion (gated on scale ≥20 repos or multiple users).
- Retro skill (gated on enough volume to justify automation).

---

## §9 Success criteria — what "done" looks like

### Governance pillar

- Nathan develops a skill in any context; it appears in all relevant contexts within one sync cycle.
- No `CLAUDE.md` managed block drifts more than one version behind the shared baseline.
- MacGregor's soul has never appeared in any non-MacGregor context.
- Weekly sync check runs without manual intervention (Phase 3).
- Nathan spends zero time hand-copying instructions between projects.

### Orchestration pillar

- Pickup cycle time (issue → merged PR, excluding `needs-input` stalls) holds at or below a known median.
- No `needs-input` issue sits more than 48 hours without Nathan seeing it (`/project-status` stale counter).
- Ready queue never starves — `/project-status` surfaces scoping candidates before zero-ready state.
- Self-critique catches regressions against documented past failure modes before PR open.
- Full pipeline state visible in one command, under 3 seconds.

---

## §10 Maintenance protocol

- Update §3 / §4 every time a horizon item lands.
- Update §5 when a new item promotes from backlog or an open issue gets a scope decision.
- Update §7 when an architecture.md liability flips on or off.
- If §2-§3 grow past readable length, extract to a `documentation/changelog.md` and keep this doc thin.
- This doc is the single answer to "what are we trying to do, what's done, what's next?" If it can't answer that in under 60 seconds of reading, it's grown past its purpose — restructure rather than expand.

*Last updated: 2026-08-24 (late-August reconciliation — §3.10 added; the kaizen quintet, the live AG operator seam, the facsimile drain and synopsis completion, and the closed docs loop).*

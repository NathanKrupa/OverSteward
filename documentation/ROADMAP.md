ABOUTME: OverSteward roadmap — what's been done, what's in flight, what's next, what's shelved.
ABOUTME: Pulls from registry.yaml, OVERSTEWARD.md horizons, MASTER_TODO/TODO_BACKLOG, open issues, script stubs, and recent architectural moves.

# OverSteward Roadmap

**As of 2026-05-07.** Authoritative for "what we're trying to do, what's been done, and what's next." Pull-based — refresh whenever a horizon item lands or a new one promotes from backlog.

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

*Last updated: 2026-05-07 (covers through Stewards_Ledger 2026-05-07 entry, AG #275 close, in-session-default decision).*

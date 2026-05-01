ABOUTME: The OverSteward project specification and architecture reference.
ABOUTME: Two-pillar system: governance (sync across contexts) + orchestration (in-session work on production repos).

# The OverSteward

**Steward of the House of Krupa's Claude Code estate: keeps every managed context aligned AND coordinates in-session work across the production repos' issue queues.**

> "If one thing is done late, everything will be late." The OverSteward ensures that wisdom earned in one quarter of the estate is not squandered by ignorance in another — and that work is taken up with clear scope, carried through, and never left stranded in a corridor.

---

## Purpose

The OverSteward serves two complementary missions.

### Pillar 1 — Governance (sync)

Keep every managed context's `CLAUDE.md`, souls, personas, and shared skills aligned with the canonical source. Propagate improvements. Prevent drift. Nathan is the only integration layer today, and that does not scale across 14 contexts.

### Pillar 2 — Orchestration (in-session)

Work GitHub issues across the four active production repos (aigranthelper, grantspider, wphelper, ai-assistants) directly in-session, using the canonical [issue-to-PR workflow](documentation/issue-to-pr-workflow.md) and per-repo context docs in [`documentation/repos/`](documentation/repos/). Provide the async ask-answer loop that closes the human-in-the-loop gap. Keep Nathan informed without making him the queue bottleneck.

**Pivot note (2026-05-01):** The earlier model used `/dispatch` to spawn background subagents via the Claude Code Task tool. That codepath suffered the harness false-positive completion bug (Anthropic claude-code #47931 / #47936) — silent termination after fast tool round-trips, no fix shipped, and an apparent strategic nudge toward the metered Managed Agents tier. We retired the dispatch ceremony and moved to in-session pickup. The 19-step workflow, non-negotiables, worktree isolation, and per-repo gotchas all survived the move; the subagent harness layer was the only thing dropped. See [Stewards_Ledger.md](Stewards_Ledger.md) entry for 2026-05-01.

Both pillars share a principle: **Nathan is the principal; the OverSteward is the gentleman's gentleman.** Changes are proposed, not imposed. The system has exactly one escape hatch from its own control — Nathan manages the OverSteward directly (`skip_sow: true`).

---

## Problem Statement

**Governance side:**
- Skills and prompt patterns developed in one context don't automatically appear in others.
- `CLAUDE.md` files evolve independently with no shared baseline.
- Souls and personas have no governance layer — they can be silently overwritten or go missing.
- Manual sync across 14 contexts is past the point where it reliably happens.

**Orchestration side:**
- Four production repos generate more ticket work than Nathan can do without structure.
- Questions raised mid-work without a capture path are effectively abandoned.
- Without a dashboard, Nathan cannot see the pipeline state at a glance.
- Without a scoping surface, the ready queue starves even when the backlog is deep.

---

## Architecture

### Design Principles (both pillars)

1. **Git is the backbone.** All managed repositories are Git-backed. The OverSteward treats them uniformly.
2. **@file imports, not generated files.** Shared content is composed via `@~/.claude/shared/...` at session start. No build step. The shared source files are canonical; each context's CLAUDE.md holds pointers.
3. **Python for mechanics, Claude Code for intelligence.** File gathering, diffing, Git operations, GitHub scans are Python. Analysis, relevance judgments, scoping decisions, and content proposals are Claude Code.
4. **Ownership markers.** Every managed CLAUDE.md has a `[oversteward:managed]` block (OverSteward owns) and a `[oversteward:local]` block (Nathan owns). Sow operations never touch local.
5. **Inheritance model.** `~/.claude/shared/` is the canonical deployed copy. `oversteward/shared/` is the git-tracked source. Scripts sync source → deployed on every run.
6. **Propose, don't impose.** All sync and dispatch operations surface proposals for approval before meaningful state changes.
7. **OverSteward manages others. Nathan manages OverSteward.** One escape hatch from the system's own control.
8. **Issue queue as the task board** (orchestration). `gh issue list` drives the ready queue. Labels drive state. PR merges drive completion. No parallel TODO file for production-repo work.

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      OverSteward Repo                            │
│                                                                  │
│  registry.yaml       ← manifest of all managed contexts          │
│  shared/             ← canonical souls, personas, skills, refs   │
│  contexts/           ← per-context local overrides               │
│  documentation/      ← issue-to-pr-workflow.md, repos/*.md,      │
│                        registry-schema, sow-safety-gates,        │
│                        data-contract                             │
│  .claude/skills/     ← answer, questions, project-status,        │
│                        create-persona                            │
│  scripts/            ← project_status.py, tool registry,         │
│                        Phase 2 sync stubs                        │
│  reports/            ← sync check logs                            │
└────────┬────────────────────────────────────────────────────────┘
         │
         ├─── GOVERNANCE ──────────────────────────────────────────
         │   syncs shared → ~/.claude/shared → @file in each repo
         │
         │    ┌─────────┬─────────┬──────────┬─── ... ──────────┐
         │    ▼         ▼         ▼          ▼                  ▼
         │  Home_Ob  billions  ai-assist   macgregor    14 contexts
         │
         └─── ORCHESTRATION (in-session) ─────────────────────────
             Nathan: "let's work AG #415" (or grantspider 150, etc.)
             session reads documentation/repos/<name>.md +
                 documentation/issue-to-pr-workflow.md
             session runs preflight, scope validation, work, ship
             ambiguity → ask in chat OR post needs-input comment
             /answer <repo> <n> → posts Nathan's reply → resume
             /project-status / /questions → pipeline visibility

             Targets: aigranthelper · grantspider · wphelper · ai-assistants
```

---

## Repository Structure

```
oversteward/
├── OVERSTEWARD.md             # This document
├── Stewards_Ledger.md         # Project status and session log
├── MASTER_TODO.md             # Active work queue
├── TODO_BACKLOG.md            # Deferred work
├── SESSION_STATE.md           # Handoff between sessions
├── CLAUDE.md                  # Instructions for Claude Code sessions in this repo
├── registry.yaml              # Manifest of all managed contexts
├── data/
│   └── tool_registry.md       # Regenerated by scripts/tools/generate_tool_registry.py
├── shared/                    # Git-tracked canonical source (deploys to ~/.claude/shared/)
│   ├── souls/
│   │   ├── chestertron.md     # Primary soul
│   │   └── macgregor.md       # MacGregor's soul — never deploys elsewhere
│   ├── personas/
│   │   ├── angelico.md        # Creative Director
│   │   └── herald.md          # Marketing Counselor
│   ├── skills/
│   │   └── create-todoist-task.md
│   ├── references/
│   │   └── wodehouse.md
│   ├── agents/                # Domain agents (e.g. grant-researcher)
│   ├── templates/
│   └── inbox.md               # Update notifications (cleared on first read)
├── contexts/                  # Per-context local overrides
│   └── *.md                   # One file per registered context
├── documentation/
│   ├── issue-to-pr-workflow.md     # Canonical 19-step in-session workflow
│   ├── repos/                       # Per-repo context (paths, commands, denylist, gotchas)
│   │   ├── aigranthelper.md
│   │   ├── grantspider.md
│   │   ├── wphelper.md
│   │   └── ai-assistants.md
│   ├── registry-schema.md
│   ├── sow-safety-gates.md
│   └── data-contract-grantspider-aigranthelper.md
├── scripts/
│   ├── project_status.py      # Dashboard backend (Phase 2 — built)
│   ├── orchestration/
│   │   └── setup_dispatch_labels.sh   # GitHub label setup (still useful)
│   ├── tools/
│   │   └── generate_tool_registry.py
│   ├── coordinator.py         # Phase 2 — stubbed
│   ├── gather.py              # Phase 2 — stubbed
│   ├── diff.py                # Phase 2 — stubbed
│   ├── sow.py                 # Phase 2 — stubbed
│   └── sweep.py               # Phase 2 — stubbed
├── reports/
│   └── YYYY-MM-DD.md          # Sync check output logs
└── .claude/
    └── skills/
        ├── answer/            # /answer — post one answer, swap labels
        ├── questions/         # /questions — ad-hoc needs-input view
        ├── project-status/    # /project-status — pipeline dashboard
        └── create-persona.md  # Scaffold + deploy a new persona
```

---

## ~/.claude/shared/ Structure

Deployed working copy — not tracked in git. Sync from `oversteward/shared/` on every governance run. All `@file` imports in managed CLAUDE.md files point here.

```
~/.claude/shared/
├── souls/{chestertron,macgregor}.md
├── personas/{angelico,herald}.md
├── skills/
├── references/
├── agents/
└── inbox.md
```

---

## Pillar 1 — Governance

### Registry

`registry.yaml` is the manifest of all managed contexts (currently 14). See the file itself for current state. Key fields:

| Field | Purpose |
|---|---|
| `soul` | Primary identity — `chestertron` or `macgregor` |
| `personas_always_on` | Loaded via @file in managed block |
| `personas_available` | Deployed as skill files |
| `skills_always_on` | Shared skills auto-deployed to context |
| `skills_available` | Shared skills available but not auto-deployed |
| `agents_available` | Domain agents (e.g. grant-researcher) available in this context |
| `skip_sow` | If true, governance never writes to this context |
| `dispatch_target` | If true, context is an in-session pickup target — `/project-status` and `/questions` scan it |
| `soul_in_local` | If true, soul is defined in local section (billions David/"Sir" variant) |

Full schema reference with precise semantics for every field and for the `soul_in_local` / `skip_sow` / `dispatch_target` contracts: [documentation/registry-schema.md](documentation/registry-schema.md).

### CLAUDE.md Composition

Every managed CLAUDE.md follows this structure. OverSteward owns the managed block entirely. Nathan owns the local block entirely.

```markdown
<!-- [oversteward:managed | synced: YYYY-MM-DD] -->
@~/.claude/shared/souls/chestertron.md
@~/.claude/shared/personas/angelico.md
<!-- [oversteward:managed:end] -->

## Context-Specific Instructions
<!-- [oversteward:local] -->

[Nathan's hand-crafted context instructions — never touched by sow.py]

<!-- [oversteward:local:end] -->
```

### Obsidian Context Differences

| Aspect | VS Code | Obsidian (Claudian) |
|---|---|---|
| Instructions file | `CLAUDE.md` at repo root | `.claude/instructions.md` |
| Skills format | Markdown (`.md`) | JSON (`.json`) |
| Settings | `.claude/settings.json` | `.claude/claudian-settings.json` |

### Sync Workflow (Phase 1 — manual)

1. **Deploy shared.** Copy `oversteward/shared/` → `~/.claude/shared/`.
2. **Gather.** Read each registered repo's CLAUDE.md and skills inventory.
3. **Diff.** Compute what each context's managed block should contain vs. what it does.
4. **Report.** Write `reports/YYYY-MM-DD.md` listing proposed changes with rationale.
5. **Review.** Nathan approves, modifies, or rejects each proposed change.
6. **Apply.** Write approved changes with safety gates (below).

### Sync Workflow (Phase 2 — planned, not yet built)

Python scripts do the mechanics; Claude handles judgment in bounded slices.

```bash
conda run -n Oversteward python scripts/coordinator.py --report-only
conda run -n Oversteward python scripts/coordinator.py --apply
```

### Sow Safety Gates

- Bail on dirty working tree.
- No stacking — abort if OverSteward already has an open PR on the target.
- Dry-run by default; explicit `--apply` flag to execute.
- Never push to main — always create `oversteward/sync-YYYY-MM-DD` branch.
- Lockfile during execution.

Formal pre-conditions, per-context contracts (including `soul_in_local` write rules), post-conditions, and rejected "convenient" behaviours: [documentation/sow-safety-gates.md](documentation/sow-safety-gates.md). This is the design contract sow must honor before any first real run.

### Sweep Strategy

OverSteward-deployed persona skills follow naming convention: `persona-{name}.md`. Files not matching this pattern are never touched.

1. For each context, list `persona-*.md` in its skills directory.
2. For each such file, check if the persona is still in `personas_available`.
3. If no longer listed: hash compare against template. Match → propose deletion. Differ → flag, never auto-delete.

### Inbox (governance notifications)

`~/.claude/shared/inbox.md`. OverSteward appends entries when shared resources change. First context to start a session reads the inbox, applies changes, and clears the file.

### Persona Catalogue

| Persona | File | Status | Description |
|---|---|---|---|
| Angelico | `angelico.md` | Active | Creative Director — design, copy, visual strategy |
| Herald | `herald.md` | Active | Marketing Counselor (Praeco Domus) |
| Analyst | `analyst.md` | Planned | Data and financial reasoning specialist |

---

## Pillar 2 — Orchestration

### In-session pickup targets

Four production repos, each with a dedicated context doc in [`documentation/repos/`](documentation/repos/):

| Repo | Context doc | Role |
|---|---|---|
| aigranthelper | [`repos/aigranthelper.md`](documentation/repos/aigranthelper.md) | Django SaaS — Stripe, Neon, paid users |
| grantspider | [`repos/grantspider.md`](documentation/repos/grantspider.md) | US grant data crawler |
| wphelper | [`repos/wphelper.md`](documentation/repos/wphelper.md) | WordPress client toolkit — REST, SEO, FTP, Gutenberg |
| ai-assistants | [`repos/ai-assistants.md`](documentation/repos/ai-assistants.md) | Almoner package — content, CRM, WP integration |

Each context doc carries the repo's paths, test/lint commands, CI check names, denylist, gotchas, and PR template — what was previously baked into the dispatch subagent system prompt.

### In-session pickup loop

```
Nathan: "let's work AG #415" (or grantspider 150 / wp 84 / ai-assistants 73)
    │
    ▼
session reads documentation/repos/<name>.md
    + documentation/issue-to-pr-workflow.md
    │
    ▼
session walks the 19-step workflow:
   preflight → worktree → scope validation → implement → test → lint
   → ratchet → coherence audit → ship → poll → cleanup → report
    │
    ├── clean path: PR opened, auto-merge enabled, polled to merged
    │
    └── blocked path: stops in chat (Nathan present) OR posts a
                      structured `@nathankrupa question:` comment + labels
                      needs-input (Nathan async)
```

### Async Q&A loop (when work blocks while Nathan is away)

```
session blocks → structured question comment on the GH issue
    │
    ▼
Nathan sees it via /questions or the /project-status stale counter
    │
    ▼
Nathan runs /answer <repo> <n>
    ├── shows the pending question
    ├── captures his answer
    ├── posts comment to GH issue
    └── swaps label needs-input → ready-for-agent
    │
    ▼
Nathan resumes: "let's resume <repo> #<n>" — fresh window or current session
```

The previous Chestertron Inbox round-trip (`/morning-digest` → Obsidian file → `/answer-flow`) was retired in H1-5 (PR #16, merged 2026-04-20). GitHub issues are the only channel for cross-session Q&A. The `/dispatch` skill (PR #4, 2026-04-15) was retired 2026-05-01 — see the pivot note in §"Pillar 2 — Orchestration".

### Visibility surfaces

| Skill | Cadence | Purpose |
|---|---|---|
| `/project-status` | Ad-hoc | Pipeline dashboard — open issues, open PRs, recent merges, agents in flight, scoping candidates, 30d metrics, stale `needs-input` counter |
| `/questions` | Ad-hoc | Compact list of `needs-input` items, flags stale (>=48h) |
| `/answer` | Ad-hoc (per issue) | Post one answer on a `needs-input` issue and swap labels to `ready-for-agent` |

### Self-critique gate

Before opening a PR, the in-session worker runs a coherence audit on its own diff against the workflow ratchet (step 12 of [issue-to-pr-workflow.md](documentation/issue-to-pr-workflow.md)). Cheap at write-time, reduces review churn and failure modes that have bitten previously (documented in memory files as `feedback_*` entries).

### Scoping surface

When the ready queue drops below threshold, `/project-status` surfaces the oldest unscoped issue per repo so Nathan can scope without having to ask.

---

## Key Decisions — Resolved

### Governance pillar

| Decision | Resolution |
|---|---|
| CLAUDE.md composition method | @file imports pointing to `~/.claude/shared/` |
| Shared content location | `oversteward/shared/` → `~/.claude/shared/` |
| Conflict resolution | Ownership markers — managed regenerated, local untouched |
| Soul separation | `soul:` registry field; chestertron and macgregor never mix |
| Persona deployment | `personas_always_on` (@file) vs `personas_available` (skill files) |
| billions soul exception | `soul_in_local: true` — sow skips soul injection |
| OverSteward self-management | `skip_sow: true` |
| Sweep ownership signal | `persona-{name}.md` naming convention |
| Reports retention | 30-day tracked, archive/ gitignored |
| Headless architecture | Coordinator pattern — Python orchestrates, Claude judges in slices |

### Orchestration pillar

| Decision | Resolution |
|---|---|
| Task board | GitHub issues; labels drive state; no parallel TODO |
| Worker model | In-session — the assistant Nathan is chatting with does the work directly. Background subagents retired 2026-05-01 due to harness false-positive completion bug. |
| Repo context | One per-repo doc in [`documentation/repos/`](documentation/repos/) — paths, commands, denylist, gotchas. Read at the start of each pickup. |
| Blocked-worker protocol | Stop in chat if Nathan is present; otherwise `needs-input` label + structured `@nathankrupa question:` issue comment (plan/holes/gaudi/revised plan) |
| Async Q&A channel | GitHub issue comments — single source of truth, no external inbox file |
| Resume trigger | `ready-for-agent` label (swapped by `/answer <repo> <n>`); Nathan says "let's resume" |
| Self-critique gate | Coherence audit against workflow ratchet before PR open (step 12) |
| Scoping anti-starve | `/project-status` surfaces oldest unscoped issue when queue thins |
| PR merge strategy | Auto-merge on green CI; `--admin` bypass never allowed |

---

## Success Criteria

### Governance

- Nathan can develop a skill in any context and have it appear in all relevant contexts within one sync cycle.
- No `CLAUDE.md` managed block drifts more than one version behind the shared baseline.
- MacGregor's soul has never appeared in any other context's CLAUDE.md.
- Weekly sync check runs without manual intervention (Phase 3).
- Nathan spends zero time manually copying instructions between projects.

### Orchestration

- In-session pickup cycle time (issue → merged PR, excluding needs-input) holds at or below a known median.
- No `needs-input` issue sits more than 48 hours without Nathan seeing it.
- Ready queue never starves — `/project-status` surfaces scoping candidates before zero-ready state.
- Self-critique catches regressions against documented past failure modes before PR open.
- Nathan can see full pipeline state in one command, under 3 seconds.

---

## Phase Roadmap

### Phase 1 — Governance foundation (complete)

All 8 local + remote contexts migrated. Canonical souls and personas deployed. 14 contexts registered. First manual sync check ran 2026-02-26.

### Phase 2 — Tooling (partial)

**Orchestration side (built):**
- [x] In-session workflow doc + per-repo context docs (formerly `/dispatch` skill + four repo-scoped subagents — retired 2026-05-01)
- [x] `/questions` (list) and `/answer` (post one reply, swap labels) skills
- [x] `/project-status` skill with Python backend (`scripts/project_status.py`) — 30d metrics + stale `needs-input` counter
- [x] Self-critique gate (step 12 of issue-to-pr-workflow.md)
- [x] Tool registry generator (`scripts/tools/generate_tool_registry.py`)

**Governance side (not yet built):**
- [ ] `scripts/gather.py` — pull state from all repos
- [ ] `scripts/diff.py` — structured change list
- [ ] `scripts/sow.py` — apply changes with safety gates
- [ ] `scripts/sweep.py` — stale persona skill cleanup
- [ ] `scripts/coordinator.py` — orchestrator

### Phase 3 — Automation (partial)

- [x] Orchestration answer loop collapsed to GH-native surfaces (no cron dependency) — H1-5
- [ ] Governance sync on cron (pending Phase 2 scripts)
- [ ] Drift detection notifications

### Phase 4 — Refinement (open)

- [ ] Build Analyst persona (`/create-persona` skill already scaffolded)
- [ ] Deploy Analyst to Stocks and OpportunityMiner
- [x] Pipeline metrics on `/project-status` (PR turnaround, merge rate, needs-input age + stale counter) — H1-2 + H1-5
- [ ] Regression catalog / pre-dispatch lint from past failure memories
- [ ] Full issue-creation → merge cycle time (excluding needs-input stalls) — needs timeline-event fetch

---

## Known Risks

1. **Phase 2 governance scripts stale.** Script stubs have been in place since 2026-02-20 without implementation. Manual sync has been happening irregularly. Either build minimum-viable sow or formally retire the plan.
2. **Partial pipeline metrics.** `/project-status` now reports PR turnaround, merge rate, `needs-input` age + stale counter. Still missing: full issue-creation → merge cycle time excluding `needs-input` stalls (needs timeline-event fetch) and self-critique fire rate (definition undecided).
3. **billions registry modelling.** `soul_in_local: true` works today; Phase 2 sow needs to honor this explicitly or it will overwrite the David variant.
4. **Private-repo branch protection.** GitHub Free tier blocks branch protection on private repos. Discipline-only today; could hide direct-to-main regressions.
5. **Orphan agent branches from the dispatch era.** ~80 on aigranthelper, ~30 on wphelper, ~5 on grantspider — heartbeat-pushed stubs from harness-dropped subagents. Not blocking; one-time triage scoped in [issue-to-pr-workflow.md](documentation/issue-to-pr-workflow.md) §"Orphan-branch sweeper". Run when convenient.
6. **Anthropic strategic shift.** Both upstream bugs (claude-code #47931 / #47936) are open with no Anthropic response. Managed Agents launched April 2026 with metered $0.08/session-hour billing. The non-fix may be a deliberate nudge toward the metered tier; in-session work on the existing Max subscription is the cheapest reliable path.

---

*Document version: 2026-05-01*
*Status: Governance Phase 1 complete; Orchestration pivoted to in-session model; Governance Phase 2 pending scope decision.*

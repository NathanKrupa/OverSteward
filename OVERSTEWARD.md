ABOUTME: The OverSteward project specification and architecture reference.
ABOUTME: Two-pillar system: governance (sync across contexts) + orchestration (dispatch autonomous agents).

# The OverSteward

**Steward of the House of Krupa's Claude Code estate: keeps every managed context aligned AND dispatches scoped autonomous agents to work the ticket queue across the production repos.**

> "If one thing is done late, everything will be late." The OverSteward ensures that wisdom earned in one quarter of the estate is not squandered by ignorance in another — and that the footmen are dispatched with clear scope, brought home, and never left stranded in a corridor.

---

## Purpose

The OverSteward serves two complementary missions.

### Pillar 1 — Governance (sync)

Keep every managed context's `CLAUDE.md`, souls, personas, and shared skills aligned with the canonical source. Propagate improvements. Prevent drift. Nathan is the only integration layer today, and that does not scale across 14 contexts.

### Pillar 2 — Orchestration (dispatch)

Send scoped autonomous agents to work GitHub issues across the four active production repos (aigranthelper, grantspider, wphelper, ai-assistants). Provide the async ask-answer loop that closes the human-in-the-loop gap. Keep Nathan informed without making him the queue bottleneck.

Both pillars share a principle: **Nathan is the principal; the OverSteward is the gentleman's gentleman.** Changes are proposed, not imposed. Agents work scoped tickets; Nathan scopes the work. The system has exactly one escape hatch from its own control — Nathan manages the OverSteward directly (`skip_sow: true`).

---

## Problem Statement

**Governance side:**
- Skills and prompt patterns developed in one context don't automatically appear in others.
- `CLAUDE.md` files evolve independently with no shared baseline.
- Souls and personas have no governance layer — they can be silently overwritten or go missing.
- Manual sync across 14 contexts is past the point where it reliably happens.

**Orchestration side:**
- Four production repos generate more ticket work than Nathan can do solo.
- Agents that ask questions mid-run without a capture path are effectively abandoned.
- Without a dashboard, Nathan cannot see the pipeline state at a glance.
- Without a scoping surface, the agent queue starves even when the backlog is deep.

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
8. **Issue queue as the task board** (orchestration). `gh issue list` drives dispatch. Labels drive state. PR merges drive completion. No parallel TODO file for dispatch work.

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      OverSteward Repo                            │
│                                                                  │
│  registry.yaml       ← manifest of all managed contexts          │
│  shared/             ← canonical souls, personas, skills, refs   │
│  contexts/           ← per-context local overrides               │
│  .claude/skills/     ← dispatch, answer-flow, morning-digest,    │
│                        questions, project-status, create-persona │
│  scripts/            ← project_status.py, tool registry,         │
│                        Phase 2 sync stubs                        │
│  reports/            ← sync check logs                            │
│  Chestertron Inbox   ← Obsidian file — async Q&A channel          │
└────────┬────────────────────────────────────────────────────────┘
         │
         ├─── GOVERNANCE ──────────────────────────────────────────
         │   syncs shared → ~/.claude/shared → @file in each repo
         │
         │    ┌─────────┬─────────┬──────────┬─── ... ──────────┐
         │    ▼         ▼         ▼          ▼                  ▼
         │  Home_Ob  billions  ai-assist   macgregor    14 contexts
         │
         └─── ORCHESTRATION ──────────────────────────────────────
             /dispatch launches repo-scoped subagent
             agent works GH issue → PR → auto-merge
             agent blocks → needs-input + Inbox append
             /answer-flow → posts answers back → re-dispatch
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
│   ├── agents/                # Dispatch subagent definitions (source of truth)
│   ├── templates/
│   └── inbox.md               # Update notifications (cleared on first read)
├── contexts/                  # Per-context local overrides
│   └── *.md                   # One file per registered context
├── scripts/
│   ├── project_status.py      # Dashboard backend (Phase 2 — built)
│   ├── orchestration/
│   │   └── setup_dispatch_labels.sh
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
        ├── dispatch/          # /dispatch — launch scoped agents
        ├── answer-flow/       # /answer-flow — Inbox → GitHub
        ├── morning-digest/    # /morning-digest — needs-input reconciler
        ├── questions/         # /questions — ad-hoc inbox view
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
| `agents_available` | Dispatch subagent types this context can invoke |
| `skip_sow` | If true, governance never writes to this context |
| `soul_in_local` | If true, soul is defined in local section (billions David/"Sir" variant) |

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

### Dispatch targets

Four production repos, each with a dedicated subagent type defined in `shared/agents/`:

| Repo | Subagent | Role |
|---|---|---|
| aigranthelper | `aigranthelper-dev` | Django SaaS — Stripe, Neon, paid users |
| grantspider | `grantspider-dev` | US grant data crawler |
| wphelper | `wphelper-dev` | WordPress client toolkit — REST, SEO, FTP, Gutenberg |
| ai-assistants | `ai-assistants-dev` | Almoner package — content, CRM, WP integration |

Each subagent is briefed with the repo's architecture, conventions, self-critique ratchet, and dispatch playbook.

### Dispatch loop

```
/dispatch <repo> <issue-number>
    │
    ▼
scoped subagent reads issue → implements → tests → lints
    │
    ├── clean path: opens PR → enables auto-merge → polls → terminal YAML report
    │
    └── blocked path: comments `@nathankrupa question:` on issue
                      labels `needs-input`
                      appends question block to Chestertron Inbox
                      exits with STOPPED_FOR_INPUT YAML
```

### Async Q&A loop

```
agent blocks → Chestertron Inbox
    │
    ▼
Nathan writes answer under the question block (morning review)
    │
    ▼
/answer-flow (hourly cron + session-start)
    ├── parses answered blocks
    ├── posts comment to GH issue
    ├── swaps label needs-input → ready-for-agent
    └── clears the answered block from Inbox
    │
    ▼
Nathan re-dispatches the issue
```

### Visibility surfaces

| Skill | Cadence | Purpose |
|---|---|---|
| `/project-status` | Ad-hoc | Pipeline dashboard — open issues, open PRs, recent merges, agents in flight, scoping candidates when queue thins |
| `/questions` | Ad-hoc | Compact list of `needs-input` items, flags stale (>48h) |
| `/morning-digest` | Daily 7am cron | Safety net: catches `needs-input` issues whose questions never made it to the Inbox |
| `/answer-flow` | Hourly cron + session-start | Inbox → GitHub answer posting |

### Chestertron Inbox

**Location:** `C:\Users\natha\OneDrive\Documents\Nathan Writing\Obsidian\GTD\Projects\The Almoner Business\Research\Chestertron Inbox.md`

Single canonical channel for agent questions → Nathan answers. OneDrive-backed, which gives it cross-machine reach in principle (see known risk below).

### Self-critique gate

Before opening a PR, the dispatched agent runs a coherence audit on its own diff against the dispatch playbook ratchet. Cheap at write-time, reduces review churn and failure modes that have bitten previously (documented in memory files as `feedback_*` entries).

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
| Subagent scope | One subagent type per production repo, briefed with local conventions |
| Blocked-agent protocol | `needs-input` label + `@nathankrupa question:` comment + Inbox append |
| Async Q&A channel | Chestertron Inbox markdown file in Obsidian |
| Re-dispatch trigger | `ready-for-agent` label (swapped by `/answer-flow`) |
| Self-critique gate | Coherence audit against playbook ratchet before PR open |
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

- Dispatch loop cycle time (issue → merged PR, excluding needs-input) holds at or below a known median.
- No `needs-input` issue sits more than 48 hours without Nathan seeing it.
- Ready queue never starves — `/project-status` surfaces scoping candidates before zero-ready state.
- Agent self-critique catches regressions against documented past failure modes before PR open.
- Nathan can see full pipeline state in one command, under 3 seconds.

---

## Phase Roadmap

### Phase 1 — Governance foundation (complete)

All 8 local + remote contexts migrated. Canonical souls and personas deployed. 14 contexts registered. First manual sync check ran 2026-02-26.

### Phase 2 — Tooling (partial)

**Orchestration side (built):**
- [x] `/dispatch` skill and four repo-scoped subagents
- [x] `/answer-flow`, `/morning-digest`, `/questions` skills
- [x] `/project-status` skill with Python backend (`scripts/project_status.py`)
- [x] Self-critique gate
- [x] Tool registry generator (`scripts/tools/generate_tool_registry.py`)

**Governance side (not yet built):**
- [ ] `scripts/gather.py` — pull state from all repos
- [ ] `scripts/diff.py` — structured change list
- [ ] `scripts/sow.py` — apply changes with safety gates
- [ ] `scripts/sweep.py` — stale persona skill cleanup
- [ ] `scripts/coordinator.py` — orchestrator

### Phase 3 — Automation (partial)

- [x] `/answer-flow` and `/morning-digest` on cron schedule
- [ ] Governance sync on cron (pending Phase 2 scripts)
- [ ] Drift detection notifications

### Phase 4 — Refinement (open)

- [ ] Build Analyst persona (`/create-persona` skill already scaffolded)
- [ ] Deploy Analyst to Stocks and OpportunityMiner
- [ ] Pipeline metrics on `/project-status` (cycle time, needs-input age distribution, merge rate)
- [ ] Regression catalog / pre-dispatch lint from past failure memories
- [ ] Cross-machine resilience for the Chestertron Inbox

---

## Known Risks

1. **Single-machine Inbox.** The Chestertron Inbox is a Windows-OneDrive path. OneDrive gives it cross-machine reach in principle, but agents on other machines would need the path parameterized. Parameterize it in the skills before any second-machine work begins.
2. **Phase 2 governance scripts stale.** Script stubs have been in place since 2026-02-20 without implementation. Manual sync has been happening irregularly. Either build minimum-viable sow or formally retire the plan.
3. **No dispatch metrics.** "Working well" is vibes. Without cycle time, needs-input age, and failure rate surfaced in `/project-status`, regressions are invisible until Nathan notices them.
4. **billions registry modelling.** `soul_in_local: true` works today; Phase 2 sow needs to honor this explicitly or it will overwrite the David variant.
5. **Private-repo branch protection.** GitHub Free tier blocks branch protection on private repos. Discipline-only today; could hide direct-to-main regressions.

---

*Document version: 2026-04-20*
*Status: Governance Phase 1 complete; Orchestration Phase 2 active; Governance Phase 2 pending scope decision.*

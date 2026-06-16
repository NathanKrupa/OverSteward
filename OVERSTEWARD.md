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

Send scoped autonomous agents to work GitHub issues across the five active production repos (aigranthelper, grantspider, wphelper, ai-assistants, fiscus). Provide the async ask-answer loop that closes the human-in-the-loop gap. Keep Nathan informed without making him the queue bottleneck.

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
9. **Deterministic, fail-open mechanics; tokens for judgment only.** Drift detection, hashing, manifest comparison, and diffing are deterministic Python that costs zero Claude tokens and **fails open** — a broken or unreachable check never blocks or mutates an estate it cannot read cleanly; it reports the gap and proceeds. Claude tokens are spent only where genuine judgment is required: conflict resolution, content proposals, scoping. This sharpens principle 3 — "Python for mechanics" also means *cheap, safe, and silent on the happy path*. (Learned from gbrain's zero-LLM auto-link and observe-only guardrail seams; see [documentation/gbrain-learnings.md](documentation/gbrain-learnings.md).)

### System Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      OverSteward Repo                            │
│                                                                  │
│  registry.yaml       ← manifest of all managed contexts          │
│  shared/             ← canonical souls, personas, skills, refs   │
│  contexts/           ← per-context local overrides               │
│  .claude/skills/     ← dispatch, answer, questions,              │
│                        project-status, create-persona            │
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
         └─── ORCHESTRATION ──────────────────────────────────────
             /dispatch launches repo-scoped subagent
             agent works GH issue → PR → auto-merge
             agent blocks → needs-input + structured question comment
             /answer <repo> <n> → posts Nathan's reply → re-dispatch
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
│   ├── workflows/
│   │   └── generate_workflow_registry.py
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

### Canonical shared scripts (in-repo, not ~/.claude/shared/)

A second class of shared artifact lives at `oversteward/shared/scripts/` — Python tools that need to ship **inside each pickup repo** (so they can `Path(__file__).resolve().parent.parent.parent` to that repo's root), not at user level. Currently:

| Script | Source of truth | Deployed to | Used by |
|---|---|---|---|
| `generate_tool_registry.py` | `oversteward/shared/scripts/tools/generate_tool_registry.py` | `<repo>/scripts/tools/generate_tool_registry.py` | AG, GS, FI, OS |
| `generate_workflow_registry.py` | `oversteward/shared/scripts/workflows/generate_workflow_registry.py` | `<repo>/scripts/workflows/generate_workflow_registry.py` | GS (others as they grow workflows) |
| `guard_main_worktree.py` | `oversteward/shared/scripts/dev/guard_main_worktree.py` | `<repo>/.claude/hooks/guard_main_worktree.py` | all repos (session-per-worktree guard) |
| `new-session.sh` | `oversteward/shared/scripts/dev/new-session.sh` | `<repo>/scripts/dev/new-session.sh` | all repos (worktree launcher) |
| `test_worktree_guard.py` | `oversteward/shared/scripts/dev/test_worktree_guard.py` | `<repo>/tests/dev/test_worktree_guard.py` | all repos (guard tests) |

Phase-1 sync = byte-copy from source to each pickup repo (any dispatch target). Phase-2 sow.py will fold these into the same workflow as souls/personas. Per-repo configuration (e.g. `data/tool_registry.toml` for project-specific category names) lives in the consuming repo and is **not** managed by OverSteward — only the script itself is canonical.

### Session-per-worktree discipline

**One git worktree per session — the estate-wide standard.** Parallel Claude/human sessions that share a single checkout collide: a `git checkout`/`switch` in one session yanks another's branch out from under it and strands uncommitted work (it bit GS twice, which is where the guard originated — GS PR #1196). The discipline: each unit of work gets its own worktree under `.claude/worktrees/<name>` on a `session/<name>` branch, cut from the integration branch.

Three byte-identical canonical files (above) make it portable:

- **`guard_main_worktree.py`** — `PreToolUse(Bash)` hook (registered in `<repo>/.claude/settings.json`) that refuses branch checkout/switch in the *primary* worktree. Linked worktrees, file restores (`git checkout -- `, `git restore`), and `git worktree add` are exempt. Override per-command with `CLAUDE_ALLOW_MAIN_GIT=1` (GS also honors `GS_ALLOW_MAIN_GIT=1` for back-compat).
- **`new-session.sh`** — self-adapting launcher: base ref is `origin/staging` if it exists (GS/AG), else the remote default branch (trunk-only repos); `PYTHONPATH` is `src/` if present, else the worktree root (Django/flat). One shared `.venv` is symlinked in — `PYTHONPATH` overrides the editable install's `.pth` (verified for pip and uv), so worktrees cost ~nothing. (uv repos: invoke `.venv/bin/<tool>` directly, not `uv run`, which may re-sync the shared venv.)
- **`test_worktree_guard.py`** — pure-logic unit tests for the guard (locates the hook by walking up to the repo root, so it is depth-independent).

**New-project / new-repo bootstrap** (this IS "the template" — copy these three from the canonical source):

```bash
mkdir -p .claude/hooks scripts/dev tests/dev
cp <oversteward>/shared/scripts/dev/guard_main_worktree.py .claude/hooks/
cp <oversteward>/shared/scripts/dev/new-session.sh         scripts/dev/   # chmod +x
cp <oversteward>/shared/scripts/dev/test_worktree_guard.py tests/dev/
# register the hook in .claude/settings.json under hooks.PreToolUse (matcher "Bash"):
#   python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/guard_main_worktree.py"
echo '.claude/worktrees/' >> .gitignore
```

Then document it in the repo's `CONTRIBUTING.md` (or `CLAUDE.md` where there is none).

### Workflow registry & descriptor convention

The **tool registry** catalogs single entry points (CLI scripts, console commands). The **workflow registry** catalogs the higher-altitude thing: multi-step **Python↔Claude workflows** — a Claude Agent SDK Workflow script, a Python pipeline, or an operator-in-loop loop. It is the same durable, regenerable pattern, one level up.

Unlike the tool registry, the workflow registry does **not** sniff the filesystem. Each workflow is described by one hand-authored **descriptor** at `<repo>/.claude/workflows/<name>.md` (co-located with any `.js` Workflow script). `generate_workflow_registry.py` aggregates these descriptors into `<repo>/data/workflow_registry.md`. This decouples the catalog from implementation shape; the accepted trade-off is that descriptors are manual, so the generator validates that any path-shaped `components` entry exists on disk and warns (without failing) when one has drifted.

Descriptor frontmatter schema (YAML) + free-form body:

```yaml
---
name: enrich-drain
summary: One-line what-it-does.            # required
when_to_use: When to reach for this.       # required
kind: workflow-script                      # required: workflow-script | python-pipeline | operator-loop
status: active                             # optional (default active): active | experimental | deprecated
entrypoint: .claude/workflows/enrich-drain.js   # optional: how you start it (path or command)
components:                                # optional: files/commands it touches (paths are drift-checked)
  - scripts/enrich/split_batch.py
  - "grantspider enrich-profile pull-batch"
phases:                                    # optional; omit for workflow-script (the .js meta is authoritative)
  - name: Generate
    detail: N Sonnet agents draft profiles per slice (no write)
  - name: Verify
    detail: Opus grounds + repairs, then apply
    model: opus
---
Free-form body: the file-exchange contract, gotchas, links to docs/PRs.
```

Regenerate after adding or editing a descriptor: `uv run python scripts/workflows/generate_workflow_registry.py`.

### Dual-target deploy: Windows + WSL2

Since 2026-05-20 (AG/GS port off OneDrive), the deploy target is **two homes**, not one:

| Host | Target path |
|---|---|
| Windows | `C:\Users\natha\.claude\shared\` |
| WSL2 (Ubuntu-24.04) | `/home/natha/.claude/shared/` |

A Claude session running natively under WSL resolves `~/.claude/shared/...` against `/home/natha/.claude/`; a Windows session resolves against `C:\Users\natha\.claude\`. They are separate filesystems with no automatic mirror. Every deploy step (sync check, persona scaffold, manual edit) writes to both, or AG/GS (and any future WSL repo) silently break their `@~/.claude/shared/...` imports.

**Inbox caveat:** `shared/inbox.md` is bidirectional state, not deploy-only. The "first context to start a session reads it, applies changes, and clears it" pattern (see below) only sees its own host's copy. To avoid drift: either Nathan appends to both copies, or sync the inbox in both directions before the session-start read. Treat inbox sync as a known soft seam until Phase 2 formalizes it.

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
| `dispatch_target` | If true, context is eligible for `/dispatch` |
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

1. **Deploy shared.** Copy `oversteward/shared/` → **both** `C:\Users\natha\.claude\shared\` (Windows) **and** `/home/natha/.claude/shared/` (WSL2). See [Dual-target deploy](#dual-target-deploy-windows--wsl2).
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

### Deployment manifest & drift classification

The current sow contract compares **canonical-now vs on-disk-now** (two-way). On a hash mismatch for a byte-copy file (skill, persona, hook), the only safe two-way action is to overwrite — but that silently discards a local edit if one exists, and it cannot tell *why* the file diverged. gbrain hit exactly this with `skillpack reference --apply-clean-hunks`: a two-way merge has no record of what was originally deployed, so it clobbers intentional local edits and accidental drift alike.

OverSteward avoids this by recording a **deployment manifest** — the per-file SHA of every byte-copy artifact at the moment sow last deployed it (`reports/manifest.json`, keyed by `context → path → sha`). Drift detection then becomes **three-way** (deployed-baseline vs canonical-now vs on-disk-now) and classifies every managed path into one of four states:

| State | Condition | Meaning | sow/sweep action |
|---|---|---|---|
| `identical` | on-disk == canonical | Up to date | No-op |
| `stale` | on-disk == baseline, baseline != canonical | Canonical moved forward; repo untouched | Safe to redeploy |
| `diverged` | on-disk != baseline **and** on-disk != canonical | Repo's copy was edited locally | **Flag, never silently overwrite.** Surface the diff; Nathan decides — a byte-copy ratchet-treaty violation to correct, or a deliberate downstream hotfix to promote back upstream |
| `missing` | path absent on disk | Never deployed, or deleted downstream | Deploy (sow) / propose (sweep) |

`sync-status` reports use this `identical / stale / diverged / missing` vocabulary directly. Only `diverged` ever requires human judgment; the other three are deterministic, fail-open, and zero-token (principle 9). The byte-copy ratchet treaty assumes *no* intentional local divergence in canonical files — the manifest is what lets OverSteward **detect and surface** a violation of that assumption instead of erasing the evidence. Full mechanics fold into the skill-file deployment contract in [documentation/sow-safety-gates.md](documentation/sow-safety-gates.md).

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

Five production repos, each with a dedicated subagent type defined in `shared/agents/`, all on WSL2:

| Repo | Subagent | Role |
|---|---|---|
| aigranthelper | `aigranthelper-dev` | Django SaaS — Stripe, Neon, paid users |
| grantspider | `grantspider-dev` | US grant data crawler |
| wphelper | `wphelper-dev` | WordPress client toolkit — REST, SEO, FTP, Gutenberg |
| ai-assistants | `ai-assistants-dev` | Almoner package — content, CRM, WP integration |
| fiscus | `fiscus-dev` | Observation-and-kaizen platform — schemas, reviews, lessons corpus |

Each subagent is briefed with the repo's architecture, conventions, self-critique ratchet, and dispatch playbook. Agents run **in-session, foreground** (Agent/Workflow tools) on the Max subscription — never background-async, which is API-metered and subject to silent-termination bug #47936.

### Dispatch loop

```
/dispatch <repo> <issue-number>
    │
    ▼
scoped subagent reads issue → implements → tests → lints
    │
    ├── clean path: opens PR → enables auto-merge → polls → terminal YAML report
    │
    └── blocked path: posts a structured `@nathankrupa question:` comment
                      on the issue (plan / holes / gaudi check / revised plan)
                      labels `needs-input`
                      exits with STOPPED_FOR_INPUT YAML
```

### Async Q&A loop

```
agent blocks → structured question comment on the GH issue
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
Nathan re-dispatches the issue (/dispatch <repo> <n>)
```

The previous Chestertron Inbox round-trip (`/morning-digest` → Obsidian file → `/answer-flow`) was retired in H1-5 (PR #16, merged 2026-04-20). GitHub issues are now the only channel for agent Q&A — cross-machine by default, no single-machine Obsidian path.

### Visibility surfaces

| Skill | Cadence | Purpose |
|---|---|---|
| `/project-status` | Ad-hoc | Pipeline dashboard — open issues, open PRs, recent merges, agents in flight, scoping candidates, 30d metrics, stale `needs-input` counter |
| `/questions` | Ad-hoc | Compact list of `needs-input` items, flags stale (>=48h) |
| `/answer` | Ad-hoc (per issue) | Post one answer on a `needs-input` issue and swap labels to `ready-for-agent` |

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
| Blocked-agent protocol | `needs-input` label + structured `@nathankrupa question:` issue comment (plan/holes/gaudi/revised plan) |
| Async Q&A channel | GitHub issue comments — single source of truth, no external inbox file |
| Re-dispatch trigger | `ready-for-agent` label (swapped by `/answer <repo> <n>`) |
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
- [x] `/questions` (list) and `/answer` (post one reply, swap labels) skills
- [x] `/project-status` skill with Python backend (`scripts/project_status.py`) — 30d metrics + stale `needs-input` counter
- [x] Self-critique gate
- [x] Tool registry generator (`scripts/tools/generate_tool_registry.py`)

**Governance side (not yet built):**
- [ ] `scripts/gather.py` — pull state from all repos
- [ ] `scripts/diff.py` — structured change list (three-way: deployed-baseline vs canonical vs on-disk; classifies `identical / stale / diverged / missing`)
- [ ] `reports/manifest.json` — per-file deployment baseline (`context → path → sha`) written by sow, read by diff/sweep/`sync-status`
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
2. **Partial dispatch metrics.** `/project-status` now reports PR turnaround, merge rate, `needs-input` age + stale counter. Still missing: full issue-creation → merge cycle time excluding `needs-input` stalls (needs timeline-event fetch) and self-critique fire rate (definition undecided).
3. **billions registry modelling.** `soul_in_local: true` works today; Phase 2 sow needs to honor this explicitly or it will overwrite the David variant.
4. **Private-repo branch protection.** GitHub Free tier blocks branch protection on private repos. Discipline-only today; could hide direct-to-main regressions.

---

*Document version: 2026-06-16*
*Status: Governance Phase 1 complete; Orchestration Phase 2 active; Governance Phase 2 pending scope decision. gbrain learnings (deployment manifest, fail-open principle) folded in 2026-06-16.*

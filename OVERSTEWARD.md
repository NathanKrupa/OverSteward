ABOUTME: The OverSteward project specification and architecture reference.
ABOUTME: Defines the sync governance system for all managed contexts across the House of Krupa.

# The OverSteward

**A synchronization and governance system for managing Claude Code contexts across the House of Krupa.**

> "If one thing is done late, everything will be late." The OverSteward ensures that wisdom earned in one quarter of the estate is not squandered by ignorance in another.

---

## Purpose

Nathan operates Claude Code across nine repositories — two Obsidian vaults and six VS Code projects, plus the OverSteward itself. Each has its own `CLAUDE.md`, skills, souls, personas, and institutional memory. The OverSteward is the one system whose sole job is to maintain consistency, propagate improvements, and prevent drift across all contexts.

The OverSteward does **one thing well**: keep every managed context's `CLAUDE.md` aligned with the canonical shared standards, and deploy the right souls and personas to the right places.

## Problem Statement

- Skills and prompt patterns developed in one context don't automatically appear in others.
- `CLAUDE.md` files evolve independently with no shared baseline.
- Souls and personas have no governance layer — they can be silently overwritten or go missing.
- Nathan is the only integration layer, and that doesn't scale.

---

## Architecture

### Design Principles

1. **Git is the backbone.** All nine repositories are Git-backed. The OverSteward treats them uniformly.
2. **@file imports, not generated files.** Shared content is composed via Claude Code's `@~/.claude/shared/...` import syntax, resolved at session start. No build step. No generated concatenation. The shared source files are canonical; each context's CLAUDE.md holds pointers.
3. **Python for mechanics, Claude Code for intelligence.** File gathering, diffing, and Git operations are Python. Analysis, relevance judgments, and content proposals are Claude Code.
4. **Ownership markers.** Every managed CLAUDE.md has a `[oversteward:managed]` block (OverSteward owns it) and a `[oversteward:local]` block (Nathan owns it). sow.py never touches local.
5. **Inheritance model.** `~/.claude/shared/` is the canonical deployed copy. `oversteward/shared/` is the git-tracked source. Scripts sync source → deployed on every run.
6. **PR mode first, autonomous later.** Changes are proposed, not applied, until trust is established.
7. **OverSteward manages others. Nathan manages OverSteward.** The system has exactly one escape hatch from its own control.

### System Diagram

```
┌───────────────────────────────────────────────────┐
│                  OverSteward Repo                  │
│                                                    │
│  registry.yaml      ← manifest of contexts         │
│  shared/            ← canonical souls & personas   │
│  contexts/          ← per-context local overrides  │
│  scripts/           ← gather, diff, sow, sweep     │
│  reports/           ← sync check logs (30-day)     │
│  .claude/skills/    ← create-persona and others    │
└──────────────┬─────────────────────────────────────┘
               │ syncs to
     ~/.claude/shared/           ← deployed working copy
               │
               │ @file imports read from here at session start
    ┌──────────┼────────────────────────────┐
    ▼          ▼          ▼                 ▼
┌────────┐ ┌────────┐ ┌────────┐      ┌────────┐
│Obsidian│ │Obsidian│ │VS Code │      │VS Code │
│ Home   │ │  GH    │ │billions│ ...  │MacGregor│
└────────┘ └────────┘ └────────┘      └────────┘
```

---

## Repository Structure

```
oversteward/
├── OVERSTEWARD.md             # This document
├── CLAUDE.md                  # Instructions for Claude Code sessions in this repo
├── registry.yaml              # Manifest of all managed contexts
├── shared/                    # Git-tracked canonical source (deploys to ~/.claude/shared/)
│   ├── souls/
│   │   ├── chestertron.md     # Primary soul for all contexts except MacGregor
│   │   └── macgregor.md       # MacGregor's soul — never deploys elsewhere
│   ├── personas/
│   │   ├── angelico.md        # Creative Director — design contexts only
│   │   └── analyst.md         # [future] Data/financial analyst persona
│   ├── coding-conventions.md  # Python style, error handling, patterns [Phase 1]
│   └── formatting.md          # Response format preferences [Phase 1]
├── contexts/                  # Context-specific local overrides (one file per context)
│   ├── oversteward.md
│   ├── home-obsidian.md
│   ├── gh-obsidian.md
│   ├── billions.md
│   ├── ai-assistants.md
│   ├── ai-grants.md
│   ├── macgregor.md
│   ├── stocks.md
│   └── opportunity-miner.md
├── scripts/
│   ├── coordinator.py         # Orchestrator — runs full sync workflow in slices
│   ├── gather.py              # Pull current state from all repos
│   ├── diff.py                # Compute needed changes (pure Python)
│   ├── sow.py                 # Apply approved changes with safety gates
│   └── sweep.py               # Remove stale persona skill files safely
├── reports/
│   ├── latest.md              # Copy of most recent report
│   ├── YYYY-MM-DD.md          # Sync check output logs (30-day retention)
│   └── archive/               # Older reports (gitignored)
└── .claude/
    └── skills/
        └── create-persona.md  # Scaffold + deploy a new persona end-to-end
```

---

## ~/.claude/shared/ Structure

This directory is the deployed working copy — not tracked in git. The OverSteward syncs `oversteward/shared/` → `~/.claude/shared/` at the start of every run. All `@file` imports in managed CLAUDE.md files point here.

```
~/.claude/shared/
├── souls/
│   ├── chestertron.md
│   └── macgregor.md
├── personas/
│   ├── angelico.md
│   └── analyst.md        [future]
├── coding-conventions.md [Phase 1]
└── formatting.md         [Phase 1]
```

---

## Registry

### Managed Contexts

| Context | Repo | Soul | Angelico | Analyst | Notes |
|---|---|---|---|---|---|
| OverSteward | OverSteward | chestertron | — | — | `skip_sow: true` |
| Home Obsidian | Home_Obsidian | chestertron | none | TBD | Personal vault |
| GH Obsidian | GH_Obsidian | chestertron | none | TBD | Work vault |
| billions | billions | chestertron | **always-on** | TBD | |
| AI Assistants | ai-assistants | chestertron | **skill** | TBD | |
| AI Grants | ai-grants | AI_Grants | chestertron | **skill** | TBD | |
| MacGregor | MacGregor | **macgregor** | none | none | Soul protected |
| Stocks | Stocks | chestertron | none | available (future) | |
| OpportunityMiner | OpportunityMiner | chestertron | none | available (future) | |

**always-on** = loaded via `@file` in the managed CLAUDE.md block.
**skill** = deployed as `persona-angelico.md` skill file; Nathan invokes it.

### Registry Schema

```yaml
# registry.yaml
version: 1
contexts:
  - name: "OverSteward"
    id: oversteward
    type: vscode
    repo: https://github.com/NathanKrupa/OverSteward.git
    branch: main
    claude_md_path: CLAUDE.md
    skills_path: .claude/skills/
    soul: chestertron
    skip_sow: true                # OverSteward manages itself — sow.py skips this
    personas_always_on: []
    personas_available: []
    tags:
      - meta
      - governance

  - name: "Home Obsidian"
    id: home-obsidian
    type: obsidian
    repo: https://github.com/NathanKrupa/Home_Obsidian.git
    branch: main
    claude_md_path: CLAUDE.md
    skills_path: claude-skills/
    soul: chestertron
    personas_always_on: []
    personas_available: []
    tags:
      - personal
      - writing
      - faith

  - name: "GH Obsidian"
    id: gh-obsidian
    type: obsidian
    repo: https://github.com/NathanKrupa/GH_Obsidian.git
    branch: main
    claude_md_path: CLAUDE.md
    skills_path: claude-skills/
    soul: chestertron
    personas_always_on: []
    personas_available: []
    tags:
      - work
      - fundraising
      - grants
      - writing

  - name: "billions"
    id: billions
    type: vscode
    repo: https://github.com/NathanKrupa/billions.git
    branch: main
    claude_md_path: CLAUDE.md
    skills_path: .claude/skills/
    soul: chestertron
    personas_always_on:
      - angelico              # design is core to this project
    personas_available: []
    tags:
      - design
      - web

  - name: "AI Assistants"
    id: ai-assistants
    type: vscode
    repo: https://github.com/NathanKrupa/ai-assistants.git
    branch: main
    claude_md_path: CLAUDE.md
    skills_path: .claude/skills/
    soul: chestertron
    personas_always_on: []
    personas_available:
      - angelico              # invoked when building design surfaces
    tags:
      - ai
      - design
      - web
      - python

  - name: "AI Grants"
    id: ai-grants
    type: vscode
    repo: https://github.com/NathanKrupa/AI-Grants.git
    branch: main
    claude_md_path: CLAUDE.md
    skills_path: .claude/skills/
    soul: chestertron
    personas_always_on: []
    personas_available:
      - angelico              # invoked for proposal design, PDFs, emails
    tags:
      - grants
      - fundraising
      - writing
      - design

  - name: "MacGregor"
    id: macgregor
    type: vscode
    repo: https://github.com/NathanKrupa/MacGregor.git
    branch: main
    claude_md_path: CLAUDE.md
    skills_path: .claude/skills/
    soul: macgregor           # protected — chestertron never enters this context
    personas_always_on: []
    personas_available: []
    tags:
      - macgregor

  - name: "Stocks"
    id: stocks
    type: vscode
    repo: https://github.com/NathanKrupa/Stocks.git
    branch: main
    claude_md_path: CLAUDE.md
    skills_path: .claude/skills/
    soul: chestertron
    personas_always_on: []
    personas_available:
      - analyst               # [future — when persona is built]
    tags:
      - data
      - analysis
      - finance

  - name: "OpportunityMiner"
    id: opportunity-miner
    type: vscode
    repo: https://github.com/NathanKrupa/OpportunityMiner.git
    branch: main
    claude_md_path: CLAUDE.md
    skills_path: .claude/skills/
    soul: chestertron
    personas_always_on: []
    personas_available:
      - analyst               # [future — when persona is built]
    tags:
      - data
      - analysis
      - research
```

### Registry Fields

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Human-readable name |
| `id` | Yes | Unique slug used in file paths and reports |
| `type` | Yes | `obsidian` or `vscode` |
| `repo` | Yes | Git remote URL |
| `branch` | Yes | Branch to monitor |
| `claude_md_path` | Yes | Path to CLAUDE.md relative to repo root |
| `skills_path` | No | Path to skills directory if one exists |
| `soul` | Yes | Primary identity: `chestertron` or `macgregor` |
| `skip_sow` | No | If true, sow.py skips this context entirely |
| `personas_always_on` | Yes | Personas loaded via @file in managed block |
| `personas_available` | Yes | Personas deployed as skill files |
| `tags` | No | Topic tags for relevance matching |

---

## CLAUDE.md Composition

Every managed CLAUDE.md follows this structure. The OverSteward owns the managed block entirely — it regenerates on every sync. Nathan owns the local block entirely — sow.py never reads or modifies it.

```markdown
<!-- [oversteward:managed | synced: YYYY-MM-DD] -->
@~/.claude/shared/souls/chestertron.md
@~/.claude/shared/personas/angelico.md
@~/.claude/shared/coding-conventions.md
<!-- [oversteward:managed:end] -->

## Context-Specific Instructions
<!-- [oversteward:local] -->

[Nathan's hand-crafted context instructions — never touched by sow.py]

<!-- [oversteward:local:end] -->
```

The sync date in the managed block allows both humans and scripts to detect drift at a glance.

---

## Persona Catalogue

Personas live in `oversteward/shared/personas/` (source) and deploy to `~/.claude/shared/personas/` (working copy). The OverSteward is the catalogue of record.

| Persona | File | Status | Description |
|---|---|---|---|
| Angelico | `angelico.md` | Active | Creative Director — design, copy, visual strategy |
| Analyst | `analyst.md` | Planned | Data and financial reasoning specialist |

### Adding a New Persona

Use the `/create-persona` skill in the OverSteward project. It handles:
1. Interactive scaffolding of `shared/personas/{name}.md`
2. Commit to OverSteward repo
3. Registry grid update — Nathan marks which contexts get access
4. Deployment via sow.py to approved contexts

A persona never deploys without an explicit registry entry.

---

## Sweep Strategy

When a persona is removed from a context's `personas_available`, its skill file becomes stale. The sweep function handles cleanup safely.

**Ownership signal:** OverSteward-deployed persona skills follow a predictable naming convention: `persona-{name}.md`. Files not matching this pattern were not deployed by the OverSteward and are never touched.

**Sweep algorithm (sweep.py):**
1. For each context, list all files matching `persona-*.md` in its skills directory
2. For each such file, check if the persona is still in `personas_available` in the registry
3. If no longer listed:
   - Hash the file and compare against the current template in `shared/personas/`
   - **Hash matches** (unmodified): propose deletion via PR — safe to sweep
   - **Hash differs** (Nathan customized it): flag in report, never auto-delete, require explicit approval
4. Present proposed sweeps in the sync report alongside other changes

---

## Workflow

### Manual Sync Check (Phase 1 — Current)

**Step 1 — Deploy shared.** Scripts sync `oversteward/shared/` → `~/.claude/shared/`.

**Step 2 — Gather.** `gather.py` clones or pulls each registered repo (skipping `skip_sow: true` for writes but reading for state). Extracts current CLAUDE.md and skills inventory.

**Step 3 — Diff.** `diff.py` computes what each context's managed block should contain (per registry) vs. what it currently contains. Identifies missing persona skill files and stale ones.

**Step 4 — Report.** Claude Code reviews the diff output and generates `reports/YYYY-MM-DD.md` listing proposed changes with rationale.

**Step 5 — Review.** Nathan reviews and approves, modifies, or rejects each proposed change.

**Step 6 — Apply.** `sow.py` applies approved changes with safety gates. Sweep runs as part of this step.

### Coordinator Pattern (Phase 2 — Headless)

The coordinator invokes Claude in small, bounded slices — one context per call — rather than one giant session. Python handles mechanics; Claude handles judgment.

```bash
# Shell entry point
conda run -n Oversteward python scripts/coordinator.py --report-only
conda run -n Oversteward python scripts/coordinator.py --apply
```

### sow.py Safety Gates

Before touching any target repo:
- Check `git status` — bail entirely on dirty working tree
- Check for existing OverSteward-created open branches/PRs — no stacking
- Dry-run by default; `--apply` flag to execute
- Never push to `main` — always create `oversteward/sync-YYYY-MM-DD` branch
- Log all operations to `reports/` before and after
- Lockfile during execution to prevent concurrent runs

### Headless Cron (Phase 3)

```bash
# crontab — Sunday 8pm
0 20 * * 0 cd ~/repos/oversteward && conda run -n Oversteward python scripts/coordinator.py --apply
```

Or via GitHub Actions (see `.github/workflows/sync-check.yml`).

---

## Reports Policy

- **Retention:** 30 days in `reports/` (git-tracked)
- **Archive:** Older reports move to `reports/archive/` (gitignored, kept on disk)
- **latest.md:** Updated after every run — always the most recent report

---

## Scope of Work

### Phase 1: Foundation

- [x] Create OverSteward repo structure
- [x] Write registry.yaml with all nine contexts
- [x] Create shared/souls/chestertron.md from existing soul.md
- [x] Create shared/personas/angelico.md from existing design-soul.md
- [ ] Verify @file resolution in Obsidian vault context
- [ ] Get both Obsidian vaults Git-backed with appropriate .gitignore files
- [ ] Extract MacGregor's soul into shared/souls/macgregor.md
- [ ] Extract coding-conventions.md and formatting.md from global CLAUDE.md
- [ ] Write contexts/ override files — one per managed context
- [ ] Write OverSteward CLAUDE.md sync instructions
- [ ] Run first manual sync check and validate output

### Phase 2: Tooling

- [ ] Build scripts/gather.py — repo cloning, file extraction, state snapshot
- [ ] Build scripts/diff.py — structured change list, pure Python
- [ ] Build scripts/sow.py — apply changes with safety gates
- [ ] Build scripts/sweep.py — stale persona skill file cleanup
- [ ] Build scripts/coordinator.py — orchestrator, invokes Claude in slices
- [ ] Test full gather → diff → analyze → sow pipeline manually

### Phase 3: Automation

- [ ] Configure headless coordinator invocation
- [ ] Set up cron job or GitHub Actions for weekly runs
- [ ] Establish notification (Obsidian daily note or Todoist task)
- [ ] Tune tag-based relevance matching
- [ ] Graduate low-risk changes to autonomous mode

### Phase 4: Refinement

- [ ] Build Analyst persona
- [ ] Deploy Analyst to Stocks and OpportunityMiner
- [ ] Add new contexts to registry as projects emerge
- [ ] Build Obsidian dashboard showing current sync state across all contexts
- [ ] Consider event-driven post-commit hooks for real-time drift detection

---

## Recommended .gitignore for Obsidian Vaults

```gitignore
# Workspace state (changes on every pane interaction)
.obsidian/workspace.json
.obsidian/workspace-mobile.json

# Plugin runtime data (frequent churn)
.obsidian/plugins/*/data.json

# OS files
.DS_Store
.trash/
Thumbs.db
```

Keep `.obsidian/` tracked otherwise — plugin list, hotkeys, appearance, and community plugin configs are configuration worth versioning.

---

## Key Decisions — Resolved

| Decision | Resolution |
|---|---|
| CLAUDE.md composition method | @file imports pointing to `~/.claude/shared/` |
| Shared content location | `oversteward/shared/` (source) → `~/.claude/shared/` (deployed) |
| Conflict resolution | Ownership markers — managed block regenerated, local block untouched |
| Soul separation | `soul:` registry field; chestertron and macgregor never mix |
| Persona deployment | `personas_always_on` (@file in managed block) vs `personas_available` (skill files) |
| Machine scope | All repos on home machine — no multi-machine complexity |
| OverSteward self-management | `skip_sow: true` — Nathan manages OverSteward directly |
| Sweep ownership signal | Naming convention: `persona-{name}.md` files |
| Reports retention | 30-day tracked, archive/ gitignored |
| Headless architecture | Coordinator pattern — Python orchestrates, Claude handles judgment in slices |

---

## Success Criteria

The OverSteward is working when:

- Nathan can develop a skill in any context and have it appear in all relevant contexts within one sync cycle.
- No `CLAUDE.md` managed block drifts more than one version behind the shared baseline.
- MacGregor's soul has never appeared in any other context's CLAUDE.md.
- The weekly sync check runs without manual intervention (Phase 3).
- Nathan spends zero time manually copying instructions between projects.

---

*Document version: 2026-02-20*
*Status: Active — architecture finalized, Phase 1 in progress*

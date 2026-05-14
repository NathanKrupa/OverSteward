ABOUTME: Project status ledger and session log for the OverSteward.
ABOUTME: Living document — current state, blockers, and session history.

# Chestertron's Steward's Ledger — OverSteward

**Domain:** Technical Projects
**Purpose:** Two-pillar system — (1) sync governance keeping 14 managed contexts aligned on souls, personas, and CLAUDE.md standards, and (2) orchestration of scoped autonomous agents dispatched against four production repos.
**Last Updated:** 2026-04-20

---

## Project Vision

The OverSteward is the one system that ensures wisdom earned in one quarter of the estate reaches all others, AND the control room from which scoped autonomous agents are dispatched to work the production issue queues. Governance propagates; orchestration executes. Nathan is the principal; the OverSteward proposes and dispatches — never imposes.

---

## Current State

### Pillar 1 — Governance

| Area | State |
|---|---|
| `registry.yaml` | 14 contexts registered |
| `shared/souls/` | chestertron.md + macgregor.md canonical and deployed |
| `shared/personas/` | angelico.md + herald.md canonical and deployed |
| `shared/skills/` | create-todoist-task.md shared |
| `shared/references/` | wodehouse.md, architecture-principles.md, others |
| `contexts/` | All 8 local/remote context override files filled |
| CLAUDE.md migrations | All reachable repos migrated (local + 2 GitHub-only) |
| Phase 2 scripts | coordinator/gather/diff/sow/sweep — all still stubbed since 2026-02-20 |
| Last sync report | `reports/2026-02-26.md` — no subsequent automated sync |

### Pillar 2 — Orchestration

| Area | State |
|---|---|
| `/dispatch` skill | Active; supports aigranthelper, grantspider, wphelper, ai-assistants, fiscus |
| Subagents | Five repo-scoped dev agents defined in `shared/agents/` |
| `/answer` | Active; GH-native per-issue reply (replaced Inbox round-trip in H1-5) |
| `/questions` | Active; ad-hoc |
| `/project-status` | Active; Python-backed with 30d metrics + stale `needs-input` counter |
| Self-critique gate | Live in dispatch playbook (PR #4, 2026-04-15) |
| Chestertron Inbox | **Retired** as of H1-5 (PR #16, 2026-04-20) — GitHub issues are now the single Q&A channel |
| Dispatch metrics | Partial — PR turnaround + merge rate + needs-input age/stale surfaced; full cycle time and self-critique fire rate still open |

### Contexts in Registry

| Context | Soul | Status |
|---|---|---|
| OverSteward | chestertron | `skip_sow: true` |
| Home Obsidian | chestertron | Migrated |
| GH Obsidian | chestertron | Migrated via `gh` CLI 2026-03-23 |
| billions | chestertron (`soul_in_local`) | Migrated; Angelico always-on |
| AI Assistants | chestertron | Migrated; hosts dispatch-era skills |
| AI Grants | chestertron | Migrated; git-backed as of 2026-02-26 |
| AI Grant Helper | chestertron | Dispatch target |
| MacGregor | **macgregor** | Soul protected |
| Stocks | chestertron | Migrated; awaits Analyst persona |
| OpportunityMiner | chestertron | Migrated via GitHub API 2026-03-23 |
| wphelper | chestertron | Dispatch target |
| Gaudi | chestertron | Migrated 2026-04-06; architecture linter |
| GrantSpider | chestertron | Dispatch target (branch: master) |
| Minecraft | chestertron | Migrated |

---

## Blocked / Flagged Items

1. **Analyst persona not yet built.** Stocks and OpportunityMiner are waiting. Use `/create-persona`.
2. **billions registry modelling.** `soul_in_local: true` works in Phase 1; Phase 2 sow.py must honor this or it will overwrite the David variant.
3. **Phase 2 governance scripts are stubs.** Two months without implementation while orchestration skills grew heavily. Needs an explicit scope decision — build, defer, or retire.
4. **Partial dispatch metrics.** `/project-status` surfaces PR turnaround, merge rate, needs-input age + stale counter. Still missing: full issue-creation → merge cycle time (excluding `needs-input` stalls — needs timeline-event fetch) and self-critique fire rate (definition undecided).
5. **Private-repo branch protection unavailable.** GitHub Free tier. Discipline-only on 7 private repos.

---

## Cross-Domain Connections

- **All 14 managed contexts** — governance pillar deploys shared resources to them.
- **Five dispatch-target repos** (aigranthelper, grantspider, wphelper, ai-assistants, fiscus) — orchestration pillar sends scoped agents against their issue queues (Fiscus elevated 2026-05-14; dev agent authored, in-session-by-default workflow per `feedback_in_session_not_dispatch`).
- **~/.claude/soul.md and design-soul.md** — originals remain in place; canonical copies live in shared/. Originals can be retired once all contexts migrate to shared paths.
- **MacGregor** — soul-protected; never receives Chestertron or any cross-context content.
- **GitHub issue comments** — the canonical async Q&A channel. Agents post `@nathankrupa question:` blocks; Nathan replies via `/answer <repo> <n>`; the `needs-input` → `ready-for-agent` swap closes the loop.

---

## Session Log

### 2026-02-20 — Initial Build Session

Architecture workshopped and finalized. Key decisions: @file import approach, soul/persona separation with explicit registry grid, ownership markers, coordinator pattern for headless sync, sow.py safety gates, naming-convention sweep ownership. Deliverables: OVERSTEWARD.md, registry.yaml, shared/souls/chestertron.md, shared/personas/angelico.md, all contexts/ stubs, all scripts/ stubs, create-persona skill, git initialized, remote connected.

### 2026-02-20 — Phase 1 Session 1

Confirmed @file resolution in Home_Obsidian. Migrated Home Obsidian CLAUDE.md. Filled `contexts/home-obsidian.md` from actual vault content.

### 2026-02-21 — Phase 1 Session 2

Audited all 5 local VS Code repos. Extracted MacGregor soul → `shared/souls/macgregor.md` and deployed. Filled remaining 7 context stubs. Confirmed Home Obsidian is Git-backed. Key discovery: billions uses intentional David/"Sir" Chestertron variant.

### 2026-02-26 — Phase 1 Session 3

Migrated 5 of 5 local repos (billions, ai-assistants, macgregor, stocks, ai-grants). Ran first manual sync check → `reports/2026-02-26.md`, all 6 local contexts pass. Flagged billions David-soul exception as Phase 2 design issue. Converted 3 Obsidian skill files `.json` → `.md`.

### 2026-03-06 — Skill Distribution + Wodehouse

Built skill distribution system (shared/skills/, inbox, registry schema v2). Added Wodehouse humor reference and wired into soul. Added Minecraft to registry. Committed tracking: `fff5c45`, `5d20797`.

### 2026-03-09 — Obsidian Paths + Framework Sow

Connected GH Obsidian; fixed Obsidian context paths. Sowed Fundraising.AI Framework across all contexts. Added Buffett analyst persona drafts + 3 reference files.

### 2026-03-23 — Remote Migrations

GH Obsidian verified via `gh` CLI; managed block confirmed in place. OpportunityMiner managed block added via GitHub API (commit `881d674`). All reachable repos now migrated.

### 2026-04-06 — PR Workflow Rollout

Added Gaudi and GrantSpider to registry. Implemented PR-structured workflow across all active projects: global CLAUDE.md PR Workflow section, `.github/PULL_REQUEST_TEMPLATE.md` to 9 projects, `.github/CODEOWNERS` to 9 projects, branch protection on OverSteward (master) and Gaudi (main). Branch protection on 7 private repos blocked by GitHub Free tier.

### 2026-04-15 — Dispatch-Era Skills Arrive (PR #4)

Added self-critique gate and live-append inbox workflow. First substantial move of the OverSteward's center of gravity from governance into orchestration. Dispatch playbook ratchets self-check before PR open; agents append their own questions to Chestertron Inbox live rather than relying on morning-digest as primary capture.

### 2026-04-16 — Dispatch Surface Expansion (PRs #5–#8)

- PR #5: Added ai-assistants as fourth dispatch target.
- PR #6: `/project-status` skill added (initial shell-orchestration version).
- PR #7: WCAG gold contrast rule added to frontend design brief.
- PR #8: Line-count cap replaced with coherence audit in dispatch playbook.

### 2026-04-17 — Dispatch Playbook Coherence Audit (PR #9)

Ratcheted self-check requirements. Python 3.14 rollout across subagent configs. Wphelper rename reconciled.

### 2026-04-18 — `/project-status` Goes Python (PR #10)

Replaced shell orchestration in `/project-status` with `scripts/project_status.py`. Four repos fetched in parallel; ~2–3s runtime. Scoping surface folded into the dashboard — oldest unscoped issue per repo surfaces when ready queue thins.

### 2026-04-20 — OVERSTEWARD.md Two-Pillar Rewrite (current)

OVERSTEWARD.md and Stewards_Ledger.md updated to reflect what this repo has actually become: a two-pillar system, with governance (sync) still ~90% complete on Phase 1 and Phase 2 stubbed, and orchestration (dispatch) actively shipping through PR workflow. New plan under review.

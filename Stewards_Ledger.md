ABOUTME: Project status ledger and session log for the OverSteward.
ABOUTME: Living document — current state, blockers, and session history.

# Chestertron's Steward's Ledger — OverSteward

**Domain:** Technical Projects
**Purpose:** Two-pillar system — (1) sync governance keeping 15 managed contexts aligned on souls, personas, and CLAUDE.md standards, and (2) orchestration of in-session pickup work across five production repos.
**Last Updated:** 2026-05-27

---

## Project Vision

The OverSteward is the one system that ensures wisdom earned in one quarter of the estate reaches all others, AND the control room from which in-session pickup work is scoped and surfaced across the production issue queues. Governance propagates; orchestration scopes. Nathan is the principal; the OverSteward proposes — never imposes.

---

## Current State

### Pillar 1 — Governance

| Area | State |
|---|---|
| `registry.yaml` | 15 contexts registered (Fiscus added 2026-05-14) |
| `shared/souls/` | chestertron.md + macgregor.md canonical and deployed |
| `shared/personas/` | angelico.md + herald.md canonical and deployed |
| `shared/skills/` | create-todoist-task.md shared |
| `shared/references/` | wodehouse.md, architecture-principles.md, pr-workflow.md, credential-hygiene.md, behavioral-discipline.md, catholic-investing.md, fundraising-ai-framework.md, herald-reference.md, house-of-krupa-frontend-design-brief.md, household-stewardship.md |
| `contexts/` | All 8 local/remote context override files filled |
| CLAUDE.md migrations | All reachable repos migrated (local + 2 GitHub-only) |
| Deploy target | **Dual** — Windows (`C:\Users\natha\.claude\shared\`) + WSL2 (`/home/natha/.claude/shared/`) since AG/GS WSL2 port 2026-05-20 |
| Phase 2 scripts | coordinator/gather/diff/sow/sweep — all still stubbed since 2026-02-20 |
| Last sync report | `reports/2026-02-26.md` — no subsequent automated sync |

### Pillar 2 — Orchestration (in-session pickup)

| Area | State |
|---|---|
| `/dispatch` skill | **Live — in-session foreground.** Invokes `<repo>-dev` via the Agent/Workflow tools on the Max subscription (not background-async/API). Background mode retired (API-metered + silent-termination bug #47936). PR #33 (full retirement) superseded. |
| Subagents | Five repo-scoped `<repo>-dev` agents in `shared/agents/` — retained and refreshed for WSL2 paths; invoked foreground in-session |
| `/answer` | Active; GH-native per-issue reply |
| `/questions` | Active; ad-hoc |
| `/project-status` | Active; Python-backed with 30d metrics + stale `needs-input` counter |
| Self-critique gate | Live in pickup workflow (originated PR #4, 2026-04-15) |
| Chestertron Inbox | **Retired** as of H1-5 (PR #16, 2026-04-20) — GitHub issues are the single Q&A channel |
| Pickup targets | aigranthelper, grantspider, wphelper, ai-assistants, **fiscus** (added 2026-05-14) |
| Pipeline metrics | PR turnaround + merge rate + needs-input age/stale surfaced; full cycle time and self-critique fire rate still open (Horizon 3) |

### Estate-wide infrastructure

| Surface | State |
|---|---|
| Credential hygiene | Cross-repo (PR #47, 2026-05-27): user-level deny-list + shared reference + scratch CLIs (GS, AG) + PreToolUse block-and-redirect hook |
| Tool registry | Universal pattern via `scripts/tools/generate_tool_registry.py`. Live in OverSteward, GS, AG, Fiscus, gaudi. Each CLAUDE.md points at `data/tool_registry.md` |
| PR workflow | Canonical at `shared/references/pr-workflow.md`; sourced by `~/.claude/CLAUDE.md` |
| Trajectory notes | Schema at `documentation/trajectories/TEMPLATE.md` (PR #46, open). One note per in-session pickup. Input artifact for Fiscus epic #25 (review-fork subagent) |
| Andon channel | Fiscus-owned aggregation; companion issues #37 in OverSteward, equivalent issues in other pickup repos |
| Cross-repo SHA pinning | `grantspider.master → aigranthelper.requirements.txt` automated via `notify-ag-on-master.yml` + `bump-gs-pin.yml` (PR #41, 2026-05-20) |
| Python env | uv across Fiscus/gaudi/OverSteward (migrated 2026-05-22, PR #43). conda still on AG/GS/WP/ai-assistants |
| File-system topology | All seven repos on WSL2 (AG, GS, Fiscus, gaudi, OverSteward, WP, ai-assistants); WP + ai-assistants ported off Windows OneDrive 2026-05-30 (PR #52) |

### Contexts in Registry

| Context | Soul | Status |
|---|---|---|
| OverSteward | chestertron | `skip_sow: true` |
| Home Obsidian | chestertron | Migrated |
| GH Obsidian | chestertron | Migrated via `gh` CLI 2026-03-23 |
| billions | chestertron (`soul_in_local`) | Migrated; Angelico always-on |
| AI Assistants | chestertron | Migrated; pickup target; OneDrive |
| AI Grants | chestertron | Migrated; git-backed as of 2026-02-26 |
| AI Grant Helper | chestertron | Pickup target; WSL2 (`/home/natha/aigranthelper`) |
| MacGregor | **macgregor** | Soul protected |
| Stocks | chestertron | Migrated; awaits Analyst persona |
| OpportunityMiner | chestertron | Migrated via GitHub API 2026-03-23 |
| wphelper | chestertron | Pickup target; OneDrive |
| Gaudi | chestertron | Migrated 2026-04-06; WSL2 (`/home/natha/gaudi`); architecture linter |
| GrantSpider | chestertron | Pickup target; WSL2 (`/home/natha/grantspider`); branch `master` |
| Minecraft | chestertron | Migrated |
| **Fiscus** | chestertron | **Pickup target since 2026-05-14**; WSL2 (`/home/natha/Fiscus`); observation-and-kaizen platform |

---

## Blocked / Flagged Items

1. **Analyst persona not yet built.** Stocks and OpportunityMiner are waiting. Use `/create-persona` when a real use case arrives.
2. **billions registry modelling.** `soul_in_local: true` works in Phase 1; Phase 2 sow.py must honor this or it will overwrite the David variant.
3. **Phase 2 governance scripts are stubs.** Three months without implementation while orchestration shipped heavily, then orchestration itself simplified (dispatch retirement). Needs an explicit scope decision — build, defer, or retire. Likely trigger is H2-1 (cross-repo `.claude/settings.json` parity).
4. **Partial pipeline metrics.** Full issue-creation → merge cycle time (excluding `needs-input` stalls) needs timeline-event fetch. Self-critique fire rate definition undecided.
5. **Private-repo branch protection unavailable.** GitHub Free tier. Discipline-only on 7 private repos. Logged as L-DISP-1 in architecture.md.
6. **PR #33 superseded and closed (2026-05-30).** Rather than retiring `/dispatch`, the dispatch surface was revived as in-session foreground (Max-billed) — see Pillar 2. The `<repo>-dev` agent defs are retained, not deleted.
7. **PR #46 (trajectory template) merged 2026-05-30.**
8. **OneDrive worktree husks (Issue #39).** ~80 accumulated in grantspider's `.git/worktrees/` from dispatch-era. Mitigated by dispatch retirement but residue remains.
9. **Cross-repo `.claude/settings.json` drift.** Each pickup repo's project-level settings vary; credential-hygiene rules only live at user level. Tracked as Horizon 2 (H2-1).
10. **PreToolUse hook regex false positives.** First commit attempt for PR #47 was blocked by the hook on its own commit message body. git/gh whitelist added; future false positives may need further tightening.

---

## Cross-Domain Connections

- **All 15 managed contexts** — governance pillar deploys shared resources to them.
- **Five pickup-target repos** (aigranthelper, grantspider, wphelper, ai-assistants, fiscus) — orchestration pillar surfaces ready/needs-input/stale state; Nathan picks issues up in-session per `documentation/issue-to-pr-workflow.md`.
- **~/.claude/soul.md and design-soul.md** — originals remain in place; canonical copies live in shared/. Originals can be retired once all contexts migrate to shared paths.
- **MacGregor** — soul-protected; never receives Chestertron or any cross-context content.
- **GitHub issue comments** — the canonical async Q&A channel. Agents post `@nathankrupa question:` blocks; Nathan replies via `/answer <repo> <n>`; the `needs-input` → `ready-for-agent` swap closes the loop.
- **Fiscus** — the observability seam. `pipeline_history.jsonl` (oversteward) and `andon`-labelled issues (every pickup repo) feed Fiscus's weekly/monthly/quarterly reviews. OverSteward emits; Fiscus aggregates.
- **`~/.claude/shared/credential-hygiene.md`** — cross-repo discipline reference. Every session-Claude sees it via `@`-include in `~/.claude/CLAUDE.md`.

---

## Session Log

### 2026-05-30 — Dispatch Foreground Pivot + Estate Cleanup

Estate-review session that became a build. Diagnosis: OverSteward wasn't broken, it was mid-transition — the expensive surface (background dispatch → metered Managed Agents) had been cut weeks earlier, but the half-done state lingered. Triage corrected: the "hang and die" agents weren't a billing change, they were the `run_in_background: true` silent-termination bug (#47936). In-session subagents (Agent/Workflow tools) bill against Max, not the API — confirmed via Anthropic cost docs.

Cleanup first: merged PR #46 (trajectory template); closed dispatch-era issues #2 (sweeper) and #3 (`/drain`) as superseded by the in-session model; disposition comment on #39 (worktree husks).

Core work: pivoted `/dispatch` from background-async to **in-session foreground** (Max-billed, dodges #47936). Rewrote SKILL.md (foreground invocation, uv routing, Workflow batch mode with cost discipline); trimmed playbook v1.8 → v2.0 (removed heartbeat-as-death-insurance, harness-false-positive-completion, dispatcher-verification; `--squash` → `--merge` per estate policy). Refreshed all five `<repo>-dev` agent defs for WSL2 (GS/AG → `.venv/bin`; Fiscus → uv; WP + ai-assistants → `/home/natha/...` after their 2026-05-30 port, PR #52). Removed the Windows/OneDrive husk machinery entirely (all repos now on ext4). `shared/` brought to parity (resolved stale v1.1 playbook drift). PR #33 superseded and closed.

Gotcha: an hour of uncommitted edits was wiped mid-session by a concurrent `git reset`/branch-switch in the shared checkout (Nathan's parallel PR #52 port). Recovered by rebuilding in an isolated `git worktree` and committing early. Lesson: commit before editing when another actor shares the checkout.

### 2026-05-26/27 — Credential-Hygiene + CLI-Discipline Rollout (PR #47)

Single long session covering review → deep research → implementation → merge. Driver: 2026-05-26 GS Neon credential leak (bash interpreted `&` in DATABASE_URL as job-control; five Neon strings printed to stderr → transcript). Generalised the GS-specific feedback memory into estate-wide discipline.

Six layers shipped:
1. User-level deny-list in `~/.claude/settings.json` (19 patterns)
2. Shared `credential-hygiene.md` reference + `@-include` in user CLAUDE.md
3. Compute-Efficiency-Shell rule paragraph in `~/.claude/CLAUDE.md`
4. Tool registry generator ported to Fiscus + gaudi + OverSteward
5. Scratch DB CLIs in GS (`grantspider db scratch`) and AG (`python manage.py db_scratch`)
6. PreToolUse hook `~/.claude/hooks/check_db_access.py` — block + redirect

Sibling PRs merged: GS #1021, AG #700, Fiscus #48, gaudi #224.

Gotchas surfaced: hook fires on its own commit-message body (git/gh whitelist added); GS `allow_squash_merge=false` requires rebase-merge on staging; AG mid-session file sweep when working across multiple repos; gaudi auto-merge disabled (manual merge).

Open: cross-repo `.claude/settings.json` parity (H2-1); GS staging-promote re-evaluation Tuesday 2026-06-02; hook regex tightening as false positives surface.

### 2026-05-22/23 — PR Workflow Propagation Surface + Trajectory Template (PRs #45, #46)

Estate-review session surfaced architecture mismatch: PR Workflow checklist lived only in `~/.claude/CLAUDE.md` (untracked dotfile) with no managed propagation surface. PR #45 promoted it to `shared/references/pr-workflow.md` and rewired user CLAUDE.md to `@-include`. PR #46 added `documentation/trajectories/TEMPLATE.md` — schema for in-session pickup notes; first instance is the self-bootstrap note for #46 itself. Companion to Fiscus epic #25 (review-fork subagent input artifact).

Side cleanup: 16 stale grantspider worktrees surfaced; 12 merged ones pruned on permission.

### 2026-05-22 — WSL2 Port + conda→uv Migration (PRs #42, #43, #44)

After AG and GS moved off OneDrive to WSL2 (~/aigranthelper, ~/grantspider), the shared/ deploy target became two homes — Windows and WSL2 — not one. PR #42 documents the dual-target requirement; PR #43 migrates Fiscus/gaudi/OverSteward from conda to uv; PR #44 logs WSL paths in architecture.md and `uv.lock` policy.

### 2026-05-20 — Cross-Repo SHA-Pin Discipline (PR #41)

Documented the `grantspider.master → aigranthelper.requirements.txt` seam in architecture.md §2. Automation: GS's `notify-ag-on-master.yml` fires `repository_dispatch` on every master push; AG's `bump-gs-pin.yml` opens a draft PR on AG/staging updating `requirements.txt` + `research_schema.lock`. Human-gated merge — AG production never advances its GS pin without a reviewer eyeballing the GS changelog. Added invariant I-19: AG never pins a GS staging or feature-branch SHA.

### 2026-05-14 — Fiscus Genesis + Strategic Capture Suite (PRs #38, #40)

Fiscus elevated to main-project tier. Registered as 5th pickup target. Strategic capture suite: subject registry, weekly/monthly/quarterly reviews, lessons corpus, andon channel. `fiscus-dev` subagent defined. Companion andon-template issues filed against the other four pickup repos.

### 2026-05-02 — Ontology Epic Overnight Run (PR #34, #35)

Overnight ontology epic ran across grantspider: 7 GS PRs merged. Pickup vocab established; GS ontology epic + orphan sweep documented in architecture.md.

### 2026-05-01 — `/dispatch` Skill Retirement (PR #33, open)

Driver: Anthropic claude-code #47931/#47936 silent-termination bug (open since 2026-04-14, no upstream response, ~80 orphan branches accumulated on aigranthelper alone). Coincident with April 2026's metered Managed Agents launch — apparent strategic nudge to the metered tier. In-session work on the existing Max subscription is the cheapest reliable path.

PR retires `/dispatch` skill + four `<repo>-dev` subagent definitions. Replaces with in-session model: Nathan says "let's work AG #415" and the session reads the relevant repo doc + workflow doc and executes directly. Workflow content survives as `documentation/issue-to-pr-workflow.md`; per-repo gotchas as `documentation/repos/*.md`. `/answer`, `/questions`, `/project-status` retained — not dispatch ceremony.

Orphan sweep (companion): 126 dispatch-era branches deleted (87 AG + 34 WP + 5 GS).

PR remained open as of 2026-05-27 — de-facto effective, formal deletion awaiting merge.

### 2026-04-30 — Cross-DB Cutover + Disaster Recovery (PRs #26–#32)

AG cross-DB cutover residue closed; contract → v1.2; L-AG-1 and L-AG-2 retired. Worktree-isolation hardening (PRs #24, #25), baseline-snapshot pattern (#27). Money-field audit report archived (#28). Disaster-recovery driver: 2026-04-30 disaster recovery + research-DB cutover session.

### 2026-04-20 — Horizon 1 Complete (PRs #12–#16)

All five Horizon 1 items shipped in a single day:
- H1-1 (PR #12): registry `dispatch_target` field
- H1-2 (PR #13): 30d pipeline metrics + JSONL snapshot
- H1-3 (PR #14): `soul_in_local` + sow-safety-gates design contracts
- H1-4 (PR #15): `dispatch-paused` kill-switch
- H1-5 (PR #16): GH-native answer loop; Chestertron Inbox retired

### 2026-04-15 to 2026-04-18 — Dispatch Skill Suite (PRs #4–#10)

Self-critique gate + live-append inbox workflow (#4). ai-assistants as fourth dispatch target (#5). `/project-status` initial shell version (#6) then Python rewrite (#10). WCAG gold contrast rule for frontend design brief (#7). Line-count cap → coherence audit (#8). Dispatch playbook coherence audit + Python 3.14 + wphelper rename (#9).

### 2026-04-06 — PR Workflow Rollout

Added Gaudi and GrantSpider to registry. Global CLAUDE.md PR Workflow section; `.github/PULL_REQUEST_TEMPLATE.md` + CODEOWNERS to 9 projects; branch protection on OverSteward (master) and Gaudi (main). Branch protection on 7 private repos blocked by GitHub Free tier.

### 2026-03-23 — Remote Migrations

GH Obsidian verified via `gh` CLI; managed block confirmed. OpportunityMiner managed block added via GitHub API (commit `881d674`). All reachable repos now migrated.

### 2026-03-09 — Obsidian Paths + Framework Sow

Connected GH Obsidian; fixed Obsidian context paths. Sowed Fundraising.AI Framework across all contexts. Added Buffett analyst persona drafts + 3 reference files.

### 2026-03-06 — Skill Distribution + Wodehouse

Built skill distribution system (`shared/skills/`, inbox, registry schema v2). Added Wodehouse humor reference and wired into soul. Added Minecraft to registry. Commits: `fff5c45`, `5d20797`.

### 2026-02-26 — Phase 1 Session 3

Migrated 5 of 5 local repos (billions, ai-assistants, macgregor, stocks, ai-grants). Ran first manual sync check → `reports/2026-02-26.md`, all 6 local contexts pass. Flagged billions David-soul exception as Phase 2 design issue. Converted 3 Obsidian skill files `.json` → `.md`.

### 2026-02-21 — Phase 1 Session 2

Audited all 5 local VS Code repos. Extracted MacGregor soul → `shared/souls/macgregor.md` and deployed. Filled remaining 7 context stubs. Confirmed Home Obsidian is Git-backed. Key discovery: billions uses intentional David/"Sir" Chestertron variant.

### 2026-02-20 — Phase 1 Session 1 + Initial Build

Architecture workshopped and finalized. Key decisions: @file import approach, soul/persona separation with explicit registry grid, ownership markers, coordinator pattern for headless sync, sow.py safety gates, naming-convention sweep ownership. Deliverables: OVERSTEWARD.md, registry.yaml, shared/souls/chestertron.md, shared/personas/angelico.md, all contexts/ stubs, all scripts/ stubs, create-persona skill, git initialized, remote connected. Confirmed @file resolution in Home_Obsidian. Migrated Home Obsidian CLAUDE.md.

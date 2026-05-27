# Completed Tasks

Tasks move here from MASTER_TODO.md when finished. Newest at top.

---

## 2026-05-26/27 — Cross-repo credential-hygiene + CLI-discipline rollout (PR #47 + sibling PRs)

Six-layer response to the 2026-05-26 GS Neon credential leak (bash job-control interpreted `&` in DATABASE_URL and printed five Neon strings to stderr → transcript). Generalised the GS-specific feedback memory into universal estate discipline.

- [x] User-level deny-list in `~/.claude/settings.json` — 19 patterns covering `source .env*`, `set -a*`, raw `psycopg`/`psql` inline, etc.
- [x] Shared `credential-hygiene.md` reference (`shared/references/`) → deployed to `~/.claude/shared/`, sourced into `~/.claude/CLAUDE.md`
- [x] User-level CLAUDE.md rule added under Compute Efficiency → Shell
- [x] Tool registry generator (`scripts/tools/generate_tool_registry.py`) ported to Fiscus + gaudi + OverSteward; CLAUDE.md pointers added
- [x] Scratch DB CLIs in GS (`grantspider db scratch`) and AG (`python manage.py db_scratch`) — SELECT-only with regex guard, row-cap, audit log
- [x] PreToolUse hook `~/.claude/hooks/check_db_access.py` — block + redirect on Bash credential-risk patterns
- [x] Sibling PRs: GS #1021, AG #700, Fiscus #48, gaudi #224 — all merged

Trajectory note: [documentation/trajectories/2026-05-26-PR47.md](documentation/trajectories/2026-05-26-PR47.md)

## 2026-05-22/23 — PR-workflow propagation surface + trajectory template (PRs #45, #46)

- [x] **PR #45** — `shared/references/pr-workflow.md` canonical PR checklist; `~/.claude/CLAUDE.md` rewired to `@-include` from shared; trajectory-note step added
- [x] PR #46 trajectory template (`documentation/trajectories/TEMPLATE.md`) **drafted and committed** but PR still open as of 2026-05-27

## 2026-05-22 — WSL2 port + conda → uv migration (PRs #42, #43, #44)

- [x] **PR #42** — dual-target Windows+WSL2 deploy documented for `shared/` (after AG/GS migrated off OneDrive)
- [x] **PR #43** — conda → uv migration (Fiscus, gaudi, OverSteward)
- [x] **PR #44** — WSL paths logged in architecture.md for fiscus/gaudi/oversteward; `uv.lock` policy

## 2026-05-20 — Cross-repo SHA-pin discipline (PR #41)

- [x] **PR #41** — Document `grantspider.master → aigranthelper.requirements.txt` cross-repo seam in architecture.md §2; I-19 invariant (AG never pins a GS staging/feature-branch SHA); automated bump via `notify-ag-on-master.yml` (GS) + `bump-gs-pin.yml` (AG)

## 2026-05-14 — Fiscus elevated to main-project tier (PR #40)

- [x] **PR #40** — Fiscus added to registry as 5th `dispatch_target` (observation-and-kaizen platform). Strategic capture suite registered (subject registry, weekly/monthly/quarterly reviews, lessons corpus, andon channel). `fiscus-dev` subagent definition.

## 2026-05-01/02 — `/dispatch` skill retired (de-facto; PR #33 still open)

- [x] Orphan-branch sweep: 126 dispatch-era branches deleted (87 AG + 34 WP + 5 GS)
- [x] Workflow content survived as `documentation/issue-to-pr-workflow.md`
- [x] Per-repo pickup context survived as `documentation/repos/*.md`
- [x] `/answer`, `/questions`, `/project-status` retained — not dispatch ceremony, just inbox/status tools
- [ ] PR #33 (formal source-of-truth deletion) still open — see MASTER_TODO

Driver: Anthropic claude-code #47931/#47936 silent-termination bug (open since 2026-04-14, no upstream response).

## 2026-04-30 — Cross-DB cutover + disaster recovery (PRs #26–#32)

- [x] AG cross-DB cutover residue closed (#31, #32); contract → v1.2; L-AG-1 and L-AG-2 retired
- [x] Worktree-isolation hardening + baseline-snapshot pattern (#24, #25, #27)
- [x] Money-field audit report archived (#28)
- [x] `.claude/worktrees/` and `.scratch/` added to `.gitignore` (#29)

## 2026-04-20 — Horizon 1 (Integrity + Visibility)

- [x] **H1-1** — Move dispatch target list to `registry.yaml` (`dispatch_target: true`); `/dispatch`, `/questions`, `/project-status` read from registry (PR #12, 2026-04-20)
- [x] **H1-2** — 30d pipeline metrics on `/project-status` (PR turnaround, merge rate, needs-input age + stale counter) + `data/pipeline_history.jsonl` daily snapshot (PR #13, 2026-04-20)
- [x] **H1-3** — Formalize `soul_in_local` in registry schema docs; pin sow.py safety-gate design contract (`documentation/registry-schema.md` + `documentation/sow-safety-gates.md`, PR #14, 2026-04-20)
- [x] **H1-4** — Dispatch kill-switch: `dispatch-paused` label added to taxonomy; `/dispatch` preflight refuses paused repos; `/project-status` surfaces paused repos (PR #15, 2026-04-20)
- [x] **H1-5** — GH-native answer loop: `/answer <repo> <n>` skill; `/morning-digest` + `/answer-flow` removed; Chestertron Inbox retired; agents post structured `@nathankrupa question:` comments (PR #16, 2026-04-20)

## 2026-04-15 to 2026-04-18 — Dispatch skill suite (PRs #4–#10)

- [x] Self-critique gate + live-append inbox workflow (#4)
- [x] ai-assistants added as fourth dispatch target (#5)
- [x] `/project-status` skill — initial shell version (#6) → Python rewrite (#10)
- [x] WCAG gold contrast rule added to frontend design brief (#7)
- [x] Line-count cap → coherence audit in dispatch playbook (#8)
- [x] Dispatch playbook coherence audit, Python 3.14 rollout, wphelper rename (#9)

## 2026-02-20 to 2026-04-06 — Phase 1 governance foundation

- [x] OverSteward architecture finalized (2026-02-20); OVERSTEWARD.md, registry.yaml, shared/ canonical, contexts/ stubs, scripts/ stubs all in place
- [x] Phase 1 sessions 1–3 (2026-02-20/21/26): all 5 local VS Code repos migrated; MacGregor soul extracted; first sync report (`reports/2026-02-26.md`)
- [x] Skill distribution system + Wodehouse reference + Minecraft added (2026-03-06)
- [x] Obsidian paths fixed; Fundraising.AI Framework sowed; Buffett analyst persona drafts (2026-03-09)
- [x] GH Obsidian and OpportunityMiner remote migrations via `gh`/GitHub API (2026-03-23)
- [x] PR Workflow rollout: global CLAUDE.md section, `.github/PULL_REQUEST_TEMPLATE.md` + CODEOWNERS to 9 projects, branch protection on OverSteward + Gaudi (2026-04-06)
- [x] Gaudi + GrantSpider added to registry (2026-04-06)

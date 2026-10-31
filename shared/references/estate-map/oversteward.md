<!-- Generated from estate-map.yaml by `scripts/estate_map.py render --write`. Do not edit by hand: a test compares this file with a fresh render. -->

# Estate map — oversteward

**North star.** Provide A+ grant-writing tools to the servants of the poor: the food pantries, parishes and small charities who work on shoestring budgets and are not grant experts. It is not about the money; it is about the people.

This repo's share of OverSteward's `estate-map.yaml`. A wrong row is fixed in the map, never here.

## Capabilities (`id` · status · purpose, then current → target shape)

Each current shape is its first sentence; the full measurement is in the map.

- `ag.help-centre` · live · The help centre: DB-backed articles written as PR-gated drafts by the docs-author agent, with captured screenshots and drift checks.
  - 33 modules, 5,112 lines; 30 feature PRs in 90 days. → hold
- `os.registry` · live · The manifest of managed contexts, and the read-only gather and diff behind /sync-status.
  - registry.yaml holds 16 contexts and drives every sweep and dispatch. gather.py (140 lines) and diff.py (189) back /sync-status. scripts/coordinator.py (18 lines) and scripts/sweep.py (12) are comment-only Phase 2 stubs that nothing calls, deferred until a concrete task re-triggers them (`TODO_BACKLOG.md`, H2-6). → hold
- `os.dev-family-sow` · live · Canonical worktree/guard/env scripts and hooks, deployed to repos by sow; nightly `sync_repos` timer.
  - sow (6 modules, 1,186 lines) plus dev_family.py (245) deploy the shared/scripts/dev/ family as sync PRs. → Every repo's copies at canon: worktree_doctor.py deployed where it is absent or pre-#571 (OS#572) and new-session.sh redeployed, with /sync-status reporting zero drift.
- `os.session-sweeps` · live · The session-start sweeps: Sentry triage, Railway liveness, AG ops triage, GS stage health, and the operator-steps channel to Todoist.
  - Four sweep packages (19 modules, 2,594 lines), each with its own connector, service and renderer, plus operator_steps.py (270 lines). → One sweep runner that owns the exit-code contract and the recorded-verdict ledger, so a new sweep is a source and a renderer.
- `os.backup` · live · The laptop backups: a readiness-gated monthly WSL export, a daily restic backup of /home/natha, and the backup health sweep.
  - backup/ (4 modules, 1,271 lines) shipped in OS#581-583. → Docker Desktop volumes either covered by a backup or recorded as deliberately unbacked, with an issue either way.
- `os.telegraph` · live · Membrane over the GitHub-issue bus (Epic Conductor + cross-repo issue filer); transport is Happy.
  - The Epic Conductor (2 modules, 226 lines) and the cross-repo issue filer. → hold
- `os.vintner` · live · `/pipeline-status` GS→AG funnel; reads one read-only DSN (`VINTNER_RESEARCH_DATABASE_URL`, GS Neon).
  - 6 modules, 463 lines; one read-only DSN to GS Neon (`src/oversteward/vintner/reader.py:21`). → hold
- `os.dream-kaizen` · live · Transcript → memory consolidation (systemd timer); kaizen queue from Fiscus lesson clusters + `kaizen` issues, plus the skill miner and trajectory-tag lint.
  - The largest package: dream/ is 12 modules and 3,758 lines; skills/ (621) and trajectory_tags.py (327) sit beside it. → hold
- `os.review-loop` · live · Assembled-input adversarial reviewer with a `.review-rounds` ledger; CI `reviewer-verdict` gate.
  - 5 modules, 1,371 lines; the assembler keeps a `.review-rounds` ledger and CI's reviewer-verdict job reads the PR body. → Tooling that checks the commits after the reviewed SHA, so a commit no verdict covers cannot merge (OS#534).
- `os.memory-deploy` · live · steward-memory → `~/.claude/projects/*/memory/`.
  - memory_deploy.py (108 lines). → hold
- `os.dispatch` · live · Issue intake and in-session pickup: the dispatch playbook, the architect card, the tribe-first queue, /project-status and the abandoned-work sweep.
  - intake/ (8 modules, 651 lines) ranks tribe work first (OS#613); shelve/ (5, 1,122) sweeps idle PRs. → One statement of the in-flight rule (L-DOC-1), and in-flight work derived from GitHub per capability (OS#640, PR 5).
- `os.estate-reports` · live · Nathan's views of the estate: the nightly Estate Brief vault note and the Estate Board.
  - brief/ (3 modules, 588 lines) and board/ (7, 1,141), each with its own GitHub client; the brief reads through the board's gh runner. → hold
- `os.page-judging` · live · Seeing estate pages as a visitor and a rater would: the signed probe through Cloudflare, the Gemini quality-rater pass, and the design bench.
  - judge/ (9 modules, 1,699 lines), probe/ (5, 406) and bench/ (6, 514). → hold
- `os.railway-cron` · live · Provisions a Railway cron service cloned from a sibling service's config, plus its own variables.
  - 5 modules, 421 lines. → hold
- `os.janitor` · live · Reclaims disk that sessions leave behind once nothing is using it.
  - 2 modules, 578 lines; prunes dead sessions' ~/.claude/tmp directories. → hold
- `os.estate-map` · building · This map: what the estate builds, where each capability lives, and its current and target shape; checked by the seventh session-start sweep.
  - OverSteward, AG and GS are seeded and their coverage floors measured (AG at 580 modules, 0 orphans, 0 overlaps; GS at 781 modules, 2 orphans, 0 overlaps, with services and connectors claimed file by file). → Per-repo slices deployed (PR 4), and in-flight work derived from GitHub (PR 5) — OS#640.

## Seams

- S-6 oversteward → all repos: `registry.yaml`; `shared/` deployed to both `~/.claude` homes; the dev family by sow PRs. In OverSteward the deployed side is symlinks, elsewhere copies
- S-8 oversteward → fiscus: `data/pipeline_history.jsonl` read from disk (dispatch subject)
- S-9 pickup repos → fiscus: `andon`-labelled issues → `shared/andon.jsonl`. **The aggregator is a stub that only echoes** (L-FI-1)
- S-10 fiscus → oversteward: `fiscus review trajectories` JSON feeds the dream/kaizen worklist
- S-11 grantspider → oversteward: `grantspider dq health --json` (stage health, locally or via `railway ssh`); Vintner reads `vintner.corpus_funnel_v`
- S-12 aigranthelper → oversteward: `/internal/ops/reports/` read and `/internal/ops/verdicts/` write, bearer tokens
- S-13 Railway, Sentry → oversteward: Liveness for contexts with a `railway:` block (AG, GS only); Sentry issues org-wide

## Invariants

- I-1: In-session pickup work never touches Nathan's live working tree (worktrees only) (`shared/skills/dispatch/playbook.md:25-28` (grantspider #426 postmortem))
- I-2: One in-flight **agent** PR per repo: dispatch refuses while an `<kind>/issue-` PR is open. The two surfaces disagree on whether `docs/` counts (L-DOC-1). `session/<name>` PRs are not covered (`shared/skills/dispatch/playbook.md:36` (includes `docs`), `SKILL.md:79` (omits it))
- I-3: Never bypass git hooks (`--no-verify`, `--admin`, hooksPath); never `git add -A` (`playbook.md:15,23`; `.claude/hooks/check_destructive_command.py`)
- I-12: Architect decisions address every audit finding in a STOPPED_FOR_INPUT report, not just the headline (memory `feedback_architect_decision_completeness`)
- I-13: Tests do not patch module globals when the fix is to expose the dependency as a parameter (`playbook.md:30`; `shared/references/architecture-principles.md` §Dependency Seams)
- I-15: Issues touching data-contract surface or the workflow name the test that would fail if the change were wrong (norm; not mechanized) (this document, 2026-04-25)
- I-16: Required CI checks are mostly off, by design: null on AG main/staging, GS main, OverSteward master, fiscus main. **Exceptions:** GS `staging` requires `ci`; gaudi main requires lint/security/test (GitHub branch-protection API, 2026-10-31; `.github/workflows/ci.yml:10-12`)
- I-21: One git worktree per session via `scripts/dev/new-session.sh` → `session/<name>`; `guard_main_worktree.py` refuses checkout/switch in the primary tree. OverSteward links the kit from `shared/`; other repos carry copies, currently drifted (L-DEV-1) (`shared/scripts/dev/new-session.sh:44`, `tests/test_deployed_links.py`)

## Liabilities

- H1-2 (oversteward; `TODO_BACKLOG.md` H3-4, H3-6): `/project-status` metrics partial: no issue→merged cycle time, no self-critique fire rate
- L-OD-1 (oversteward (ops); OS#58 (open)): Dormant OneDrive checkouts await triage-then-delete
- L-MKT-1 (oversteward (ops); OS#644 (open); `reports/2026-10-29-resource-page-outreach/` (untracked); `systemctl --user list-timers ag-outreach*`): The resource-page outreach pipeline, which sends live email on a weekday timer, is untracked files in the primary OverSteward checkout: no review, no tests, no history. Its user systemd units point at that path, and the laptop backups (restic and the WSL export) are its only copies
- L-DEV-1 (oversteward; `/sync-status`; OS#572): Dev-family copies drift: `new-session.sh` is one version behind in every repo; exchequer's `guard_main_worktree.py` differs; `worktree_doctor.py` is absent in wphelper, ai-assistants, exchequer, gaudi and pre-#571 in AG, GS, fiscus
- L-FI-1 (fiscus; Fiscus `src/fiscus/andon.py:20-27`, `subjects/*/contract.yaml`): Fiscus andon aggregation is a Phase-0 stub, and the AG/dispatch subject contracts are `status: stub`; exchequer and gaudi lack the andon template
- L-WSL-1 (oversteward (ops); `documentation/runbooks/wsl-recovery.md:192`): Docker Desktop volumes (compose databases) live in the `docker-desktop` distro, outside both the monthly export and the daily restic of `/home/natha`. OS#581–583 shipped the backups and closed; **nothing open tracks this gap**
- L-DOC-1 (oversteward; `documentation/ROADMAP.md:62,2282`, `shared/skills/dispatch/SKILL.md:3,79`): Dead pointers: `documentation/issue-to-pr-workflow.md` and `documentation/repos/` never existed but are cited by `ROADMAP.md` and `DETERMINISTIC_AGENTS.md`; the dispatch skill's description omits oversteward as a target; `SKILL.md:79` and `playbook.md:36` disagree on whether an open `docs/issue-` PR blocks dispatch

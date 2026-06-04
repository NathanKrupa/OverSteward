---
session_date: 2026-06-03
status: complete — workflow-registry pattern shipped (GS live) + GS git-workflow reconciled, renamed master→main, discipline hardcoded
branch_at_close: feat/workflow-registry (OverSteward PR #54 OPEN/CLEAN — ready to merge, Nathan's call)
---

## Where we left off

Two arcs in one session.

**Arc 1 — Workflow registry** (a tool-registry-style catalog of hybrid Python↔Claude workflows, one altitude up).
- Decisions (with Nathan): descriptor-docs-only (no filesystem sniffing) + per-repo topology (mirror the tool registry).
- **OverSteward PR #54 (OPEN/CLEAN)** — canonical `generate_workflow_registry.py` in `shared/scripts/workflows/` + byte-copy in `scripts/workflows/`, 15-test module, convention spec in `OVERSTEWARD.md`, tool-registry regenerated. *Ready to merge; left for Nathan.*
- **GS PR #1166 (MERGED)** — generator deployed + 3 seed descriptors (`enrich-drain`, `backfill`, `llm-extract`) + `data/workflow_registry.md` + CLAUDE.md line.
- Lesson: canonical shared scripts must lint clean under the *strictest* deploy-target config (GS ruff: line-length 99 + DTZ005), else the byte-copy breaks. Memory: `feedback_canonical_strictest_linter`, `reference_workflow_registry`.

**Arc 2 — GS git workflow: reconcile → rename → hardcode discipline.** GS `staging` had diverged from `master` (82 ahead / 22 behind). Root cause: `staging` had `required_linear_history=TRUE`, forcing every back-merge into a rebase (new SHAs) → master's commits never became staging ancestors → guaranteed divergence. AG never had this (its staging was non-linear → `main ⊆ staging`). Fixed end-to-end:
1. Disabled `required_linear_history` on GS `staging` (preserved all other protections).
2. **Reconciled** — GS PR #1177: merged master→staging (true merge); 2 sitemap conflicts resolved toward master (verified strict successor) while preserving staging-only 600s drain deadline. → master 0 ahead.
3. **Renamed `master`→`main`** (GitHub). Default still `staging`.
4. **Retargeted automation** — GS PR #1178 (`notify-ag-on-main.yml`, ci/pages triggers, watchdog, ci scripts, docs) + AG PRs #806/#807 (CI installs `grantspider@main`, `bump-gs-pin` guard → `refs/heads/main`). `gs-master-bump` event-type kept (contract key). Cross-repo bump chain VERIFIED (AG draft #808 from a GS main push).
5. **Hardcoded the invariant** — new `divergence-watchdog.yml`: fails CI + files a tracking issue when `main` is ahead of `staging`; auto-closes when healthy. PROVEN LIVE (#1179 opened then auto-closed).
6. **Back-merged** — GS #1180, AG #807 → **both repos at `main ⊆ staging`**.
7. **Railway**: Nathan repointed both GS Dagster services (webserver + daemon) to `main`.
8. **Obsidian canvas** revised to the resolved/working state: `GTD/Projects/The Almoner Business/Research/Git Workflow - GS vs AG.canvas`.

## Pending / next session

- **OverSteward PR #54** — OPEN/CLEAN, ready to merge (the workflow-registry system). Nathan to merge or review. (This SESSION_STATE commit rides on the same branch.)
- **GS issue #1181** — "Dagster-aware promotion gate" (`ops`/`architecture`). Designed-not-built: a Railway pre-deploy hook that queries the Dagster run-storage Postgres (private; no Cloudflare) for in-flight runs, polls-and-waits before redeploy, aborts+alerts on timeout. Scoped; implementation left open.
- **GS PR #1079** — stale feature (success-rate asset check), `MERGEABLE/UNSTABLE`, 6 days old. Nathan's call to rebase/verify/merge or close.
- **Optional** — add `staging` to `divergence-watchdog.yml` push triggers so the debt issue auto-closes immediately on back-merge (currently closes on next main push / daily cron).

## Context / gotchas for next session

- **GS branch model is now main + staging** (memory `project_gs_branch_model`): `main` = production (Railway Dagster + AG SHA-pin); `staging` = integration (default branch). Feature→staging; promote/hotfix→main as merge commits; back-merge main→staging as a TRUE merge commit, immediately, same sitting. Invariant: `git rev-list --count origin/staging..origin/main == 0`.
- **GS boy-scout base ref is now `origin/main`** (was origin/master): `GRANTSPIDER_BOY_SCOUT_BASE_REF=origin/main make verify` when branched off main; skip boy-scout (`GRANTSPIDER_CI_LOCAL_SKIP_BOY_SCOUT=1`) for pure merges/back-merges. Memory `feedback_boy_scout_rule` updated.
- GS main checkout was repointed local `master`→`main` (tracking origin/main, was 2 behind — `git pull` to ff). 6 temp worktrees removed. Nathan's 6 stashes + local feature branches untouched.
- Squash disabled in both repos; never re-enable (severs parent-links → #1010 storm). master-target = merge commit; staging-target = rebase or merge (linear history now OFF on staging).
- Memory written/updated this session: `project_gs_branch_model`, `feedback_canonical_strictest_linter`, `reference_workflow_registry`, `feedback_boy_scout_rule`.

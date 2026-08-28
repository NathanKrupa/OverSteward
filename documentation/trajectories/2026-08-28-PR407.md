# Trajectory — canonical-family audit fixes surfaced by the OS#401/#402 deploy

**Date:** 2026-08-28
**Branch:** session/sync-family
**Scope:** OverSteward-side corrections found while syncing the canonical `shared/scripts/dev/` family estate-wide after PR #403 / #405.

## What was asked

Deploy the rewritten guards (OS#401, OS#402) to every pickup repo and bring the family back into lockstep. `sow.py` is a Phase-2 stub, so the sync was run by hand: `/sync-status --family` → classify every drift by direction → one PR per repo.

## What was found on the OverSteward side

- `dev_family.HOOK_MEMBERS` lacked `guard_trunk_pull.py`, so the audit mapped it to `scripts/dev/` and reported it `absent-but-doctrine-referenced` in OverSteward itself, while the file has lived in `.claude/hooks/` since OS#345. A test asserting the mapping was seen red before the one-line fix.
- `tests/dev/test_with_test_env.py` and `tests/dev/test_guard_shared_venv.py` carried tests canon lacked (dotenv quote/comment semantics from OS#175; the deployed-hook-equals-canon assertion). Drift direction was measured against canon's git history: the repo copies were **novel**, not stale, so canon was promoted *from* them. The hook-equals-canon test now skips outside the canonical repo, since only OverSteward has `shared/`.
- `scripts/dev/sync-repos.{service,timer}` were never deployed into OverSteward's own `scripts/dev/`, though CLAUDE.md tells the operator to install them from there.

## What was found on the estate side (not fixed here)

- `.gitleaks.toml` drifts in aigranthelper and gaudi are **deliberate repo-local allowlists** for `.secrets.baseline`; overwriting them would make their secret-scan gate flag their own baseline. Filed as a decision issue.
- gaudi, fiscus and exchequer had never received the OS#241 `extend-exclude` for the family, so their `ruff-format` pre-commit reformatted canon on commit. That is the repos' side of the standing decision and rides in their sync PRs.

## What worked

- [process] Classifying drift by **direction** (does the repo blob match any historical canon blob?) before overwriting — 26 stale, 6 novel; two of the novel ones were canon's defect, two were repo config, two were formatter artefacts.
- [tooling] Running each target repo's *own* `ruff` with `--force-exclude` rather than reasoning about line lengths: the "would reformat" findings vanished for AG and GS, which isolated the three repos that actually lacked the exclusion.

## What did not

- The first sync pass committed with the repos' pre-commit hooks live and no exclusion in place — five of seven stalled. The pre-flight should have run each repo's `ruff format --check --force-exclude` on the copied files before committing.
- The memory habit "author a canonical script to the strictest linter across all targets" is superseded by OVERSTEWARD.md § OS#241 and misdirected the first diagnosis. Corrected in memory.

## Gates

- `pytest -q`: 1658 passed, 1 skipped (worktree, `PYTHONPATH` proven to resolve to the worktree)
- `gaudi check . --severity error --exit-code`: clean
- `cmp` canon ↔ `tests/dev/` for both promoted files: identical

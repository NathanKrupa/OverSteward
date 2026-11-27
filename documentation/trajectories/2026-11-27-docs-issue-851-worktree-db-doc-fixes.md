---
date: 2026-11-27
repo: oversteward
branch: docs/issue-851-worktree-db-doc-fixes
issues:
  - oversteward#851
session_kind: dispatch
duration: "8min to the recorded verdict (456s measured from the run's start stamp)"
reviewer: PASS findings=0 tokens=60000 (round 1; harness usage input 33, cache_creation 95154, cache_read 1470233, output 7993; $1.22, 104s)
---

# Trajectory — worktree_db.py is required wherever the doctor is; bench wording; a measured duration

## Context

OS#851 collected three doc defects found by the day's agents and reviewers: OVERSTEWARD.md scoped `worktree_db.py` to repos with a dockerized test DB although the doctor refuses without it in any repo; CLAUDE.md's "This repo declares it" read as "declares a bench" when OverSteward's `.worktree-bench` says `none`; and the #847 trajectory note carried a pre-review duration estimate instead of the measured 719 s.

## Trajectory

Read `worktree_doctor.py` before writing a word. `require_worktree_db()` is the first call in both `reconcile()` (behind `sweep` and `cleanup-merged`'s sweep step) and `_ownership()` (behind `check` and `teardown` whenever docker is in play), and `declares_no_bench()` is read only after it, so the declaration cannot spare a repo the sibling. Confirmed by running the doctor copied alone into a scratch directory against this `none` repo: `check` and `sweep` both exited 2 with "worktree_db.py is not deployed beside this script", and the deployed copy's `sweep` exited 0 with the no-bench message. `--no-docker` is the one path past it for `check` and `teardown`, and `repair` never asks, so the docs name those exceptions.

Grepping the whole of OVERSTEWARD.md for the same claim found two more forms of it than the issue named: the deploy table's "Used by" cell for `worktree_db.py`, and the sweep paragraph's "whose absence the other verbs tolerate silently", which says the opposite of the code. The playbook's "copy both files" rationale ("without it silently finds none") was the same stale claim in the canonical dispatch playbook; all three were corrected with the bootstrap comment. CLAUDE.md's sentence is hand-written (the file's managed block is its first five lines), so it was edited in place. The #847 note's duration follows the corpus precedent of a template-format figure with the measurement beside it.

## What worked

- [tooling] Running the doctor extracted alone into a scratch directory against the real repo — it turned "the code reads this way" into an observed exit 2 under a `none` declaration before the doc said so.
- [process] Grepping the whole document for the corrected claim, not only the line the issue cited — two more stale forms of it were in the same file, and one in the playbook.

## What didn't  (cost: trivial | minutes | hours | blocked)

- [tooling][trivial] A `tail --pid` wait on a pytest PID found by `pgrep` was refused by the permission classifier → remedy: wait on the background task's completion notification instead.

## What was learned

- [process] When a doc fix corrects what a function requires, check every verb that reaches it and the flags that skip it (`--no-docker`, `repair`) — a blanket "every verb refuses" would have been the next false claim → promote: none.

## Tools

- `shared/scripts/dev/worktree_doctor.py check|sweep` [used] — empirical check of the missing-sibling refusal under `.worktree-bench` = `none`.
- `scripts/review/assemble_review_input.py` [used] — reviewer input.

## Open threads

- Whether the doctor should need `worktree_db.py` in a repo whose `.worktree-bench` declares `none` is a code question, filed as its own `agent-finding` issue once this PR opened (linked from the PR).

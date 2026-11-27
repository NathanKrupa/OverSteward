---
date: 2026-11-27
repo: oversteward
branch: docs/issue-847-seed-editable-rows
issues:
  - oversteward#847
session_kind: dispatch
duration: "60min"
---

# Trajectory — promote the seeded-row test rule into the AG dev card

## Context

OS#847 is the kaizen queue's head: a cluster of six trajectory notes (aigranthelper#2675, #2727, #2762, #2771, #2832 and grantspider#2991) that the queue read as one recurring lesson. The issue asked for the rule as the six actually show it, promoted into the AG card and into the GS card only if the GS note had the same shape, with a card-test pin.

## Trajectory

Read the six trajectory notes from each repo's `origin/staging` and grepped the six PR bodies, then read the AG fixture that one of them added and aigranthelper#2731, an issue another PR body cited as the same failure. The five AG notes share one mechanism, seen from different sides: a seed migration copies the in-repo copy into an admin-editable row once, when the database is built, so a test that reads the row reads the bench's history, not the code. The notes show the row stale under `--reuse-db`, absent after a flush, already present for a `create`, and joined by later seeded rows for a positional read, and two of them show the same freeze in production. The fixes they made are the rule: delete and re-run the migration's own seed function, `update_or_create` by key, select by key.

grantspider#2991 does not share the shape. Its seed reads a module at upgrade time, every fresh build re-reads it, and its fix is a digest pin that names the re-seed migration, not a seed inside the test. So the rule went into `shared/agents/aigranthelper-dev.md` only, as one gotcha bullet, and the GS card is unchanged.

The pin went in first and was seen red (0 matches), then the bullet. Seven mutants on the bullet (delete it, state it twice, drop each load-bearing fragment, drop a citation) all reddened the pin on its own assertion.

Both sibling repos are private and OverSteward is public, so the bullet states the rule in its own terms and names the PRs by number only.

## What worked

- [process] Reading the PR bodies beside the notes — one body cited a sibling issue that supplied the "row absent after a flush" side of the same rule, which no note stated.
- [tooling] A byte-restoring mutant loop over the card bullet, each kill read off its `E` line — seven mutants, seven named kills, tree verified clean after.

## What didn't  (cost: trivial | minutes | hours | blocked)

- [process][trivial] Wrote the first red run's output beside the assigned scratch directory instead of inside it → remedy: create the assigned scratch directory before the first redirect.

## What was learned

- [process] A kaizen cluster is a lexical grouping, not a proof of one rule — read each member's fix and promote only the members whose fix is the rule; here five of six were → promote: none.

## Tools

- `git show origin/staging:documentation/trajectories/<note>` [used] — read the sibling notes without touching their checkouts.
- scratchpad `mutate.py` [NEW] — the card-bullet mutant loop.

## Open threads

- grantspider#2991's own lesson (pin a digest of module-seeded content, failure naming the re-seed migration) is a separate rule with one instance; it is not promoted here.

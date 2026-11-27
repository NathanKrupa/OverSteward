---
date: 2026-11-27
repo: oversteward
branch: docs/issue-591-lite-gate-ratchets
issues:
  - oversteward#591
session_kind: in-session-pickup
duration: "60min"
reviewer: PASS findings=0 tokens=95000 (round 1; harness: input 34, cache-create 115734, cache-read 1632665, output 9618)
---

# Trajectory — lite gates run every ratchet their full gate runs, and run again after each round

## Context

OS#591 began as one AG instance: the lite gate missed the SMELL-003 ratchet,
so `make verify` after review forced unreviewed commits. On 2026-11-27 it was
widened to the kaizen cluster `cluster:576a0e8625c89b88` (five instances:
oversteward#683, aigranthelper#2798, aigranthelper#2904, grantspider#3790,
grantspider#3932). The widened acceptance asked for a table of each dispatch
target's full-gate ratchets beside its card's lite gate, and for every ratchet
to be in the lite gate or excused.

## Trajectory

- Read the five notes first. OS#683 had already put AG's `make ci-gaudi` in
  the lite gate and named it in `pr-workflow.md`, so the issue's original ask
  was done. The other four notes showed two gaps that remained. AG#2904's
  forced commit was the untyped-function ratchet (`make ci-types`), which no
  card ran. AG#2904 and GS#3790 also failed because a round's fixes moved a
  ratchet and nobody re-ran the lite gate before the full gate.
- Built the table from each repo's shipped branch (`git show origin/<branch>`),
  never a checkout. Every full gate's ratchets: AG has types, SMELL-003 and
  ARCH-013. GS has boy-scout, the Dagster asset-check coverage ratchet and the
  coverage floor of 65. fiscus has boy-scout. wphelper has the DEP-001 cycle
  baseline inside its gaudi gate. exchequer and marketing-manager say "no
  ratchet" in their run-local headers. ai-assistants has lint and pytest only.
  So the gaps were AG types and GS asset-check coverage. GS's coverage floor
  needs the whole suite, so it stays in the full gate.
- Before writing either command into a card, ran each one with a negative
  fixture, in scratch copies outside the product checkouts. GS: an
  extracted `origin/staging` tree. `make ci-asset-check-coverage` with
  db-ready skipped took 5s and passed. With one baseline line removed it
  failed, naming the uncovered asset. AG: a `--reference` clone of `staging`.
  `make ci-types` took 19s and passed. With a public untyped function added it
  failed, at +1 (121 against 120).
- Edited the canonical cards and `pr-workflow.md`, then added pins in
  `tests/test_agent_cards.py`: the two new lite-gate steps, a check that
  doctrine and cards name the same `make ci-*` set, and the re-run instruction
  in the doctrine and in every pre-round card. Eight mutants, all killed.

## What worked

- [process] I read the cluster's notes before the issue's proposed fix. Most of the original ask was already done by OS#683, and the remaining gaps were types and asset-check coverage rather than SMELL-003 — reading the evidence first kept the change to the real gaps.
- [tooling] I proved each new lite-gate command on a disposable copy of the product repo's shipped branch: an extracted archive for GS, a `--reference` clone for AG. Both took seconds, the negative fixtures went red, and the product checkouts were not touched.
- [design] A set-equality test between the `make ci-*` targets the doctrine names and those the cards run. This one comparison catches drift in either direction, so it doubles as the "doctrine and cards agree" acceptance check.

## What didn't  (cost: trivial | minutes | hours | blocked)

- [tooling][trivial] My first types-ratchet negative fixture was a private function (`_probe`), and the ratchet passed it. The counter only counts public functions → remedy: read what a counter counts before writing its fixture.
- [tooling][trivial] `git checkout -B` in a scratch clone was refused by the main-worktree guard, which matched on shape → remedy: clone with `--branch` so no checkout is needed.
- [tooling][trivial] The first scratch clone was made with `--no-checkout`. Once the guard refused its checkout it was left as an empty husk in the scratchpad → remedy: none; scratch only.

## What was learned

- [process] A lite gate is owed on each round's fixes, not only before round 1: a fix moves a ratchet as easily as the first commit, and a ratchet first seen in the full gate forces a commit no verdict covers → promote: doctrine.
- [process] "Every ratchet the full gate runs" is checked by reading the full gate's own job list on the shipped branch. A card's prose summary is not enough: AG's card listed the untyped-function ratchet under `ci-light`, yet its lite gate did not run it → promote: none.

## Tools

- `git show origin/<branch>:<path>` [used] — read each repo's full gate without a checkout
- `git archive origin/staging | tar -x` and `git clone --reference` [used] — disposable copies for the negative fixtures
- `make ci-types` (aigranthelper), `make ci-asset-check-coverage` (grantspider) [used] — the two ratchet jobs added to the lite gates

## Open threads

- GS's coverage floor (`--cov-fail-under=65`) needs the whole suite and stays in the full gate only; a coverage drop still first appears after review.

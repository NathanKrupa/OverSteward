---
date: YYYY-MM-DD
repo: <repo-id>              # e.g. aigranthelper, grantspider, oversteward, fiscus
pr: <repo>#<N>               # filled in once PR exists
branch: <branch-name>
issues:                      # parent issues this pickup addresses
  - <repo>#<N>
session_kind: in-session-pickup
duration: <approximate>      # e.g. "90min", "2 sessions"
---

# Trajectory — <one-line summary of the change>

## Context

What problem did this pickup take on? Cite the issue and any related artifacts
(architecture row, prior PR, lesson). Two or three sentences. Should answer:
why now, and why this scope.

## Trajectory

Chronological narrative of the work — key decisions, dead-ends, pivots, scope
adjustments. Not a diff log; the path taken and why. Should be readable months
later by someone who wasn't there.

## What worked

Capture: approaches / patterns / framings that produced visible leverage.
Specific over abstract. One bullet per item.

- …

## What didn't  (cost: trivial | minutes | hours | blocked)

Capture: failed approaches, wrong assumptions, friction that wasted time — even
if it ultimately didn't block the PR.
Skip: one-off typos, anything that won't recur.
Format: `- [cost] <what happened> — <why it bit> → remedy: <proposed fix, or "none">`

- …

## What was learned

Capture: generalizable rules a future pickup in this surface should follow.
Rule + brief why.
Skip: restatements of what just happened.
Format: `- <rule> — <why> → promote: doctrine | memory | lessons.jsonl | none`

- …

## Tools

Capture: tools / commands / scripts used this pickup. Mark NEW ones built here.
Format: `- <tool/command> [used | NEW] — <what for>`

- …

## Open threads

Deferred items, follow-up issues filed, things spotted but out of scope. Each
line should be actionable or linkable.

- …

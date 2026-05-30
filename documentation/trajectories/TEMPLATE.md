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

Approaches, patterns, tools, or framings that produced visible leverage. One
bullet per item. Specific over abstract.

- …

## What didn't

False starts, wrong assumptions, friction. Include things that wasted time
even if they ultimately didn't block the PR. The review-fork subagent reads
these to identify recurring drag.

- …

## What was learned

Generalizable lessons — what a future pickup in this surface should do
differently or remember. These are the candidate inputs for promotion into
`Fiscus/shared/lessons.jsonl`, `~/.claude/projects/.../memory/`, or per-repo
doctrine. Phrase each as a rule + brief why.

- …

## Open threads

Deferred items, follow-up issues filed, things spotted but out of scope. Each
line should be actionable or linkable.

- …

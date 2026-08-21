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

> **Per-lesson `category` — required on every new note.** Tag each lesson bullet
> in the three capture sections below (*What worked*, *What didn't*, *What was
> learned*) with one value from this fixed vocabulary, written as a leading
> `[category]`:
>
> - `design` — architecture, structure, layering, interface/seam decisions
> - `functional` — feature behavior, correctness, what the code does
> - `tooling` — scripts, commands, dev environment, automation/CI
> - `process` — workflow, dispatch, review, PR mechanics, coordination
> - `outcome` — what shipped and its measured result or impact
>
> One note routinely mixes categories — tag each bullet on its own.
>
> **The tags are enforced at commit time**, by the `trajectory-tags` pre-commit
> hook (`scripts/lint/trajectory_tags.py`, OS#329). It validates only the notes a
> commit adds or modifies — notes written before the gate existed are exempt and
> are never retro-tagged. An untagged bullet is not a style lapse: it resolves to
> `uncategorized`, which drops it out of the analyzer's two headline sections,
> and an untagged `promote:` removes it from the promotion worklist entirely.

## What worked

Capture: approaches / patterns / framings that produced visible leverage.
Specific over abstract. One bullet per item.
Format: `- [category] <what worked> — <why it helped>`

- [tooling] Ran the gaudi gate against a second `origin/master` baseline worktree — comparing the finding delta (not absolute counts) kept a pre-existing smell from reading as a regression.
- …

## What didn't  (cost: trivial | minutes | hours | blocked)

Capture: failed approaches, wrong assumptions, friction that wasted time — even
if it ultimately didn't block the PR.
Skip: one-off typos, anything that won't recur.
Format: `- [category][cost] <what happened> — <why it bit> → remedy: <proposed fix, or "none">`

- [process][minutes] Mistook an open session PR for an agent race — its branch didn't match the agent pattern → remedy: confirm the branch matches `^(fix|feat|ci|refactor|cleanup)/issue-<n>-` before stopping.
- …

## What was learned

Capture: generalizable rules a future pickup in this surface should follow.
Rule + brief why.
Skip: restatements of what just happened.
Format: `- [category] <rule> — <why> → promote: doctrine | memory | lessons.jsonl | none`

`→ promote:` is **required on every bullet in this section**, and its target must
be the **last thing on the bullet** (an optional full stop aside). The consumer's
regex is end-anchored, so a target followed by more prose — `→ promote: memory,
and then more` — is invisible downstream and the gate rejects it. Use `none` when
the lesson genuinely shouldn't be promoted; that is a judgement, not a skip.

- [design] Classify lessons at capture time, not read time — the author knows the lesson's intent, which keeps the downstream review deterministic → promote: doctrine.
- …

## Tools

Capture: tools / commands / scripts used this pickup. Mark NEW ones built here.
Format: `- <tool/command> [used | NEW] — <what for>`

- …

## Open threads

Deferred items, follow-up issues filed, things spotted but out of scope. Each
line should be actionable or linkable.

- …

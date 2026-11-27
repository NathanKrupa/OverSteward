---
date: 2026-11-27
repo: oversteward
branch: docs/issue-849-mm-merge-exception
issues:
  - oversteward#849
session_kind: in-session-pickup
duration: "45min"
reviewer: PASS findings=0 tokens=935454
---

# Trajectory — marketing-manager takes the ordinary manual-merge path

## Context

OS#849: PR #842 (OS#841) wrote a marketing-manager exception into dispatch
playbook step 16 and into `shared/agents/marketing-manager-dev.md`, because the
repo then allowed squash, rebase and auto-merge. Its settings now allow merge
commits only, with auto-merge off, so the exception had outlived its cause.
The issue tracks marketing-manager#4.

## Trajectory

Measured the premise first: `gh api repos/NathanKrupa/marketing-manager`
returned merge on, squash, rebase and auto-merge off. Removed both exception
sentences from step 16 (the auto-merge one and the merge-method one) and
rewrote the card's merge paragraph in the shape the exchequer and OverSteward
cards already use ("Auto-merge is switched off in this repo", then the hand
merge), adding the settings measurement to its confirm-live block. No test
pinned any card's merge path, so added two: each auto-merge-off card states
that and its hand-merge command, and no dev card or dispatch doc carries
"X is allowed" / "allows X" wording for auto-merge, squash or rebase. Both
were run against the `origin/master` card and playbook and failed four ways
for the stated reasons before the fix was restored.

## What worked

- [process] Measuring the repo settings before editing: the issue's premise is the only thing that makes deleting the exception safe, and it took one API call.
- [design] Matching the existing manual-merge wording of the exchequer and OverSteward cards let one parametrized test pin all three cards instead of one bespoke pin.

## What didn't

- [tooling] A full pytest plus gaudi run in one foreground command passed the auto-background threshold; waiting on it took several attempts at a sanctioned wait shape. Launch a gate that long with `run_in_background` from the start.

## What was learned

- [process] A doc exception tied to a settings issue ("until X#4 lands") needs its own follow-up issue to retire it, as OS#849 was; without one the exception text outlives the setting it describes. → promote: lessons.jsonl
- [functional] The exception-wording regex has to avoid step 16's own "auto-merge not allowed" fallback text; requiring "is/are allowed" or "allows X" kept that line clear. → promote: none

## Tools

- `gh api repos/<owner>/<repo> --jq '{merge:.allow_merge_commit,squash:.allow_squash_merge,rebase:.allow_rebase_merge,auto:.allow_auto_merge}'`
- `tests/test_agent_cards.py -k merge`

## Open threads

- After merge, comment on and close marketing-manager#4; the shared deploy is the orchestrator's.

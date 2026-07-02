---
name: refresh-docs
description: "Monthly cadence sweep that reconciles OverSteward's dated status docs (Stewards_Ledger.md, MASTER_TODO.md, TODO_BACKLOG.md, TODO_COMPLETED.md) against current issue/PR/git state. Status docs encode dated state and drift unprompted within ~5 weeks, unlike the spec docs (OVERSTEWARD.md) which stay accurate. Read-only reconciliation — proposes edits, waits for Nathan's approval, never auto-writes the docs. Use when a month has passed since the last refresh, when the ledger's `Last Updated` is stale, or when Nathan asks to \"refresh docs\", \"reconcile the ledger\", \"sweep the TODOs\", or runs /refresh-docs."
---

# /refresh-docs — dated-status-doc cadence sweep

OverSteward's **status** docs decay within ~5 weeks — they encode dated state
(issue numbers, PR numbers, "Last Updated", completed/active checklists) and
drift silently as merges land and issues close. The **spec** doc
(`OVERSTEWARD.md`) stays accurate because it describes design, not state, so it
is deliberately **out of scope** here.

This skill runs a monthly reconciliation: compare each status doc against the
live issue/PR/git state, then **propose** the corrections and wait for Nathan's
sign-off. It never writes the docs itself (propose, don't impose — OVERSTEWARD.md
principle 6).

## Invocation

```
/refresh-docs
```

No arguments.

## Cadence

**Monthly.** The trigger is either:

- Nathan asks for it explicitly, or
- the ledger's `**Last Updated:**` line is more than ~4 weeks old (check it in
  step 1 and surface the age).

Run from the OverSteward working tree (or a session worktree — use
`.venv/bin/python` there). Read-only against GitHub and git; the only writes are
the doc edits Nathan approves at the end.

## Docs in scope

| Doc | What decays |
|-----|-------------|
| `Stewards_Ledger.md` | `**Last Updated:**` date; "Current State" narrative; recent session log |
| `MASTER_TODO.md` | `## Active` items whose issue/PR has since closed or merged |
| `TODO_BACKLOG.md` | queued items already picked up, closed, or superseded |
| `TODO_COMPLETED.md` | should gain rows for work merged since the last refresh |

`OVERSTEWARD.md` is **not** swept — it is a spec, not a status doc. If a genuine
spec inaccuracy surfaces incidentally, note it for a separate PR rather than
editing it here.

## Reconcile steps

### 1. Read the four docs and note their dated state

Read each doc. Capture the ledger's `**Last Updated:**` date and every
issue/PR number referenced in the `## Active` / backlog sections. Report the
ledger's age up front.

### 2. Gather live state for OverSteward

```bash
gh issue list --repo NathanKrupa/OverSteward --state all \
  --json number,title,state,closedAt --limit 200
gh pr list --repo NathanKrupa/OverSteward --state all \
  --json number,title,state,mergedAt,closedAt --limit 200
git log --oneline --since="5 weeks ago" master
```

### 3. Diff docs against live state

For each doc, find the drift:

- **MASTER_TODO `## Active`** — any item whose referenced issue is now
  `CLOSED` or whose PR is `MERGED`/closed → propose moving it to
  `TODO_COMPLETED.md` (with the merge/close date) and dropping it from Active.
- **TODO_BACKLOG** — any queued item now closed, dispatched, or superseded →
  propose removing or annotating it.
- **TODO_COMPLETED** — any PR merged since the ledger's `Last Updated` that has
  no completed-row → propose adding one (date + PR/issue numbers + one line).
- **Stewards_Ledger** — propose bumping `**Last Updated:**` to today and adding
  a short "Current State" reconciliation note only if the narrative is now
  materially wrong. Do not rewrite prose that is still accurate.

### 4. Present the proposal and wait for approval

Show Nathan a compact per-doc diff of the proposed edits. **Wait for explicit
approval before writing.** If he approves, apply the edits in a `docs/` branch
and open a PR (this repo routes all changes through PRs to `master`); if he
declines any item, drop it.

### 5. No silent writes

This skill proposes. The only writes are Nathan-approved doc edits, and only via
a PR — never a direct commit to `master`, never `SESSION_STATE.md` (gitignored,
local-only).

## Rules

- **Status docs only.** Never edit `OVERSTEWARD.md` (spec) or `SESSION_STATE.md`
  (gitignored scratch) from this skill.
- **Propose, don't impose.** No doc write without Nathan's sign-off.
- **All writes via PR to `master`.** Branch protection forbids direct commits.
- **Preserve accurate prose.** Only touch lines that are demonstrably stale;
  don't churn wording that is still correct.

## Related

- `/project-status` — live pipeline dashboard the reconciliation reads against
- `/sync-status` — governance-drift report (the config-side analogue of this
  doc-freshness sweep)

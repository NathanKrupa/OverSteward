---
name: answer-flow
description: Parse Nathan's answers from `C:\Users\natha\OneDrive\Documents\Nathan Writing\Obsidian\GTD\Projects\The Almoner Business\Research\Chestertron Inbox.md`, post each as a GitHub comment on the referenced issue, swap `needs-input` → `ready-for-agent`, and clean the answered block from the Inbox. Completes the intent-capture loop (agent asks → morning-digest surfaces → Nathan answers → answer-flow posts → agent re-dispatched). Invoked at session start or ad-hoc via `/answer-flow`.
---

# /answer-flow — Chestertron Inbox → GitHub

Completes the dispatch intent-capture loop. When agents hit ambiguity they comment `@nathankrupa question:` and label `needs-input`. The morning-digest skill surfaces those in `C:\Users\natha\OneDrive\Documents\Nathan Writing\Obsidian\GTD\Projects\The Almoner Business\Research\Chestertron Inbox.md`. Nathan writes answers under each question during his morning review. This skill reads those answers, posts them back to GitHub, and preps the issue for re-dispatch.

## Invocation

- **Primary:** scheduled remote agent, hourly, via `/schedule`.
- **Secondary:** session-start auto-run (Chestertron already reads the Inbox at session start).
- **Tertiary:** ad-hoc via `/answer-flow`.

### Install the hourly schedule

```
/schedule create --name answer-flow --cron "0 * * * *" --skill answer-flow
```

## Inbox format expected

Morning-digest writes blocks in this shape:

```markdown
## Morning agent digest — Monday, April 14th 2026

### aigranthelper #148 — Stripe webhook signature test (3d old)
**Question:** Should the test mock the webhook secret or read from env?
**Link:** https://github.com/NathanKrupa/aigranthelper/issues/148
**Status:** ⏰ blocking (>48h)

### grantspider #170 — Parser for new CA source (8h old)
**Question:** The source returns JSON wrapped in <pre> tags — strip HTML?
**Link:** https://github.com/NathanKrupa/grantspider/issues/170
**Status:** active

---
```

Nathan writes an `**Answer:**` line under the question he wants to answer:

```markdown
### aigranthelper #148 — Stripe webhook signature test (3d old)
**Question:** Should the test mock the webhook secret or read from env?
**Link:** https://github.com/NathanKrupa/aigranthelper/issues/148
**Status:** ⏰ blocking (>48h)
**Answer:** Use a fixed test secret constant inside the test module. Don't read from env — too fragile for CI.
```

A block is **answered** if it contains a non-empty `**Answer:**` line (anything after the marker counts, trimmed).

## What this skill does

### 1. Read the Inbox

Read `C:\Users\natha\OneDrive\Documents\Nathan Writing\Obsidian\GTD\Projects\The Almoner Business\Research\Chestertron Inbox.md`. Identify each block that starts with `### <repo> #<n>`. Parse:
- repo (token before `#`)
- issue number
- link (from the `**Link:**` line)
- answer text (everything after `**Answer:**` up to the next `###` or `---`, stripped of surrounding blank lines)

### 2. For each answered block

Loop. **Transactional per issue** — a failure on block N doesn't stop block N+1.

For each answered block:

a) **Post the comment**:
```bash
gh issue comment <n> --repo NathanKrupa/<repo> --body "[answering question from <date-of-digest>]:

<answer-text>"
```

Use today's date if the digest date isn't parseable.

b) **Swap labels**:
```bash
gh issue edit <n> --repo NathanKrupa/<repo> \
  --remove-label needs-input \
  --add-label ready-for-agent
```

c) **Record result** (success / error + reason).

### 3. Clean the Inbox

Rewrite `C:\Users\natha\OneDrive\Documents\Nathan Writing\Obsidian\GTD\Projects\The Almoner Business\Research\Chestertron Inbox.md`:
- **Preserve untouched:**
  - Frontmatter (`---` at top through closing `---`)
  - Navigation line (`[[Dashboard]] - [[In Box]] - [[Topic Dashboard]]`)
  - Explainer paragraph ("Chestertron, this is your inbox…")
  - Empty-state line (`*(Inbox empty…)*` if present)
  - Any Nathan notes NOT inside a digest answered block
  - The `## Morning agent digest — <date>` header (unchanged unless ALL of its blocks are answered — then remove the whole section)
  - Any unanswered `###` blocks within a digest

- **Remove:**
  - Answered `###` blocks (where posting succeeded)

- **Update frontmatter:**
  - `date modified` → today in project format (`dddd, MMMM Do YYYY`)

### 4. Report

Print a compact summary:

```
Answer-flow report:

Posted:
  ✓ aigranthelper#148 — answer posted, label swapped
  ✓ grantspider#170 — answer posted, label swapped

Skipped (no answer):
  - wphelper#45 — awaiting Nathan

Errors:
  - aigranthelper#999 — gh comment failed: Not Found (issue closed?)

Inbox: 1 answered block removed, 1 unanswered block retained.
```

If nothing answered: `No answered blocks in Chestertron Inbox.`

## Rules

- **Transactional per issue.** One failure ≠ all failures.
- **Idempotency:** once a block is answered + posted + removed, re-running is a no-op (block is gone).
- **Never touch Inbox frontmatter fields other than `date modified`.**
- **Never delete Nathan's notes outside of digest-answered blocks.**
- **Do not spawn agents.** Answer-flow only posts + labels. Re-dispatch is a separate action (Nathan runs `/dispatch` again, or v2 `/drain` picks it up).
- **If `ready-for-agent` label doesn't exist on the target repo**, fall back to removing `needs-input` only, and warn in the report.
- **If the issue is already closed**, post the comment anyway (value for audit trail), skip label swap, note in report.

## Why this is the final leg

Without this handler:
- Agents ask questions → they sit forever
- Nathan answers in Inbox → answers never reach GitHub
- Agents re-dispatched → no context, ask the same question again

With this handler, the loop closes: ambiguity → question → digest → answer → comment → re-dispatch with context.

## Related

- `/dispatch` — produces `needs-input` blocks via intent-capture
- `/morning-digest` — surfaces them in the Inbox
- `/questions` — ad-hoc read-only view
- ai-assistants #46 — `/drain` skill (v2) will invoke answer-flow + auto-redispatch answered items

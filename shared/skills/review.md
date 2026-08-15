---
benefits-from: [security-audit]
---
ABOUTME: Pre-landing code review skill with two-pass system and scope drift detection.
ABOUTME: Adapted from garrytan/gstack's /review pattern for House of Krupa contexts.

# Review — Pre-Landing Code Review

A structured code review workflow to run before merging any PR or committing significant changes. Catches bugs, scope drift, and quality issues before they land.

## When to Use

Invoke `/review` when:
- A feature branch is ready to merge
- A significant commit (50+ lines changed) is about to land
- Nathan asks for a review of recent changes
- Before any deployment

## Phase 1: Scope Assessment

1. **Identify the change set.** `git diff main...HEAD` (or appropriate base branch).
2. **Categorize the diff size:**
   - Small: < 50 lines changed
   - Medium: 50–200 lines changed
   - Large: 200+ lines changed
3. **Summarize intent.** In one sentence, what is this change trying to accomplish?

## Phase 2: Scope Drift Detection

Compare the stated intent against the actual diff:
- Are there changes unrelated to the stated purpose?
- Are there "while I was here" cleanups mixed with functional changes?
- Should this be split into multiple commits or PRs?

Flag drift but don't block on it — Nathan decides whether to split.

## Phase 2.5: Security-Pass Offer (web-surface repos only)

This skill declares `benefits-from: [security-audit]` (see frontmatter). On a
web-surface repo, a review is stronger when the security pass has already run.

**Gate — only offer when both hold:**
- The repo under review is a web-surface repo: **aigranthelper** or
  **ai-assistants** (the contexts tagged `web` in `registry.yaml` that expose a
  browser/API attack surface).
- `/security-audit` has NOT already run this session.

When both hold, offer — do not force:

> This is a web-surface repo and the security pass hasn't run this session.
> Want me to run `/security-audit` on this diff first, before the critical pass?

If Nathan accepts, run `/security-audit` inline and fold its findings into the
Phase 3 Critical Pass under **Security**. If he declines (or the gate doesn't
hold), continue straight to Phase 3. This is a lightweight offer, not a chain —
skip it entirely for non-web repos and never block the review on it.

## Phase 3: Critical Pass

Review the entire diff for issues that MUST be fixed before landing:

- **Correctness:** Logic errors, off-by-one, wrong variable, missing edge cases
- **Security:** Injection, XSS, exposed secrets, broken auth (reference `/security-audit` for details)
- **Data loss:** Destructive migrations, dropped columns, overwritten files
- **Breaking changes:** API contract changes, renamed exports, changed signatures
- **Test coverage:** Are new code paths tested? Are existing tests still valid?

For each finding:
```
[CRITICAL] file:line — description
  Why: [why this matters]
  Fix: [suggested fix]
```

## Phase 4: Quality Pass

Review for issues that SHOULD be fixed but aren't blocking:

- **Naming:** Do names describe what the code does? (per House of Krupa naming rules)
- **Duplication:** Is there copy-pasted code that should be extracted?
- **Complexity:** Are there deeply nested conditionals or long functions?
- **Comments:** Are ABOUTME headers present on new files? Are comments accurate?
- **Style:** Does the code match surrounding style?
- **Error handling:** Are errors caught and handled appropriately?
- **Performance:** Any obvious N+1 queries, unbounded loops, or missing pagination?

For each finding:
```
[QUALITY] file:line — description
  Suggestion: [what to improve]
```

## Phase 5: Test Assessment

1. **Run the test suite.** Do all tests pass?
2. **Coverage check.** Are there new code paths without tests?
3. **Test quality.** Are tests testing real behavior (not mocked behavior)?
4. **Missing edge cases.** What inputs or states aren't tested?

```
Tests: [pass/fail count]
New code paths without tests: [list]
Suggested test additions: [list]
```

## Phase 6: Documentation Check

- Do new features have corresponding documentation updates?
- Are CLAUDE.md or context files affected by this change?
- Are any README sections now stale?

## Report Format

```
## Code Review: [branch or commit description]
**Diff size:** [small/medium/large] ([N] files, [+X/-Y] lines)
**Intent:** [one-sentence summary]
**Scope drift:** [none / minor / significant]

### Critical Issues ([count])
[findings from Phase 3]

### Quality Issues ([count])
[findings from Phase 4]

### Test Assessment
[from Phase 5]

### Documentation
[from Phase 6]

### Verdict: [APPROVE / APPROVE WITH FIXES / REQUEST CHANGES]
[one-sentence summary of recommendation]
```

## Principles

- **Be specific.** Every finding references a file and line.
- **Be actionable.** Every finding includes a suggested fix or direction.
- **Be proportional.** Small diffs get a lighter review. Don't nitpick style on a 3-line bugfix.
- **Separate critical from quality.** Nathan can ship with quality issues; he can't ship with critical issues.
- **No sycophancy.** "LGTM" is only valid when the code actually looks good.

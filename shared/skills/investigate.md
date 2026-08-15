ABOUTME: Systematic debugging skill with scope-lock and hypothesis discipline.
ABOUTME: Adapted from garrytan/gstack's /investigate pattern for House of Krupa contexts.

# Investigate — Systematic Debugging

A structured debugging workflow that enforces root-cause discipline. Use this when facing a non-trivial bug, test failure, or unexpected behavior.

## When to Use

Invoke `/investigate` when:
- A test failure has a non-obvious cause
- A bug requires more than a one-line fix
- You've already tried one fix and it didn't work
- The error message doesn't point directly to the problem

## Phase 1: Scope Lock

Before touching any code:

1. **Identify the affected area** — which files, modules, or components are involved?
2. **Declare a scope boundary** — state explicitly: "I will only modify files in [directory/module] until the root cause is found."
3. **Do NOT edit files outside this boundary** without explicitly expanding scope and explaining why.

This prevents the common failure mode of "fix-hopping" — making speculative changes across the codebase hoping something sticks.

## Phase 2: Root Cause Investigation

1. **Read the error carefully.** The error message often contains the solution. Do not skip past stack traces.
2. **Reproduce consistently.** Run the failing command/test and confirm the failure. If it's intermittent, identify the conditions.
3. **Check recent changes.** `git diff`, `git log --oneline -10`, uncommitted changes. What changed?
4. **Gather evidence.** Read the relevant source files completely. Don't skim.

## Phase 3: Pattern Analysis

1. **Find working examples.** Is there similar code elsewhere in this codebase that works? Compare it to the broken code.
2. **Read the reference implementation.** If implementing a pattern (framework feature, library API), read the docs or source — completely, not just the first example.
3. **Identify differences.** What's different between working and broken?
4. **Map dependencies.** What does this code depend on? Config, env vars, imports, database state?

## Phase 4: Hypothesis Testing

The **3-Strike Rule:**

1. **State your hypothesis clearly** — "I believe the root cause is X because Y."
2. **Make the smallest possible change** to test the hypothesis.
3. **Run the test/repro.** Did it work?
   - **Yes:** Proceed to Phase 5.
   - **No:** Form a NEW hypothesis. Do NOT add another fix on top.
4. **If 3 hypotheses fail:** STOP. Say "I don't understand what's causing this" and escalate to Nathan. Do not keep guessing.

**Rules:**
- ONE hypothesis at a time. Never apply multiple fixes simultaneously.
- Revert failed hypotheses before trying the next one.
- If you don't understand something, say so. "I don't know" is always better than a wrong guess applied to production code.

## Phase 5: Implementation

1. Write or update a test that captures the bug (it should fail without the fix).
2. Apply the minimal fix.
3. Run the test — confirm it passes.
4. Run the full test suite — confirm no regressions.
5. If the fix touches shared code, check callers.

## Phase 6: Verification Report

After fixing, output:

```
## Investigation Report

**Symptom:** [what was observed]
**Root Cause:** [what actually caused it]
**Fix:** [what was changed and why]
**Hypotheses Tested:** [list any wrong hypotheses and why they were wrong]
**Regression Risk:** [what else could this fix affect]
**Tests:** [which tests cover this]
```

## Anti-Patterns This Skill Prevents

- **Fix-hopping:** Making speculative changes across multiple files
- **Stack-of-fixes:** Applying fix after fix without reverting failures
- **Symptom-fixing:** Addressing the visible error without finding the cause
- **Scope creep:** "While I'm here, let me also fix..."
- **Guessing without evidence:** Changing code based on vibes rather than analysis

# Issue-to-PR Workflow (in-session)

How an in-session Claude Code assistant takes a GitHub issue from "ready for work" to "merged PR." Used directly by the assistant Nathan is chatting with — no subagent dispatch, no background harness. The conversational form is plain English: "let's work AG #415" / "grantspider 150."

This document is descended from the now-retired `dispatch/playbook.md`. The 19 steps survive; the subagent ceremony does not. Heartbeat-commit and dispatcher-verify (workarounds for the Claude Code harness false-positive completion bug) are removed — they were defenses against silent subagent termination, which doesn't apply when the work runs in the parent session.

## Identity & Intent

You are an in-session PR worker. Nathan has pre-approved the work in the issue picked up. Your output is a merged PR or a clean stop with a question. You are NOT a code reviewer, a designer, or a refactorer.

One issue → one PR → CI green (or local-equivalent) → auto-merge → done. No side effects on Nathan's live working tree.

## Non-negotiables

- **Never** use `--no-verify`, `--admin`, or any bypass flag
- **Never** force-push to any branch
- **Never** commit files matching `.env*`, `*.pem`, `*.key`, `credentials*`, `secrets*`, `local_settings*`
- **Never** run migrations, drop tables, delete external data, or modify CI config of other repos
- **Never** silently fix unrelated pre-existing failures — report them, don't mask them
- **Never** expand scope beyond the issue's acceptance criteria
- **Never** use `git add -A` or `git add .` — stage specific files only
- **Never** guess when ambiguous — stop and ask Nathan
- **Never** run any git command that mutates Nathan's live working tree state. The forbidden list is illustrative, not exhaustive: `git checkout` (any form, including `git checkout origin/main -- .`), `git pull`, `git reset`, `git restore`, `git stash` (any variant — `--keep-index`, `-u`, push, pop, drop), `git rebase`, `git merge`, `git clean`, `git rm`. **The forbidden list applies inside dispatch worktrees too, not only in the main checkout.** The worktree exists to isolate `git add` (specific files) / `git commit` / `git push` / `git branch` from Nathan's tree — not to enable the forbidden ops. `git stash` is especially dangerous: the stash list is repo-wide (one stack shared across all worktrees), so a stash inside a worktree pollutes the same list the main checkout sees and a `pop` can land on the wrong tree. (Postmortem: grantspider PR #543, 2026-04-28.) The test is: if the operation could surprise a human running `git status` or `git stash list` in the main repo right now, it's forbidden — wherever you are.
- **Never** fall back to Nathan's live working tree when the temp worktree fails. If step 5 or step 6 fails, the correct response is STOP, not "work in the main checkout instead." Touching the live tree as a fallback leaves uncommitted state, switched branches, and contaminated HEAD — Nathan's open terminals and IDE will see the mess. (grantspider #426 postmortem, 2026-04-22.)
- **Never** reach into the main checkout for a "baseline" or "before" view of files. If you need to compare your changes against pristine master (gaudi delta, lint delta, test delta), create a SECOND temp worktree at `origin/<default-branch>` and run the comparison there. **Do NOT** `git stash` your way to a clean view of the main checkout — even with `--keep-index` and even if you believe the working tree is clean, the operation can capture and then discard untracked uncommitted files (notes, drafts, runbooks, session-state docs). This happened on grantspider #538 (PR #539 postmortem, 2026-04-28). The correct pattern is in "The 'baseline-comparison snapshot' pattern" below.
- **Never** patch module globals in tests (`monkeypatch.setattr("module.attr", fake)` for `subprocess`, HTTP clients, filesystem, clock, `os.environ`, `random`) when the fix is to expose the dependency as a parameter. See `~/.claude/shared/references/architecture-principles.md` §Dependency Seams. If a test needs a patched global, the code under test has a hidden dependency — fix the signature, not the test.

## Workflow (19 steps, in order)

### Pre-flight

1. **Concurrency check.** Scan repo for open PRs with branch pattern `^(fix|feat|ci|refactor|cleanup)/issue-<n>-`. If a PR matching THIS issue number exists as a draft (re-pickup case after a question/answer cycle), remember its branch name for step 6. If any OTHER agent PR is open on the repo with ANY issue number, STOP — confirm with Nathan that it's safe to proceed.
2. **Branch collision recovery.** Compute the target branch name `<type>/issue-<n>-<slug>`. Check if it exists on origin:
   - **Not present** → proceed.
   - **Present, 0 commits ahead of default branch** (orphan from prior failed attempt) → delete it: `git push origin --delete <branch>`. Note the cleanup. Proceed.
   - **Present, has commits ahead** AND matches the step-1 draft PR → carry over (step 6 will check out this branch).
   - **Present, has commits ahead** AND no matching draft PR → STOP and ask Nathan. Do not destroy work.
3. **Label `agent-in-progress`** on the target issue: `gh issue edit <n> --add-label agent-in-progress --repo <owner>/<repo>`. Create the label first if it doesn't exist. (Advisory in the in-session model — `/project-status` and `/questions` use it to avoid surfacing the issue twice.)

### Worktree setup (isolation — keeps Nathan's live working tree untouched)

4. **Fetch (and prune husks).** `cd` into the repo. Run `git worktree prune 2>/dev/null || true` to drain any stale admin-metadata husks left by prior work (see "Windows + OneDrive" note below). Then run `git fetch origin <default-branch>`. Do NOT run `git checkout` or `git pull` on the main working tree — Nathan may be editing there.
5. **Create worktree.** Generate a temp path: `WORKTREE_PATH=$(mktemp -d -t inwork-<repo>-<n>-XXXX)` (on Windows bash: `WORKTREE_PATH="$TEMP/inwork-<repo>-<n>-$RANDOM"; mkdir -p "$WORKTREE_PATH"`). Then:
   - **Continuing existing draft PR** (from step 1): `git worktree add "$WORKTREE_PATH" <existing-branch>`
   - **Fresh start:** `git worktree add -B <target-branch> "$WORKTREE_PATH" origin/<default-branch>`
6. **Switch to worktree, then verify viability.** `cd "$WORKTREE_PATH"`. Then run these three checks — all must pass before you proceed:
   - `git rev-parse --is-inside-work-tree` → must print `true`.
   - `git rev-parse --show-toplevel` → must print a path that starts with `$WORKTREE_PATH`.
   - `ls "$WORKTREE_PATH" | head -3` → must show repo contents (at minimum a `.git` reference and at least one tracked file like `pyproject.toml` or `README`). An empty directory means `git worktree add` registered metadata but the checkout never populated — a known Windows+OneDrive fragility.

   **If any check fails, STOP.** Tell Nathan which check failed; do NOT attempt to work around the failure by `cd`ing back into the main repo or by running `git checkout` on Nathan's live tree.

   ALL subsequent git, test, lint, edit operations happen in `$WORKTREE_PATH`. Nathan's live working tree is never touched.

   **Mid-run vanishing worktree.** If a `git` command later in the workflow fails with "fatal: not a git repository" or similar, the temp tree has disappeared mid-flight. Same rule: STOP, do not migrate work to the main checkout. Tell Nathan; any unpushed commits are lost.

### Issue scope validation

7. **Read issue.** `gh issue view <n> --repo <owner>/<repo> --comments`. Read body AND latest comments. Comments often override the original body (Option picks, clarifications).
8. **Preflight the issue.** Bail out if:
   - Body contains "Options:" or "Approaches:" with no picked choice in comments
   - No "Acceptance" or checkbox list exists in body or comments
   - Label `needs-scoping` or `reject-close` is present
   - "Already done" case: verify each acceptance item against current code. If all satisfied, STOP and tell Nathan: "Acceptance already satisfied on main — see <file:line> evidence. Closing unnecessary."

8.5. **Consumer-enumeration pre-flight (type / data-shape refactors only).** If the issue is "type X as dataclass," "convert X dict to typed object," "promote X to TextChoices," or any other refactor that changes the SHAPE of a value, the surface is wider than the type-definition file. Before any code change:

   1. Identify the dict-shape keys or call-site keywords being replaced.
   2. Run `git grep -l '<keyword>' apps/ tests/ scripts/ | wc -l` to count consumer files.
   3. Repeat for each major key/keyword.
   4. Take the union of all touched files.

   **If the union exceeds 5 files, STOP and ask Nathan.** Recommend a 2-PR split: PR1 introduces the new type alongside the legacy shape (additive); PR2 migrates consumers in batches. The dataclass-typing failure pattern is consistent — a "narrower" framing of "just 2 files" reliably balloons to 11+ once consumer call sites are touched.

   (The cap was 8 in the dispatch playbook; tightened to 5 in the in-session model because consumer-rippling refactors still suffer from coherence problems even without the harness ceiling.)

### Work

9. **Implement** the minimum change that satisfies acceptance. No refactoring, no "while I'm here" cleanups, no tangential improvements.

   **Before each Edit/Write tool call, verify your cwd.** Run `pwd` (or check via `git rev-parse --show-toplevel`) — the path MUST start with `$WORKTREE_PATH`. If it does not (e.g., a `cd` failed silently and you're now in `OneDrive/Tech/Python/<repo>/`), STOP. Recover by `cd "$WORKTREE_PATH"` and re-verify; if `cd` won't take, tell Nathan.

   **In-flight breadth recount (type/data-shape refactors only).** After every 5 file edits, run `git diff --name-only origin/<default-branch>... | wc -l` in the worktree. If the count exceeds 10, STOP — the issue's scope was wider than estimated; re-scope per §8.5.

   Commit cadence is normal in-session: stage specific files, commit when a unit of work is coherent. No heartbeat-commit ceremony required (background-subagent harness drop is no longer a concern).

10. **Run the FULL test suite locally** using the repo's exact test command. Isolated runs on touched files are necessary but NOT sufficient — they miss cross-cutting regressions, fixture-state corruption, import-time errors, and side effects that surface only end-to-end.

    1. **Use the project's default test command first** (typically `pytest` with `--reuse-db` configured in `pyproject.toml` for Django projects). Don't pass `--create-db` unless you've already seen cached-state rot in this session.
    2. **Full suite must pass green.** Zero unexpected failures. If failures appear:
        - Verify they reproduce on `origin/<default-branch>` in a SECOND `$TEMP` worktree (per "baseline-comparison snapshot" pattern below). Do NOT classify a failure as "pre-existing" without this check.
        - Verified-pre-existing failures: capture them with specific test IDs, link to the documented flake.
        - New failures: STOP and report. Do NOT merge a PR that introduces failures, even if CI is disabled and auto-merge would let it through.
    3. **Report full-suite results.** "Isolated 50/50 passed" is incomplete.
11. **Run lint locally** using the repo's exact lint command (SCOPED TO THE SAME PATHS CI USES — not the whole repo). Fix anything flagged.
11a. **Code-quality ratchet self-check.** If the repo ships a project-level ratchet (Types-ratchet, Gaudi-ratchet, SMELL-003 ratchet, or equivalent), run it locally against your worktree BEFORE pushing. The canonical invocation for repos with a `gaudi` dependency is `conda run -n Oversteward gaudi ratchet --check`.

    1. **Regression = your problem.** If your changes raise any ratcheted count, refactor BEFORE you push. Long functions you just wrote must be broken up, not noted as a follow-up.
    2. **SMELL-003 target:** extract helpers so no new function exceeds the repo's smell threshold (typically 50 lines).
    3. **If the ratchet is advisory in CI, treat it as blocking locally.**
    4. **If refactoring is genuinely out of scope** (rare), STOP and ask Nathan.
    5. **Update the ratchet baseline** if your PR legitimately reduces the count. Do not update it upward to absorb a regression.

12. **Coherence audit** (size alone never stops the merge; coherence and breadth do).

    1. **File-to-acceptance mapping.** For each changed file, name which acceptance bullet(s) justify it. If any file cannot be traced to a bullet, it is scope creep — revert that file.
    2. **Breadth cap (files).** After reverts, if >10 files remain changed, STOP and ask Nathan. Breadth is where unrelated changes hide.
    3. **Size diagnostic (not a gate).** If `git diff` shows >800 lines changed, note `large_pr: true` and include the file-to-acceptance mapping in the PR body. Do NOT stop.
    4. **Autonomous split (MAY).** If >800 lines AND a clean split is identifiable — sequenced PRs where neither half contains dead code or broken imports — open two (or more) sequenced PRs instead of one.
    5. **Sanity ceiling.** If `git diff` >2000 lines, STOP and ask Nathan.
    6. **Escape hatch.** If the issue body or any scoping comment contains the sentinel `<!-- intentionally-large -->`, skip the 800-line and 2000-line checks. The breadth cap (12.2) still applies.

### Ship

13. **Commit.** Specific files only (`git add <path>` per file). Message format: `<type>: <short description> (#<issue>)` + optional body.
14. **Push.** `git push -u origin <target-branch>`.
15. **Open or update PR.**
    - New: `gh pr create --base <default-branch> --title "..." --body "Closes #<n>\n..."` (use repo PR template).
    - Continuing draft: mark ready + update title/body if needed: `gh pr ready <existing-pr>` + `gh pr edit <existing-pr> --body "..."`.
16. **Enable auto-merge immediately, then verify.** Run `gh pr merge <PR#> --auto --squash --delete-branch --repo <owner>/<repo>`. Then immediately `gh pr view <PR#> --json autoMergeRequest --jq .autoMergeRequest` — if the output is `null`, auto-merge silently dropped; re-run the merge command until it sticks. If auto-merge remains unreachable ("auto-merge not allowed" or similar), tell Nathan and flip to manual-merge fallback: wait for all checks green, then run `gh pr merge <PR#> --squash --delete-branch --repo <owner>/<repo>` (no `--auto`).

### Close the loop

17. **Sleep-and-poll** until terminal state. Wait intervals: 30s, 60s, 90s, 120s, 180s. Cap ~8 minutes total. After each wait: `gh pr view <PR#> --json state,mergeStateStatus,autoMergeRequest,statusCheckRollup`.
    - `state == MERGED` → terminal MERGED
    - Any required check `conclusion == FAILURE` → terminal CI_FAILED
    - `state == OPEN` and `mergeStateStatus == CLEAN` and `autoMergeRequest == null` → auto-merge was dropped mid-flight. Re-enable before the next sleep.
    - Cap reached → terminal STILL_RUNNING (Nathan follows up).
18. **Release the lock.** `gh issue edit <n> --remove-label agent-in-progress --remove-label ready-for-agent --repo <owner>/<repo>`. ALWAYS do this, regardless of terminal state.

### Cleanup (always runs, even on error/stop)

19. **Remove worktree.** `cd` out, then `git worktree remove "$WORKTREE_PATH" --force`. If the worktree held unpushed commits (e.g. STOPPED_FOR_INPUT without draft push), push them as a draft PR FIRST, then remove.

### Final

20. **Report to Nathan.** Concise summary — branch, PR URL, terminal state, files changed, test/lint result, any notes.

## Asking properly (in-flight ambiguity)

In-session, ambiguity dissolves faster than it did in the dispatch model — Nathan is right there. Self-critique gate still applies:

1. **State your plan** in 1-2 sentences.
2. **Find holes.** What could fail? What edge cases? What assumption are you making?
3. **Check Gaudi principles.** Run `conda run -n Oversteward gaudi cheat-sheet`. Does any rule speak to your ambiguity? If yes, apply it.
4. **Decide.** If the revised plan is clear, **execute it.** If not, ask Nathan in chat directly.

For ambiguity that you discover Nathan needs to step away to think about (architectural, hard scoping calls), use the GitHub-comment form for asynchronous capture:

```markdown
@nathankrupa question: <one-line specific question>

**Plan considered:** <your original plan, 1-2 sentences>
**Holes found:** <what you identified, 1-2 sentences>
**Gaudi check:** <rule ids consulted, or "none applicable">
**Revised plan:** <what you'd do now, 1-2 sentences>
```

Then `gh issue edit <n> --remove-label agent-in-progress --add-label needs-input --repo <owner>/<repo>` and stop. Nathan returns via `/answer <repo> <n>` to capture his reply, which flips `needs-input` → `ready-for-agent`. Pickup is conversational: Nathan says "let's resume AG #X" in a fresh window when ready.

## Patterns You Should Know

### The "splitting research" pattern

Some issues present multiple options ("Option 1 / Option 2 / Option 3") without a picked choice. These are NOT ready for work. Stop at step 8 and tell Nathan: "Options unpicked — please choose, then we resume."

### The "baseline drift" pattern

If an issue adds CI/quality gates to a repo that has never had them, the baseline may already be dirty. Step 10/11 will catch this. If lint/security fails on unmodified main: STOP at step 12, file a cleanup issue (or ask Nathan to), don't ship broken gates.

### The "already done" pattern

Some issues linger after the work has been absorbed by another PR. Step 8 catches this. If acceptance is already met, close the issue with evidence rather than opening a no-op PR.

### The "partially done" pattern

Some acceptance items already satisfied, others not. Verify each, note in the PR body which were pre-existing, implement the remainder. Don't pretend the whole issue was your work.

### The "re-pickup after answer" pattern

When Nathan answers a `needs-input` question, he removes the `needs-input` label and resumes the conversation: "let's resume AG #X." Step 1 finds the existing draft PR for that issue. Step 6 checks out its branch in a new worktree. Work resumes on the existing branch rather than creating a fresh one. Step 15 marks the draft ready rather than creating a new PR.

### The "consumer ripple" pattern (formerly "dataclass-typing scope creep")

When the issue says "type X as dataclass" or "convert dict-shape Y to typed object," the type definition lives in 1-2 files but its consumers ripple through ~10. The consistent symptom is that a "narrower" framing of "just 2 files" balloons to 11+ in practice once consumer call sites are touched.

**Detection:** §8.5 consumer-enumeration pre-flight catches this BEFORE work starts.

**Fix:** split the issue into a 2-PR sequence in §8.5 (PR1 additive, PR2 migrate) when consumers >5.

### The "baseline-comparison snapshot" pattern

Some refactors require comparing post-change state against a pristine `origin/<default-branch>` baseline — most often gaudi finding deltas, lint deltas, or test-result deltas. The temptation is to `git stash` Nathan's working tree, `git checkout origin/main -- .`, run the baseline tool, then restore. **This is the forbidden anti-pattern** (see non-negotiable list above).

**The correct pattern: a second temp worktree.**

```bash
# Inside your existing worktree at $WORKTREE_PATH
BASELINE_PATH="${WORKTREE_PATH}.baseline"
git worktree add --detach "$BASELINE_PATH" origin/<default-branch>

# Run the baseline tool against the baseline tree
( cd "$BASELINE_PATH" && .venv/Scripts/gaudi.exe check src/ -f json > /tmp/baseline.json )

# Run the same tool against your worktree (the post-change state)
.venv/Scripts/gaudi.exe check src/ -f json > /tmp/after.json

# Diff and report. Then clean up:
git worktree remove --force "$BASELINE_PATH"
```

The `.baseline` worktree is owned by your work — same lifecycle, removed at step 19 alongside the primary worktree. Nathan's main checkout stays untouched throughout.

**Why this matters (grantspider #538 / PR #539, 2026-04-28):** an agent ran `git stash --keep-index -u` and `git checkout origin/master -- .` in the main checkout to source a baseline. The stash reported "captured nothing." The subsequent `checkout` then wiped two uncommitted markdown files Nathan had authored that session.

## Out-of-band cleanup

### Windows + OneDrive: worktree husk drain

On Windows with repos under OneDrive, `git worktree remove --force` (step 19) reliably succeeds on the filesystem tree (in `$TEMP/`) but fails with `Permission denied` on the admin-metadata half (`<repo>/.git/worktrees/<name>/`) because OneDrive holds file locks during sync. The result is a husk: no live worktree (git worktree list is clean), but an orphan metadata dir accumulates on disk.

The step-4 `git worktree prune` drains any husk whose OneDrive lock has since released — locks are transient (minutes to hours), so deferring the cleanup to the next pickup usually succeeds.

Husks that resist prune across multiple sessions can be cleaned manually when no work is in flight on that repo: `rm -rf <repo>/.git/worktrees/*`. This is safe only when `git worktree list` shows just the main working tree.

### Windows + OneDrive: vanishing temp worktree (post-#426 postmortem)

A related failure mode: the temp checkout at `$TEMP/inwork-<repo>-<n>-<RANDOM>/` is created successfully by `git worktree add` (step 5), but then disappears before or during step 6 — possible causes include antivirus quarantining `.git` internals, OS idle-cleanup sweeping `%TEMP%`, OneDrive syncing an adjacent path and locking contested files, or an unrelated process removing the directory.

**This is the scenario that drove the step-6 viability probe.** The probe catches the failure at the moment of `cd`, before any work happens. But the probe can also trip mid-work if the temp tree is deleted later — the non-negotiable stands for the whole work lifecycle: **if the worktree goes away, STOP. Do not migrate work to the main checkout.**

**Recovery:** run when the system is quiet (close heavy apps, pause OneDrive sync, add `%TEMP%\inwork-*` to antivirus exclusions if this recurs).

## Orphan-branch sweeper

The dispatch model accumulated heartbeat-pushed orphan branches (~80 on aigranthelper, ~30 on wphelper as of 2026-05-01) when the harness false-positive completion bug dropped subagents mid-run. In the in-session model these stop accumulating, but the existing pile needs a one-time triage:

- List branches matching `^(fix|feat|ci|refactor|cleanup|arch|test|chore|docs)/issue-` with no open PR
- For each: if the issue is closed, delete the branch (`git push origin --delete <branch>`)
- If the issue is open with no `agent-in-progress` label, classify as harness-drop and present to Nathan for triage (delete or resume)
- If `agent-in-progress` is set and the branch has recent commits (<30 min), leave alone

This is operator-level cleanup, not part of the issue-to-PR workflow. Run when convenient.

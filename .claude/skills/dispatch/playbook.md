# Dispatch Playbook — Universal Rules (v1.8)

Shared reference for all `<repo>-dev` subagents. Each subagent layers repo-specific context on top of this.

## Identity & Intent

You are an autonomous PR worker. Nathan has pre-approved the work in the issue you are assigned. Your output is a merged PR or a clean stop with a question. You are NOT a code reviewer, a designer, or a refactorer.

One issue → one PR → CI green → auto-merge → done. No side effects on Nathan's live working tree.

## Non-negotiables

- **Never** use `--no-verify`, `--admin`, or any bypass flag
- **Never** force-push to any branch
- **Never** commit files matching `.env*`, `*.pem`, `*.key`, `credentials*`, `secrets*`, `local_settings*`
- **Never** run migrations, drop tables, delete external data, or modify CI config of other repos
- **Never** silently fix unrelated pre-existing failures — report them, don't mask them
- **Never** expand scope beyond the issue's acceptance criteria
- **Never** use `git add -A` or `git add .` — stage specific files only
- **Never** guess when ambiguous — use the intent-capture protocol
- **Never** run any git command that mutates Nathan's live working tree state. The forbidden list is illustrative, not exhaustive: `git checkout` (any form, including `git checkout origin/main -- .`), `git pull`, `git reset`, `git restore`, `git stash` (any variant — `--keep-index`, `-u`, push, pop, drop), `git rebase`, `git merge`, `git clean`, `git rm`. **If you need any git operation that affects working-tree files, the index, or the stash list, do it inside a worktree, not in the main checkout.** The test is: if the operation could surprise a human running `git status` in the main repo right now, it's forbidden.
- **Never** fall back to Nathan's live working tree when the temp worktree fails. If step 5 or step 6 fails, the correct response is STOP (`REFUSED_PREFLIGHT`), not "work in the main checkout instead." Touching the live tree as a fallback leaves uncommitted state, switched branches, and contaminated HEAD — Nathan's open terminals and IDE will see the mess. This has happened (grantspider #426 postmortem, 2026-04-22) — the fix is the step-6 viability probe, and violating it anyway is a fireable offense.
- **Never** reach into the main checkout for a "baseline" or "before" view of files. If you need to compare your changes against pristine master (gaudi delta, lint delta, test delta), create a SECOND temp worktree at `origin/<default-branch>` and run the comparison there. **Do NOT** `git stash` your way to a clean view of the main checkout — even with `--keep-index` and even if you believe the working tree is clean, the operation can capture and then discard untracked uncommitted files (notes, drafts, runbooks, session-state docs). This happened on grantspider #538 (PR #539 postmortem, 2026-04-28): the agent's stash reported "captured nothing" but the subsequent `git checkout origin/master -- .` wiped two uncommitted markdown files Nathan had authored. The correct pattern is in "The 'baseline-comparison snapshot' pattern" below.
- **Never** patch module globals in tests (`monkeypatch.setattr("module.attr", fake)` for `subprocess`, HTTP clients, filesystem, clock, `os.environ`, `random`) when the fix is to expose the dependency as a parameter. See `~/.claude/shared/references/architecture-principles.md` §Dependency Seams. If a test needs a patched global, the code under test has a hidden dependency — fix the signature, not the test.

## Workflow (19 steps, in order)

### Pre-flight

1. **Concurrency check.** Scan repo for open PRs with branch pattern `^(fix|feat|ci|refactor|cleanup)/issue-<n>-`. If a PR matching THIS issue number exists as a draft (STOPPED_FOR_INPUT re-dispatch case), remember its branch name for step 6. If any OTHER agent PR is open on the repo with ANY issue number, STOP — "another agent in flight, refusing to race."
2. **Branch collision recovery.** Compute the target branch name `<type>/issue-<n>-<slug>`. Check if it exists on origin:
   - **Not present** → proceed.
   - **Present, 0 commits ahead of default branch** (orphan from failed attempt) → delete it: `git push origin --delete <branch>`. Note the cleanup in final report. Proceed.
   - **Present, has commits ahead** AND matches the step-1 draft PR → carry over (step 6 will check out this branch).
   - **Present, has commits ahead** AND no matching draft PR → STOP for input. Do not destroy work.
3. **Label `agent-in-progress`** on the target issue: `gh issue edit <n> --add-label agent-in-progress --repo <owner>/<repo>`. Create the label first if it doesn't exist.

### Worktree setup (isolation — keeps Nathan's live working tree untouched)

4. **Fetch (and prune husks).** `cd` into the repo. Run `git worktree prune 2>/dev/null || true` to drain any stale admin-metadata husks left by prior dispatches (see "Windows + OneDrive" note in out-of-band cleanup). Then run `git fetch origin <default-branch>`. Do NOT run `git checkout` or `git pull` on the main working tree — Nathan may be editing there.
5. **Create worktree.** Generate a temp path: `WORKTREE_PATH=$(mktemp -d -t dispatch-<repo>-<n>-XXXX)` (on Windows bash: `WORKTREE_PATH="$TEMP/dispatch-<repo>-<n>-$RANDOM"; mkdir -p "$WORKTREE_PATH"`). Then:
   - **Continuing existing draft PR** (from step 1): `git worktree add "$WORKTREE_PATH" <existing-branch>`
   - **Fresh start:** `git worktree add -B <target-branch> "$WORKTREE_PATH" origin/<default-branch>`
6. **Switch to worktree, then verify viability.** `cd "$WORKTREE_PATH"`. Then run these three checks — all must pass before you proceed:
   - `git rev-parse --is-inside-work-tree` → must print `true`.
   - `git rev-parse --show-toplevel` → must print a path that starts with `$WORKTREE_PATH` (confirms you're in the worktree, not nested inside the main repo via a silent `cd` failure).
   - `ls "$WORKTREE_PATH" | head -3` → must show repo contents (at minimum a `.git` reference and at least one tracked file like `pyproject.toml` or `README`). An empty directory means `git worktree add` registered metadata but the checkout never populated — a known Windows+OneDrive fragility (see Out-of-band cleanup section).

   **If any check fails, STOP.** Emit `final_state: REFUSED_PREFLIGHT` with `notes` describing which check failed, and `question: "worktree viability probe failed at step 6 — Nathan to retry when system is quiet. See Windows+OneDrive section of the playbook."`. Release the `agent-in-progress` label (step 18) and the worktree metadata (step 19). Do NOT attempt to work around the failure by `cd`ing back into the main repo or by running `git checkout` on Nathan's live tree — that is the non-negotiable documented above, driven by the grantspider #426 postmortem.

   ALL subsequent git, test, lint, edit operations happen in `$WORKTREE_PATH`. Nathan's live working tree is never touched.

   **Mid-run vanishing worktree.** If a `git` command later in the workflow fails with "fatal: not a git repository" or similar, the temp tree has disappeared mid-flight. Same rule: STOP, do not migrate work to the main checkout. Emit `final_state: STOPPED_FOR_INPUT` with the failure context; any unpushed commits are lost (that's the cost of the fragility — do not try to rescue them by working in-place).

### Issue scope validation

7. **Read issue.** `gh issue view <n> --repo <owner>/<repo> --comments`. Read body AND latest comments. Comments often override the original body (Option picks, clarifications).
8. **Preflight the issue.** Bail out if:
   - Body contains "Options:" or "Approaches:" with no picked choice in comments
   - No "Acceptance" or checkbox list exists in body or comments
   - Label `needs-scoping` or `reject-close` is present
   - "Already done" case: verify each acceptance item against current code. If all satisfied, STOP and comment: "Acceptance already satisfied on main — see <file:line> evidence. Closing unnecessary."

8.5. **Consumer-enumeration pre-flight (type / data-shape refactors only).** If the issue is "type X as dataclass," "convert X dict to typed object," "promote X to TextChoices," or any other refactor that changes the SHAPE of a value, the surface is wider than the type-definition file. Before any code change:

   1. Identify the dict-shape keys or call-site keywords being replaced.
   2. Run `git grep -l '<keyword>' apps/ tests/ scripts/ | wc -l` to count consumer files.
   3. Repeat for each major key/keyword.
   4. Take the union of all touched files.

   **If the union exceeds 8 files, STOP for input.** Comment: "Consumer count is N files. Per playbook §8.5 / dataclass-typing strategy memory, this must split into a 2-PR sequence: PR1 introduces the new type alongside the legacy shape (additive); PR2 migrates consumers in batches. Awaiting re-scope."

   **Why:** the dataclass-typing failure pattern is consistent — a "narrower" framing of "just 2 files" reliably balloons to 11+ once consumer call sites are touched, exceeds the step-12.2 breadth cap, and triggers harness/API failure modes mid-flight. Three #351-class dispatches died this way before this rule was added (2026-04-28). See memory `feedback_dataclass_typing_dispatch_strategy.md`.

### Work

9. **Implement** the minimum change that satisfies acceptance. No refactoring, no "while I'm here" cleanups, no tangential improvements.

   **Before each Edit/Write tool call, verify your cwd.** Run `pwd` (or check via `git rev-parse --show-toplevel`) — the path MUST start with `$WORKTREE_PATH`. If it does not (e.g., a `cd` failed silently and you're now in `OneDrive/Tech/Python/<repo>/`), STOP. This is the worktree non-negotiable; the step-6 viability probe is your starting line, but cwd drift mid-run is also covered. Recover by `cd "$WORKTREE_PATH"` and re-verify; if `cd` won't take, emit `STOPPED_FOR_INPUT` per §6.

   **In-flight breadth recount (type/data-shape refactors only).** After every 5 file edits, run `git diff --name-only origin/<default-branch>... | wc -l` in the worktree. If the count exceeds 10, STOP — file a comment: "Breadth cap exceeded mid-run (N files). The issue's scope was wider than estimated; re-scope per §8.5." The step-12.2 coherence-audit cap is checked too late for these failures; this in-flight check is the early warning.

   **Heartbeat-commit (mandatory for any dispatch with >5 expected file edits).** The Claude Code harness has a known race condition where it terminates a subagent immediately after delivering a fast tool result, without waiting for the model's next assistant turn (see §"The harness false-positive completion" pattern). When the harness drops you mid-dispatch, any work since the last `git push` is lost. Mitigation: push the branch periodically as a heartbeat.

   1. **First push as soon as one logical unit is staged.** That is, after the first 1-3 files are edited and you've staged them with `git add <path>`, do an initial `git commit -m "WIP: <short summary> (#<n>)"` and `git push -u origin <target-branch>`. Even if no PR is open yet, the branch is on remote.
   2. **Push every 3-5 file edits thereafter.** Run `git diff --cached --shortstat` to check whether new staged work warrants a push. Use `git commit --amend --no-edit && git push --force-with-lease` to keep the WIP commit clean OR `git commit -m "WIP: ..."` for separate commits — your choice; squash-merge collapses both at the end.
   3. **Push before any long-running command.** Specifically: before running the full pytest suite (step 10), before any operation that takes >60s. The risk window is the unprotected gap between your last push and the next; pre-empt it.
   4. **Final commit at step 13** uses the canonical message format and replaces the WIP label. If you used `--amend` strategy, just rename the message at step 13 (`git commit --amend -m "..."`).

   The cost of these extra pushes is trivial (network + remote storage); the cost of a harness drop is rebuilding all unpushed work from scratch. **Always push more often than feels necessary.**
10. **Run tests locally** using the repo's exact test command. Must pass. Pre-existing failures: capture them, DO NOT modify, report in final YAML.
11. **Run lint locally** using the repo's exact lint command (SCOPED TO THE SAME PATHS CI USES — not the whole repo). Fix anything flagged.
11a. **Code-quality ratchet self-check.** If the repo ships a project-level ratchet (Types-ratchet, Gaudi-ratchet, SMELL-003 ratchet, or equivalent), run it locally against your worktree BEFORE pushing. The canonical invocation for repos with a `gaudi` dependency is `conda run -n Oversteward gaudi ratchet --check` (or the repo's documented command). Rules:

    1. **Regression = your problem, not CI's.** If your changes raise any ratcheted count, refactor BEFORE you push. Long functions you just wrote must be broken up *by you*, not noted as a follow-up. The whole point of the ratchet is that it doesn't go up.
    2. **SMELL-003 target:** extract helpers so no new function exceeds the repo's smell threshold (typically 50 lines). Orchestrator functions stay thin; extracted helpers each do one thing. This applies to test fixtures, scripts, and CLI entry points as well as production code.
    3. **If the ratchet is advisory in CI, treat it as blocking locally.** A green CI merge on an advisory ratchet regression is not permission to ship a regression. File the enforcement-gap as a follow-up issue in the dispatcher's inbox if you notice CI isn't enforcing what it should.
    4. **If refactoring is genuinely out of scope** (rare — extracting helpers almost never is), STOP for input. Do not push a regression and hope the ratchet forgives you.
    5. **Update the ratchet baseline** if your PR legitimately reduces the count. Do not update it upward to absorb a regression.

12. **Coherence audit** (size alone never stops the merge; coherence and breadth do).

    1. **File-to-acceptance mapping.** For each changed file, name which acceptance bullet(s) justify it. If any file cannot be traced to a bullet, it is scope creep — revert that file.
    2. **Breadth cap (files).** After reverts, if >10 files remain changed, STOP for input. Breadth is where unrelated changes hide.
    3. **Size diagnostic (not a gate).** If `git diff` shows >800 lines changed, emit `large_pr: true` in the structured report and include the file-to-acceptance mapping in the PR body. Do NOT stop.
    4. **Autonomous split (MAY).** If >800 lines AND a clean split is identifiable — sequenced PRs where neither half contains dead code or broken imports — the agent MAY open two (or more) sequenced PRs instead of one. If no clean split is available, ship as a single PR.
    5. **Sanity ceiling.** If `git diff` >2000 lines, STOP for input. That indicates a scoping bug upstream; re-scope rather than ship.
    6. **Escape hatch.** If the issue body or any scoping comment contains the sentinel `<!-- intentionally-large -->`, skip the 800-line diagnostic AND the 2000-line ceiling entirely. The PR is pre-approved as large. The breadth cap (step 12.2) still applies.

### Ship

13. **Commit.** Specific files only (`git add <path>` per file). Message format: `<type>: <short description> (#<issue>)` + optional body.
14. **Push.** `git push -u origin <target-branch>`.
15. **Open or update PR.**
    - New: `gh pr create --base <default-branch> --title "..." --body "Closes #<n>\n..."` (use repo PR template).
    - Continuing draft: mark ready + update title/body if needed: `gh pr ready <existing-pr>` + `gh pr edit <existing-pr> --body "..."`.
16. **Enable auto-merge immediately, then verify.** Run `gh pr merge <PR#> --auto --squash --delete-branch --repo <owner>/<repo>`. Then immediately `gh pr view <PR#> --json autoMergeRequest --jq .autoMergeRequest` — if the output is `null`, auto-merge silently dropped (can happen on branch-protection edge cases); re-run the merge command until it sticks. Do NOT proceed to step 17 until `autoMergeRequest` is non-null. If auto-merge remains unreachable ("auto-merge not allowed" or similar), report it in the final YAML and flip to manual-merge fallback: wait for all checks green, then run `gh pr merge <PR#> --squash --delete-branch --repo <owner>/<repo>` (no `--auto`).

### Close the loop

17. **Sleep-and-poll** until terminal state. Wait intervals: 30s, 60s, 90s, 120s, 180s. Cap ~8 minutes total. After each wait: `gh pr view <PR#> --json state,mergeStateStatus,autoMergeRequest,statusCheckRollup`.
    - `state == MERGED` → terminal MERGED
    - Any required check `conclusion == FAILURE` → terminal CI_FAILED
    - `state == OPEN` and `mergeStateStatus == CLEAN` and `autoMergeRequest == null` → auto-merge was dropped mid-flight. Re-enable with `gh pr merge <PR#> --auto --squash --delete-branch` (or do the manual-merge fallback per step 16) before the next sleep. Do NOT exit the poll loop with a green, clean, un-merging PR.
    - Cap reached → terminal STILL_RUNNING (dispatcher follows up)
18. **Release the lock.** `gh issue edit <n> --remove-label agent-in-progress --remove-label ready-for-agent --repo <owner>/<repo>`. ALWAYS do this, regardless of terminal state (including CI_FAILED / STILL_RUNNING / STOPPED_FOR_INPUT). `ready-for-agent` is dispatch-eligibility state; once the agent has picked up the issue, that state is consumed. The `/answer` flow re-adds `ready-for-agent` when the issue is ready for re-dispatch.

### Cleanup (always runs, even on error/stop)

19. **Remove worktree.** `cd` out, then `git worktree remove "$WORKTREE_PATH" --force`. If the worktree held unpushed commits (e.g. STOPPED_FOR_INPUT without draft push), push them as a draft PR FIRST, then remove.

### Final

20. **Emit structured report** (see format below).

## Intent-Capture Protocol (when ambiguity hits mid-work)

When the issue is unclear — not obvious from code, not in the issue body, not in comments:

### Self-critique gate (MANDATORY before asking)

Nathan's time is expensive. Most "I need to ask" moments dissolve under a moment's thought. Before filing a question:

1. **State your plan.** Write out, in 1-2 sentences, what you would do if you had to proceed right now.
2. **Find holes.** What could fail? What edge cases? What assumption are you making? What depends on an unknown?
3. **Check Gaudi principles.** Run `conda run -n Oversteward gaudi cheat-sheet`. Does any rule speak to your ambiguity? If yes, apply it and skip asking.
4. **Propose improvements.** Incorporate your findings into a revised plan.
5. **Decide.** If the revised plan is clear, **execute it** — do not ask. If not, the question is worth Nathan's time.
6. **Ask properly** (only if steps 1-5 didn't resolve it — see below).

### Asking properly

When the self-critique gate confirms a real blocker:

1. **Post a structured question comment on the issue.** GitHub is the single source of truth — no external inbox file. Use this exact body:

```markdown
@nathankrupa question: <one-line specific question>

**Plan considered:** <your original plan, 1-2 sentences>
**Holes found:** <what you identified, 1-2 sentences>
**Gaudi check:** <rule ids consulted, or "none applicable">
**Revised plan:** <what you'd do now, 1-2 sentences>
```

   `gh issue comment <n> --repo <owner>/<repo> --body "$(cat <<'EOF'
   ...body above...
   EOF
   )"`

2. `gh issue edit <n> --remove-label agent-in-progress --add-label needs-input --repo <owner>/<repo>`
3. If any commits exist in the worktree: push as a **draft** PR so context isn't lost. `gh pr create --draft --base <default-branch> --title "[WIP] <issue title> (#<n>)" --body "Waiting on input — see issue comments."`
4. Remove the worktree (step 19).
5. Emit final report with `final_state: STOPPED_FOR_INPUT` and the question text.
6. Exit. Do not guess.

**Note on the answer loop:** Nathan sees pending questions via `/questions` or `/project-status` (stale counter). He runs `/answer <repo> <n>`, which posts his reply as an issue comment and flips `needs-input` → `ready-for-agent`. You will be re-dispatched with the answer in the issue thread.

## Structured Final Report

Emit a fenced YAML block as your final output:

```yaml
pr_url: https://github.com/... | null
branch: <branch-name> | null
final_state: MERGED | CI_FAILED | STILL_RUNNING | STOPPED_FOR_INPUT | REFUSED_PREFLIGHT
issue_number: <n>
files_changed: [path/to/file, ...]
lines_changed: +N / -M
tests: "X/Y passed" | "failed: <summary>"
lint: clean | "N findings fixed" | failing
large_pr: true | false
duration_seconds: <int>
worktree_cleaned: true | false
continued_existing_branch: true | false
orphan_branch_deleted: "<name>" | null
question: "<text>" | null
notes: "anything unexpected"
```

## Failure Cleanup (always release resources)

In ALL failure paths — tests failed, scope exceeded, CI failed, STOPPED_FOR_INPUT, unexpected error:

- **Always** remove `agent-in-progress` AND `ready-for-agent` labels (step 18)
- **Always** remove the worktree (step 19)
- **Always** emit the structured report

The agent does not leave orphaned state on Nathan's machine OR on GitHub.

## Patterns You Should Know

### The "splitting research" pattern

Some issues present multiple options ("Option 1 / Option 2 / Option 3") without a picked choice. These are NOT agent-ready. Stop at step 8 and comment: "Options unpicked — please choose, then re-dispatch."

### The "baseline drift" pattern

If an issue adds CI/quality gates to a repo that has never had them, the baseline may already be dirty. Step 10/11 will catch this. If lint/security fails on unmodified main: STOP at step 12, file a cleanup issue (or ask dispatcher to), don't ship broken gates.

### The "already done" pattern

Some issues linger after the work has been absorbed by another PR. Step 8 catches this. If acceptance is already met, close the issue with evidence rather than opening a no-op PR.

### The "partially done" pattern

Some acceptance items already satisfied, others not. Verify each, note in the PR body which were pre-existing, implement the remainder. Don't pretend the whole issue was your work.

### The "re-dispatch after answer" pattern

When Nathan answers a `needs-input` question, he removes the `needs-input` label and re-dispatches. Step 1 finds the existing draft PR for that issue. Step 6 checks out its branch in a new worktree. Work resumes on the existing branch rather than creating a fresh one. Step 15 marks the draft ready rather than creating a new PR.

### The "baseline-comparison snapshot" pattern (added v1.9)

Some refactors require comparing post-change state against a pristine `origin/<default-branch>` baseline — most often gaudi finding deltas, lint deltas, or test-result deltas. The temptation is to `git stash` Nathan's working tree, `git checkout origin/main -- .`, run the baseline tool, then restore. **This is the forbidden anti-pattern** (see non-negotiable list above).

**The correct pattern: a second temp worktree.**

```bash
# Inside your existing dispatch worktree at $WORKTREE_PATH
BASELINE_PATH="${WORKTREE_PATH}.baseline"
git worktree add --detach "$BASELINE_PATH" origin/<default-branch>

# Run the baseline tool against the baseline tree
( cd "$BASELINE_PATH" && .venv/Scripts/gaudi.exe check src/ -f json > /tmp/baseline.json )

# Run the same tool against your worktree (the post-change state)
.venv/Scripts/gaudi.exe check src/ -f json > /tmp/after.json

# Diff and report. Then clean up:
git worktree remove --force "$BASELINE_PATH"
```

The `.baseline` worktree is owned by your dispatch — same lifecycle, removed at step 19 alongside the primary worktree. Nathan's main checkout stays untouched throughout.

**Why this matters (grantspider #538 / PR #539, 2026-04-28):** an agent ran `git stash --keep-index -u` and `git checkout origin/master -- .` in the main checkout to source a baseline. The stash reported "captured nothing" — which the agent interpreted as harmless. The subsequent `checkout` then wiped two uncommitted markdown files Nathan had authored that session (a runbook draft and an updated SESSION_STATE.md). The agent self-reported the procedural violation; Nathan recovered the files from a separate context. The recovery was lucky. The new rule above + this pattern are the real fix.

### The "harness false-positive completion" pattern (added v1.8)

**Symptom:** the harness sends a `task-notification` with `status: completed` but no YAML report was emitted by the agent. The transcript ends with the last assistant turn at `stop_reason: tool_use` (the agent made a tool call) followed by a `user` turn (tool result delivered) and nothing after — the model never got to take its next turn.

**Diagnosed cause (2026-04-28):** the Claude Code harness terminates a subagent immediately after delivering a tool result, without waiting for the next assistant turn. Reproduces consistently when the tool call completes very fast (~40 ms tool_use → tool_result gap). Successful dispatches show ~9s between tool_use and tool_result, then ~35s before the next assistant turn (the final report). Failed dispatches show the same setup but the next turn never arrives.

This is a **harness bug** (Claude Code), not the model and not the agent. Reported to Anthropic with JSONL transcript evidence. Until upstream-fixed, mitigate via:

1. **Heartbeat-commit (step 9)** — push the branch periodically so partial work is preserved.
2. **Dispatcher-side verification (SKILL.md "Post-dispatch")** — when a "completed" notification arrives, the dispatcher verifies the YAML report was actually emitted AND a PR/branch exists at the expected state. If either is missing, treat as `HARNESS_DROPPED` (a false-positive completion) and re-dispatch from the heartbeat-pushed branch.

Four `aigranthelper-dev` dispatches dropped this way on 2026-04-28 (#327 broad, #351 v1+v2, #306). All exhibited the smoking-gun JSONL pattern. Other subagent types (general-purpose, etc.) appear unaffected — no observed instances. The bug correlates with long architectural-typing dispatches reaching ~135+ turns and ~128k cache_read.

**For a re-dispatched issue that was previously dropped:** step 1 finds the existing branch on remote (heartbeat-committed). Step 6 checks it out in a new worktree. Work resumes from the last heartbeat. The new dispatch can pick up where the dropped one left off without re-doing prior work.

### The "dataclass-typing scope creep" pattern (added v1.7)

When the issue says "type X as dataclass" or "convert dict-shape Y to typed object," the type definition lives in 1-2 files but its consumers ripple through ~10. Three #351 / #327 dispatches died at 11-file breadth before this pattern was named (2026-04-28).

**Symptom:** agent's narrower-than-original framing ("just 2 files") still touches 11+ in practice; harness or API silently terminates mid-Edit/Write at high turn count and high cache_read.

**Detection:** §8.5 consumer-enumeration pre-flight catches this BEFORE work starts.

**Fix:** split the issue into a 2-PR sequence in §8.5 (PR1 additive, PR2 migrate) when consumers >8.

**Reliability note:** even with proper splitting, harness/API reliability degrades as cache_read approaches ~128k and turn count approaches ~135. Long architectural-typing dispatches sit close to that ceiling. If a dispatch dies silently after a successful tool_use turn (no error message, harness reports "completed"), the work is lost and re-dispatching the same scope will likely fail the same way. Re-scope smaller before retrying. See memory `feedback_dataclass_typing_dispatch_strategy.md` for full diagnosis.

## Out-of-band cleanup (operator-level, not agent-level)

If an agent crashes mid-run (rate limit, harness error, network), the `agent-in-progress` label may remain orphaned. A separate **sweeper** agent (scheduled, not per-dispatch) reconciles:

- Find issues labeled `agent-in-progress`
- For each: check if any open PR references the issue AND has recent commits (<30min)
- If no such PR → label is stale → remove it + comment on the issue noting the sweep
- Sweeper is NOT part of the dispatch skill. It's a separate scheduled task (v2).

### Windows + OneDrive: worktree husk drain

On Windows with repos under OneDrive, `git worktree remove --force` (step 19) reliably succeeds on the filesystem tree (in `$TEMP/`) but fails with `Permission denied` on the admin-metadata half (`<repo>/.git/worktrees/<name>/`) because OneDrive holds file locks during sync. The result is a husk: no live worktree (git worktree list is clean), but an orphan metadata dir accumulates on disk.

The step-4 `git worktree prune` drains any husk whose OneDrive lock has since released — locks are transient (minutes to hours), so deferring the cleanup to the next dispatch usually succeeds where the in-run cleanup could not.

Husks that resist prune across multiple dispatches can be cleaned manually when no dispatch is in flight on that repo: `rm -rf <repo>/.git/worktrees/*`. This is safe only when `git worktree list` shows just the main working tree.

### Windows + OneDrive: vanishing temp worktree (post-#426 postmortem)

A related failure mode: the temp checkout at `$TEMP/dispatch-<repo>-<n>-<RANDOM>/` is created successfully by `git worktree add` (step 5), but then disappears before or during step 6 — possible causes include antivirus quarantining `.git` internals, OS idle-cleanup sweeping `%TEMP%`, OneDrive syncing an adjacent path and locking contested files, or an unrelated process removing the directory. The agent's cwd is left stale; subsequent `git` commands fail with "fatal: not a git repository" or the `cd` silently lands outside any git tree.

**This is the scenario that drove the step-6 viability probe.** The probe catches the failure at the moment of `cd`, before any work happens. But the probe can also trip mid-work if the temp tree is deleted later — so the non-negotiable stands for the whole dispatch lifecycle: **if the worktree goes away, STOP. Do not migrate work to the main checkout.**

**Recovery (Nathan-side)**: run dispatches when the system is quiet (close heavy apps, pause OneDrive sync, add `%TEMP%\dispatch-*` to antivirus exclusions if this recurs). Re-dispatch once the environment is clean. The issue may also be mitigated long-term by moving the dispatch temp root out of `%TEMP%` to a dedicated non-indexed path (e.g. `C:\dispatch-tmp\`) — a future playbook revision, out of scope here.

**Postmortem reference**: grantspider #426 merged with the feature branch pushed from Nathan's main OneDrive checkout rather than an isolated temp worktree. The metadata dir `dispatch-grantspider-426-19214/` was orphaned (gitdir pointed at a non-existent Temp path) but the agent pushed and merged anyway, leaving the main checkout on the feature branch with a clean tree. No work was lost; the non-negotiable violation was the working-in-place fallback. The fix is in step 6 (viability probe) and the non-negotiable section.

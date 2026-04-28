---
name: dispatch
description: "Dispatch a scoped background agent to work a GitHub issue autonomously (implement → test → PR → auto-merge). Use when the user says \"dispatch issue N on REPO\" or \"work issue N on REPO\" where REPO is any repo marked `dispatch_target` in registry.yaml (currently aigranthelper, grantspider, wphelper, ai-assistants)."
---

# /dispatch — autonomous agent PR worker

Dispatches a repo-scoped background agent (`<repo>-dev` subagent) to work a single GitHub issue end-to-end. Agent implements, tests, lints, opens PR, enables auto-merge, polls to terminal state, reports back structured YAML.

## Invocation

```
/dispatch <repo> <issue-number>
```

Where `<repo>` is the `id` of any context in `registry.yaml` marked `dispatch_target: true`. Get the current list with:

```bash
conda run -n Oversteward python scripts/registry.py dispatch-targets
```

Example:
```
/dispatch grantspider 150
/dispatch aigranthelper 123
/dispatch wphelper 37
/dispatch ai-assistants 61
```

## What this skill does (in order)

### 1. Repo routing

Look up the dispatch target metadata from the registry:

```bash
conda run -n Oversteward python scripts/registry.py info <repo>
```

The helper returns:
- `id` — the repo id
- `subagent` — the subagent type to invoke (`{id}-dev` convention)
- `repo` — git remote URL
- `branch` — default branch
- `owner` — GitHub owner (`NathanKrupa`)
- `full_name` — `<owner>/<id>` for `gh --repo` calls

Unknown repo arg (helper exits non-zero) → abort with "Unknown repo" refusal.

### 2. Preflight (before firing the agent)

Run these checks. Any failure → refuse to dispatch, report the reason to the user.

**Repo kill-switch (check first — whole-repo abort):**
- `gh issue list --repo <owner>/<repo> --label dispatch-paused --state open --limit 1 --json number,title,url`
- If any result: refuse. The repo is paused. Remove the `dispatch-paused` label from the referenced issue(s) to resume.

**Issue readiness:**
- `gh issue view <n> --repo <owner>/<repo> --json state,labels,body,comments`
- Issue must be `state: OPEN`
- Label `reject-close` → refuse
- Label `needs-scoping` → refuse
- Label `agent-in-progress` → refuse (concurrency guard)
- Label `needs-input` → refuse (has an open question)
- Body (or latest comment) must contain either `## Acceptance` or a checkbox list `- [ ]`
- Body must not contain unpicked multi-option blocks (e.g. `Options:` followed by numbered list with no comment resolving the choice)

**Concurrency:**
- `gh pr list --repo <owner>/<repo> --state open --json headRefName --jq '.[].headRefName' | grep -E '^(fix|feat|ci|refactor|cleanup)/issue-'`
- If any match, there's an open agent PR → refuse ("another dispatch in flight on this repo")

**Branch collision:**
- Compute likely branch name: `<type>/issue-<n>-<slug>`
- `git ls-remote https://github.com/<owner>/<repo>.git refs/heads/<branch>`
- If exists → refuse ("branch exists, prior failed attempt — clean up first")

If all preflights pass: proceed.

### 3. Fire the agent

Invoke Task tool with:
- `subagent_type: <repo>-dev`
- `run_in_background: true`
- `prompt`: structured brief including:
  - Issue number + `gh` commands to read body/comments
  - Reference to `.claude/skills/dispatch/playbook.md` (universal workflow)
  - Explicit reminder of repo's default branch
  - Expected structured YAML return format

### 4. Return to user

Immediately return:
```
Dispatched <repo>-dev on issue #<n>.
Agent ID: <id>
Status will notify on completion.
```

Do not block the conversation. The notification comes asynchronously.

## Refusal messages (what to tell the user on preflight failure)

- **Unknown repo:** "Unknown repo `<arg>`. Run `conda run -n Oversteward python scripts/registry.py dispatch-targets` to see current dispatch targets."
- **Repo paused:** "Repo `<repo>` is paused — issue #<paused-issue> has `dispatch-paused`. Remove that label to resume dispatching."
- **Issue closed:** "Issue #<n> is closed. Nothing to dispatch."
- **Label reject-close:** "Issue #<n> is labeled reject-close. Reopen-and-relabel or pick a different issue."
- **Label needs-scoping:** "Issue #<n> needs scoping first. Either scope it (pick option, add acceptance criteria) and remove the label, or pick a different issue."
- **Label agent-in-progress:** "Issue #<n> already has an agent working on it. Wait or investigate."
- **Label needs-input:** "Issue #<n> is waiting on your input. Run `/answer <repo> <n>` or read the issue comments on GitHub."
- **No acceptance criteria:** "Issue #<n> has no acceptance criteria. Agent won't know when it's done. Add `## Acceptance` with checkboxes first."
- **Unpicked options:** "Issue #<n> presents options but none is picked in comments. Choose one (1/2/3) and comment on the issue, then re-dispatch."
- **Open agent PR on repo:** "Repo has an open agent PR (#<pr>). One-per-repo rule — wait for it to merge or close."
- **Branch exists:** "Branch `<name>` already exists — prior attempt not cleaned up. Delete the branch or pick a new issue."

## Post-dispatch

When the harness sends a `task-notification` with `status: completed`, **do not trust it blindly** — verify before relaying. The Claude Code harness has a known race condition (see playbook §"The harness false-positive completion" pattern) where it can terminate a subagent immediately after delivering a tool result without waiting for the model's next turn. The notification arrives as `completed` but the agent never finished.

### Dispatcher verification (mandatory on every completion notification)

Before relaying any final_state, run these checks:

1. **YAML report present?** The agent's terminal output should contain a fenced YAML block with `final_state: <X>` and the rest of the structured fields (per playbook §"Structured Final Report"). If the result text is mid-narrative ("Now add regression tests:" / "Let me create the file:" / similar), the agent did NOT finish — this is the false-positive completion bug.

2. **Branch state matches claimed final_state?** Run:
   ```bash
   git ls-remote https://github.com/<owner>/<repo>.git "refs/heads/<expected-branch>" 2>&1
   gh issue view <n> --repo <owner>/<repo> --json labels --jq '.labels[].name'
   gh pr list --repo <owner>/<repo> --state open --search "head:<expected-branch>" --json number,state --jq '.[]'
   ```

   - `final_state: MERGED` → expect remote branch deleted, PR shows MERGED state
   - `final_state: STILL_RUNNING` → expect remote branch present, open PR
   - `final_state: STOPPED_FOR_INPUT` → expect `needs-input` label set; possibly draft PR
   - `final_state: REFUSED_PREFLIGHT` → expect labels cleared, no remote branch
   - **No YAML report at all** → false-positive completion. Verify branch state directly.

3. **If verification fails (YAML missing OR branch state inconsistent with claimed final_state):**
   - Treat as a special case: `HARNESS_DROPPED`.
   - Clear the `agent-in-progress` label: `gh issue edit <n> --remove-label agent-in-progress`.
   - **Check the heartbeat-pushed branch:** if a branch exists on remote at the expected name with WIP commits, the agent's partial work survives. A re-dispatch (step 1 of playbook) will find it as an existing draft PR or just an existing branch, and step 6 will check it out in a new worktree to resume.
   - If no branch on remote, the agent died before its first heartbeat-push — work is lost.
   - Report to user as: "⚠️ Harness dropped agent on #<n> — false-positive completion. <Heartbeat branch found / no branch pushed>. Re-dispatch?"

### Final-state messages (after verification passes)

- `final_state: MERGED` → "✅ PR merged: <url>"
- `final_state: CI_FAILED` → "❌ CI failed on <url> — check the Actions tab"
- `final_state: STILL_RUNNING` → "⏱ PR open, CI pending: <url>. Will merge when green."
- `final_state: STOPPED_FOR_INPUT` → "❓ Agent stopped with a question on issue #<n>. See comments."
- `final_state: REFUSED_PREFLIGHT` → "🚫 Agent refused: <reason>"
- `HARNESS_DROPPED` (verification-derived) → "⚠️ Harness dropped agent on #<n>. <Heartbeat status>. Re-dispatch?"

## Limitations (v1)

- One-shot per call. No drain mode. Use `/drain <repo>` (v2) for queue consumption.
- No cost/token logging.
- No cross-repo dependency awareness.
- Synchronous preflight checks can be slow (~3-5s) — acceptable for now.

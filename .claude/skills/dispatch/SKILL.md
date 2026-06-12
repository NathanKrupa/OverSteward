---
name: dispatch
description: "Work a GitHub issue with a scoped repo agent in-session, foreground (implement → test → PR → auto-merge). Runs on the Max subscription, not metered API. Use when the user says \"dispatch issue N on REPO\" or \"work issue N on REPO\" where REPO is any repo marked `dispatch_target` in registry.yaml (currently aigranthelper, grantspider, wphelper, ai-assistants, fiscus, exchequer)."
---

# /dispatch — in-session scoped agent PR worker

Runs a repo-scoped agent (`<repo>-dev`) on a single GitHub issue end-to-end: implement, test, lint, open PR, enable auto-merge, poll to terminal state, return a structured YAML report. The agent works in an isolated worktree so Nathan's live tree is never touched.

## Billing & reliability — why this runs foreground (read once)

This skill **invokes the agent in-session, foreground — never `run_in_background: true`.** Two reasons:

- **Cost.** In-session subagents (the `Agent`/Task tool and the `Workflow` tool) bill against the **Max subscription quota**, not the metered Anthropic API. Background/detached "Managed Agents" are API-metered ($/token + $/session-hour) and are off-limits on a subscription budget. Foreground keeps the work inside the envelope Nathan already pays for.
- **Reliability.** The Claude Code silent-termination bug ([anthropics/claude-code#47936](https://github.com/anthropics/claude-code/issues/47936)) drops `run_in_background: true` subagents mid-task in ~15–30% of runs and falsely reports them `completed`. It is specific to background-async mode. Foreground subagents return their real final output, so there is no false-completion to detect and no heartbeat-commit insurance to maintain.

The cost is that the session stays alive while the agent works — you watch it finish rather than closing the laptop. That is the trade we accept to stay on Max.

## Invocation

```
/dispatch <repo> <issue-number>
```

Where `<repo>` is the `id` of any context in `registry.yaml` marked `dispatch_target: true`. Get the current list with:

```bash
uv run python scripts/registry.py dispatch-targets
```

Example:
```
/dispatch grantspider 150
/dispatch aigranthelper 123
/dispatch wphelper 37
/dispatch ai-assistants 61
/dispatch fiscus 7
```

## What this skill does (in order)

### 1. Repo routing

Look up the dispatch target metadata from the registry:

```bash
uv run python scripts/registry.py info <repo>
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

### 3. Run the agent (foreground)

Invoke the `Agent` tool with:
- `subagent_type: <repo>-dev`
- **No `run_in_background`** (foreground — see billing/reliability note above)
- `prompt`: structured brief including:
  - Issue number + `gh` commands to read body/comments
  - Reference to `.claude/skills/dispatch/playbook.md` (universal workflow)
  - Explicit reminder of the repo's default branch
  - Expected structured YAML return format

The session blocks until the agent returns. The agent's final message **is** its structured YAML report — that is the real result, no notification round-trip.

### 4. Return to user

When the agent returns, read its YAML report and relay the terminal state directly (no verification round-trip is needed — foreground returns the genuine final output):

- `final_state: MERGED` → "✅ PR merged: <url>"
- `final_state: CI_FAILED` → "❌ CI failed on <url> — check the Actions tab"
- `final_state: STILL_RUNNING` → "⏱ PR open, CI pending: <url>. Will merge when green — re-poll with `gh pr view`."
- `final_state: STOPPED_FOR_INPUT` → "❓ Agent stopped with a question on issue #<n>. See comments. Answer with `/answer <repo> <n>`."
- `final_state: REFUSED_PREFLIGHT` → "🚫 Agent refused: <reason>"

If the agent returns prose with no YAML block (rare in foreground), treat it as incomplete: check branch/PR/label state directly with `gh` and report what you find, rather than trusting a bare "done."

## Refusal messages (what to tell the user on preflight failure)

- **Unknown repo:** "Unknown repo `<arg>`. Run `uv run python scripts/registry.py dispatch-targets` to see current dispatch targets."
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

## Batch mode — a few issues at once (via Workflow)

When Nathan wants several issues worked in one go, do NOT fire several background tasks. Author a small **`Workflow`** that fans out one `<repo>-dev` agent per issue, foreground, in parallel — all on the Max subscription, journaled and resumable.

**Two hard constraints:**

1. **One issue per repo per batch.** The playbook's step-1 concurrency rule refuses to race a second agent PR on the same repo. So a batch targets *distinct* repos (e.g. GS #150 + AG #123 + WP #37), or sequences same-repo issues one after another. Do not put two grantspider issues in the same parallel batch.
2. **Keep batches small (2–4).** Each agent maintains its own context window, so N agents burn Max quota ~N× faster. A runaway fan-out can torch a 5-hour window in one sitting. Small, deliberate batches over autopilot drains — Nathan is on a fixed envelope.

Run each issue through its full preflight (§2) before adding it to the batch; a Workflow stage that fails preflight drops that issue and continues with the rest. Each agent follows the same playbook (its own worktree isolation, its own structured report). Relay a compact per-issue summary table when the batch returns.

## Limitations

- **Foreground only.** No "fire and walk away" — the session stays alive while the agent runs. This is deliberate (Max billing + #47936 reliability).
- **Cost is real, not free.** It is subscription quota, not an API invoice, but parallel batches consume that quota fast. Watch `/usage`.
- **No cross-repo dependency awareness.** If issue B depends on issue A's PR merging first, sequence them by hand.
- Synchronous preflight checks take ~3–5s — acceptable.
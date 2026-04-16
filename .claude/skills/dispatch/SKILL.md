---
name: dispatch
description: Dispatch a scoped background agent to work a GitHub issue autonomously (implement → test → PR → auto-merge). Use when the user says "dispatch issue N on REPO" or "work issue N on REPO" where REPO is aigranthelper, grantspider, wphelper, or ai-assistants.
---

# /dispatch — autonomous agent PR worker

Dispatches a repo-scoped background agent (`<repo>-dev` subagent) to work a single GitHub issue end-to-end. Agent implements, tests, lints, opens PR, enables auto-merge, polls to terminal state, reports back structured YAML.

## Invocation

```
/dispatch <repo> <issue-number>
```

Where `<repo>` is one of: `aigranthelper`, `grantspider`, `wphelper`, `ai-assistants`.

Example:
```
/dispatch grantspider 150
/dispatch aigranthelper 123
/dispatch wphelper 37
/dispatch ai-assistants 61
```

## What this skill does (in order)

### 1. Repo routing

Map `<repo>` → subagent type + GitHub remote:

| Arg | Subagent | GitHub remote | Default branch |
|---|---|---|---|
| `aigranthelper` | `aigranthelper-dev` | `NathanKrupa/aigranthelper` | `main` |
| `grantspider` | `grantspider-dev` | `NathanKrupa/grantspider` | `master` |
| `wphelper` | `wphelper-dev` | `NathanKrupa/wphelper` | `main` |
| `ai-assistants` | `ai-assistants-dev` | `NathanKrupa/ai-assistants` | `main` |

Unknown repo arg → abort with error.

### 2. Preflight (before firing the agent)

Run these checks. Any failure → refuse to dispatch, report the reason to the user.

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

- **Unknown repo:** "Unknown repo `<arg>`. Use: aigranthelper, grantspider, wphelper, or ai-assistants."
- **Issue closed:** "Issue #<n> is closed. Nothing to dispatch."
- **Label reject-close:** "Issue #<n> is labeled reject-close. Reopen-and-relabel or pick a different issue."
- **Label needs-scoping:** "Issue #<n> needs scoping first. Either scope it (pick option, add acceptance criteria) and remove the label, or pick a different issue."
- **Label agent-in-progress:** "Issue #<n> already has an agent working on it. Wait or investigate."
- **Label needs-input:** "Issue #<n> is waiting on your input. Check Chestertron Inbox or the issue comments."
- **No acceptance criteria:** "Issue #<n> has no acceptance criteria. Agent won't know when it's done. Add `## Acceptance` with checkboxes first."
- **Unpicked options:** "Issue #<n> presents options but none is picked in comments. Choose one (1/2/3) and comment on the issue, then re-dispatch."
- **Open agent PR on repo:** "Repo has an open agent PR (#<pr>). One-per-repo rule — wait for it to merge or close."
- **Branch exists:** "Branch `<name>` already exists — prior attempt not cleaned up. Delete the branch or pick a new issue."

## Post-dispatch

The agent's completion notification will include a structured YAML report. Read it and relay:
- `final_state: MERGED` → "✅ PR merged: <url>"
- `final_state: CI_FAILED` → "❌ CI failed on <url> — check the Actions tab"
- `final_state: STILL_RUNNING` → "⏱ PR open, CI pending: <url>. Will merge when green."
- `final_state: STOPPED_FOR_INPUT` → "❓ Agent stopped with a question on issue #<n>. See comments."
- `final_state: REFUSED_PREFLIGHT` → "🚫 Agent refused: <reason>"

## Limitations (v1)

- One-shot per call. No drain mode. Use `/drain <repo>` (v2) for queue consumption.
- No cost/token logging.
- No cross-repo dependency awareness.
- Synchronous preflight checks can be slow (~3-5s) — acceptable for now.

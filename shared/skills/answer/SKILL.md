---
name: answer
description: "Answer a single agent-blocked GitHub issue. Takes `<repo> <issue-number>`, shows the agent's pending question, captures Nathan's answer, posts it as a `gh issue comment`, and swaps `needs-input` → `ready-for-agent` so the issue becomes eligible for re-dispatch. Use when the user says \"answer AG 148\", \"answer grantspider 170\", \"respond to wp 45\", or runs /answer."
---

# /answer — post one answer, unblock one agent

Replaces the Chestertron Inbox round-trip (`/morning-digest` → Obsidian → `/answer-flow`) with a direct GH-native answer loop. Nathan picks one waiting issue, writes the answer in the terminal, and it lands on GitHub immediately.

## Invocation

```
/answer <repo> <issue-number>
```

- `<repo>` — id of any context in `registry.yaml` marked `dispatch_target: true`. Shorthand accepted (`AG`, `GS`, `WP` → `aigranthelper`, `grantspider`, `wphelper`; `ai-assistants` stays as-is).
- `<issue-number>` — integer.

Examples:
```
/answer AG 148
/answer grantspider 170
/answer wphelper 45
/answer ai-assistants 61
```

## What the skill does

### 1. Resolve the repo

- Expand shorthand if needed (`AG`/`GS`/`WP`/`AIA`).
- Validate against `conda run -n Oversteward python scripts/registry.py dispatch-targets`.
- Unknown id → refuse: "Unknown repo `<arg>`. Run `conda run -n Oversteward python scripts/registry.py dispatch-targets` for the current list."

### 2. Fetch the pending question

```bash
gh issue view <n> --repo NathanKrupa/<repo> \
  --json number,title,url,state,labels,body,comments
```

- Issue must be `state: OPEN` and carry the `needs-input` label. If not, refuse:
  - Closed → "Issue #<n> is closed. Nothing to answer."
  - Missing `needs-input` → "Issue #<n> is not labeled needs-input. Either no question is pending, or an answer already landed."
- Pull the most recent comment whose body matches `@nathankrupa question:` (case-insensitive). That is the live question.
- If no such comment exists, fall back to the issue body (agent may have phrased the question there). If neither exists, refuse: "Issue #<n> has `needs-input` but no `@nathankrupa question:` comment and no body text. Investigate manually before answering."

### 3. Show Nathan the question

Print:

```
<repo>#<n> — <title>
<url>

Question (from @<author>, <age>):
<question-body, truncated to ~400 chars if needed>
```

Then ask Nathan for the answer. One prompt, free-form reply. Allow multi-line (accept until a blank line followed by `.` on its own, or just take the whole next user message — whichever the conversation tool gives us).

If Nathan types `skip` / `cancel` / empty → abort without side effects.

### 4. Post the comment

```bash
gh issue comment <n> --repo NathanKrupa/<repo> --body "$(cat <<'EOF'
[answering @nathankrupa question]:

<nathan-answer>
EOF
)"
```

Use a heredoc so line breaks and quotes in Nathan's answer survive.

### 5. Swap labels

```bash
gh issue edit <n> --repo NathanKrupa/<repo> \
  --remove-label needs-input \
  --add-label ready-for-agent
```

If `ready-for-agent` doesn't exist on the repo, fall back to `--remove-label needs-input` only and warn in the report.

### 6. Report

```
Answered <repo>#<n>.
  Comment: <gh-api-returned-url>
  Labels: needs-input → ready-for-agent
  Next: /dispatch <repo> <n> to re-dispatch the agent.
```

## Rules

- **One issue per call.** Batching is `/questions` territory; `/answer` is deliberately surgical.
- **Read-then-write.** Always fetch current state before posting — labels may have changed since `/questions` was last run.
- **No Inbox file touched, ever.** The Chestertron Inbox is deprecated; this skill replaces the round-trip entirely.
- **Do not spawn agents.** Re-dispatch is a separate `/dispatch` call Nathan initiates.

## Related

- `/questions` — list every `needs-input` issue across dispatch repos. Good companion: run `/questions`, pick one, run `/answer <repo> <n>`.
- `/dispatch <repo> <n>` — fire the agent again once answered.
- `/project-status` — dashboard shows stale-question counts (>48h) alongside ready/needs-scoping queues.

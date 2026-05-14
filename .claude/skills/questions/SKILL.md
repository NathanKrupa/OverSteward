---
name: questions
description: "List agent-blocked issues (labeled `needs-input`) across every repo marked `dispatch_target` in registry.yaml (currently aigranthelper, grantspider, wphelper, ai-assistants, fiscus). Use when the user asks \"what's waiting on me\", \"any questions\", \"check inbox\", or runs /questions. Returns compact list with age, URL, and latest question excerpt; flags items >48h old."
---

# /questions — agent inbox aggregator

Lists issues labeled `needs-input` across every dispatch-target repo. These are items where a dispatched agent hit ambiguity, filed a `@nathankrupa question:` comment, and paused. This skill gives an ad-hoc mid-session view of what's blocking progress.

## Invocation

```
/questions
```

No arguments.

## What this skill does

### 1. Scan all dispatch-target repos in parallel

The repo list comes from the registry — no hardcoded loop. Run from the OverSteward project root:

```bash
for r in $(conda run -n Oversteward python scripts/registry.py dispatch-targets 2>/dev/null); do
  gh issue list --repo NathanKrupa/$r --label needs-input \
    --state open --json number,title,url,updatedAt,createdAt \
    --limit 50 | jq -c --arg repo "$r" '.[] | . + {repo: $repo}'
done
```

### 2. For each issue, fetch the most recent `question:` comment

For each returned issue:

```bash
gh issue view <number> --repo NathanKrupa/<repo> \
  --json comments --jq '.comments | map(select(.body | test("question:"; "i"))) | last'
```

Extract the body and truncate to ~200 chars for display.

### 3. Compute age

Age = now − `updatedAt` (or `createdAt` if no recent update). In whole hours if <48h, else days.

Items with age > 48h get a ⏰ prefix (blocking marker).

### 4. Render compact output

```
Questions waiting on Nathan:

⏰ [aigranthelper#148] Stripe webhook signature test (3d old)
    https://github.com/NathanKrupa/aigranthelper/issues/148
    Q: Should the test mock the webhook secret or read from env? Current...

   [grantspider#170] Parser for new CA source (8h old)
    https://github.com/NathanKrupa/grantspider/issues/170
    Q: The source returns JSON wrapped in <pre> tags — should I strip HTML...

Total: 2 waiting (1 blocking ⏰)
```

Empty state:

```
✅ No questions waiting. All agents unblocked.
```

### 5. No side effects

This skill is read-only. It does not post comments, remove labels, or modify issues.

## Rules

- **Parallel scans OK** — 4 repos × 1 `gh` call each is <3s total
- **If a repo returns 404 / auth error**, show inline: `[repo] (error: <short>)` and continue with the others
- **Do not invoke `/dispatch` or spawn agents** from this skill — reporting only
- **Question excerpt**: if no comment matches `question:` pattern, fall back to the issue title only (label might have been applied manually)

## Related

- `/dispatch` — the skill that produces these blocked items when agents file `needs-input` questions
- `/answer <repo> <n>` — post one answer and swap `needs-input` -> `ready-for-agent`
- `/project-status` — dashboard surfaces stale `needs-input` counts (>=48h) alongside the rest of the pipeline

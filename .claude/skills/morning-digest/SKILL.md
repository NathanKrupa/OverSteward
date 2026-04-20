---
name: morning-digest
description: "Reconcile GitHub `needs-input` issues against the Chestertron Inbox across every repo marked `dispatch_target` in registry.yaml. Dispatched agents append their own questions live (primary path); this skill catches any `needs-input` issue whose question hasn't made it to the inbox and appends it. Invoked daily via `/schedule` (7am) or ad-hoc via `/morning-digest`."
---

# /morning-digest — inbox reconciler

Primary flow: dispatched dev agents append their questions directly to the Chestertron Inbox as they hit blockers (see dispatch playbook's Intent-Capture Protocol). This skill is the **safety net** — it scans every dispatch-target repo for `needs-input` issues and appends any that don't yet have a corresponding entry in the inbox.

## Canonical paths

- **Chestertron Inbox:** `C:\Users\natha\OneDrive\Documents\Nathan Writing\Obsidian\GTD\Projects\The Almoner Business\Research\Chestertron Inbox.md`
- **Repos scanned:** every context in `registry.yaml` marked `dispatch_target` (currently aigranthelper, grantspider, wphelper, ai-assistants). Source via `conda run -n Oversteward python scripts/registry.py dispatch-targets`.

## Intended invocation

- Primary: scheduled remote agent via `/schedule`, daily at 7am local.
- Secondary: ad-hoc `/morning-digest`.

## What this skill does

### 1. Scan all dispatch-target repos

Run from the OverSteward project root. The repo list comes from the registry — no hardcoded loop:

```bash
for r in $(conda run -n Oversteward python scripts/registry.py dispatch-targets 2>/dev/null); do
  gh issue list --repo NathanKrupa/$r --label needs-input \
    --state open --json number,title,url,updatedAt,createdAt \
    --limit 50 | jq -c --arg repo "$r" '.[] | . + {repo: $repo}'
done
```

### 2. Read the Chestertron Inbox

Extract every `**Link:**` URL currently in the inbox. Build a set.

### 3. Determine gaps

An issue is a gap if its URL is in the scan result but NOT in the inbox link set. These are `needs-input` issues whose agents never filed the corresponding inbox block (crash, skipped protocol, etc.).

### 4. For each gap, fetch the agent's `question:` comment

```bash
gh issue view <n> --repo NathanKrupa/<repo> --json comments \
  --jq '.comments | map(select(.body | test("@nathankrupa question:"; "i"))) | last'
```

Extract the comment body after `question:`.

### 5. Append a reconciler block per gap

Use the standard dispatch format so `/answer-flow` can parse it uniformly:

```markdown
### <repo> #<N> — <title>  [reconciled <YYYY-MM-DD HH:MM>]
**Plan considered:** *(not captured by agent — reconciled from GitHub)*
**Holes found:** *(not captured)*
**Gaudi check:** *(not captured)*
**Revised plan:** *(not captured)*
**Question:** <excerpt from @nathankrupa question: comment>
**Link:** <issue URL>

---
```

The `[reconciled ...]` marker tells Nathan this entry came via the safety net, not a live agent append.

### 6. Append only — never rewrite

- **Append** at the end of the file.
- **Never touch** frontmatter, navigation, explainer paragraph, or existing content.
- **Update** frontmatter `date modified` → today's date in `dddd, MMMM Do YYYY`.

### 7. Empty state

If there are no gaps (every `needs-input` issue is already in the inbox, OR no `needs-input` issues exist), do nothing. Skill exits silently. Do NOT append a "no questions" marker.

### 8. No GitHub side effects

Read-only against GitHub. No comments, labels, or issue edits.

## Scheduling

```
/schedule create --name morning-digest --cron "0 7 * * *" --skill morning-digest
```

## Acceptance

- [ ] Triggers daily at 7am local
- [ ] Appends only the gaps (issues with `needs-input` label not already in inbox)
- [ ] Reconciled entries use standard dispatch format so `/answer-flow` parses them
- [ ] Never rewrites or reorders existing inbox content
- [ ] Preserves frontmatter (only `date modified` may change)

## Rules

- **Append-only.** Never delete or reorder existing blocks.
- **Per-repo error tolerance.** If a repo returns 404 / auth error, note it in a reconciler comment (e.g. `### ERROR — <repo> unreachable`) and continue.
- **Do not spawn agents.**
- **Do not touch Obsidian frontmatter fields other than `date modified`.**

## Related

- **Dispatch playbook** → Intent-Capture Protocol with self-critique gate. Agents append directly.
- `/answer-flow` → hourly + on-demand, posts answers back to GitHub.
- `/questions` → ad-hoc read-only view.

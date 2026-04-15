---
name: morning-digest
description: Scan aigranthelper, grantspider, wphelper, and ai-assistants for `needs-input` issues and append a morning digest to `data/obsidian/Chestertron Inbox.md` so Nathan can answer agent questions during his morning review. Invoked on a cron schedule (7am local) via `/schedule`, or ad-hoc via `/morning-digest`.
---

# /morning-digest — agent question digest

Runs the agent-question digest that feeds Nathan's morning review. Scans the four orchestration repos for issues labeled `needs-input` (filed by dispatched agents via the intent-capture protocol), compiles a digest block, appends it to `data/obsidian/Chestertron Inbox.md` above the last "empty" marker line, and preserves the inbox frontmatter + navigation links.

## Intended invocation

Primary: scheduled remote agent via `/schedule`, daily at 7am local.
Secondary: ad-hoc invocation `/morning-digest` during any session.

## What this skill does

### 1. Scan four repos

```bash
for r in aigranthelper grantspider wphelper ai-assistants; do
  gh issue list --repo NathanKrupa/$r --label needs-input \
    --state open --json number,title,url,updatedAt,createdAt \
    --limit 50 | jq -c --arg repo "$r" '.[] | . + {repo: $repo}'
done
```

### 2. For each issue, fetch the most recent `question:` comment

```bash
gh issue view <n> --repo NathanKrupa/<repo> \
  --json comments \
  --jq '.comments | map(select(.body | test("@nathankrupa question:"; "i"))) | last'
```

Extract the comment body starting at `question:` and truncate to ~300 chars.

### 3. Compute age and blocking status

Age = `now - updatedAt` (fall back to `createdAt`). Items >48h old are `⏰ blocking`; otherwise `active`.

### 4. Build the digest block

Today's date in the format `dddd, MMMM Do YYYY` (project convention per CLAUDE.md).

```markdown
## Morning agent digest — <date>

### <repo> #<n> — <title> (<age>d old)
**Question:** <excerpt>
**Link:** <issue URL>
**Status:** <active | ⏰ blocking (>48h)>

### <repo> #<n> — <title> (<age>h old)
**Question:** <excerpt>
**Link:** <issue URL>
**Status:** active

---
```

Empty state (no `needs-input` issues anywhere):

```markdown
## Morning agent digest — <date>

✅ No agent questions waiting.

---
```

### 5. Append to Chestertron Inbox

Read `data/obsidian/Chestertron Inbox.md`. Find the line beginning with `*(Inbox empty` — if present, replace it with the new digest block. Otherwise append the digest block at the end of the file.

**Preserve untouched:**
- Frontmatter (`---` block at top, including `date created`, `tags`, etc.)
- Navigation line (`[[Dashboard]] - [[In Box]] - [[Topic Dashboard]]`)
- Existing inbox content (prior unprocessed Nathan notes)

**Do update:**
- `date modified` in frontmatter → today's date in the project format

### 6. No GitHub side effects

This skill is read-only against GitHub. It does not post comments, remove labels, or modify issues.

## Scheduling

To install the 7am cron trigger, run once:

```
/schedule create --name morning-digest --cron "0 7 * * *" --skill morning-digest
```

To verify:

```
/schedule list
```

To remove:

```
/schedule delete morning-digest
```

## Acceptance

- [ ] Triggers daily at 7am local
- [ ] Writes digest block preserving Chestertron Inbox frontmatter + navigation links
- [ ] Per-item entries include issue link, title, question excerpt, age, blocking flag
- [ ] `⏰ blocking` on items >48h old
- [ ] Writes empty-state `✅ No agent questions waiting.` when all clear

## Related

- `/dispatch` — produces `needs-input` items via intent-capture (agents pause and label when ambiguous)
- `/questions` — read-only ad-hoc view of the same data (no file writes)
- ai-assistants #43 — answer-flow handler (posts Nathan's inbox answers back to GitHub — separate issue)

## Rules

- **Idempotent on same day.** If today's digest block already exists, replace it rather than appending a duplicate
- **If a repo returns 404 / auth error**, include a `[repo] (error: <short>)` line and continue with the others
- **Do not spawn agents** from this skill — reporting-to-inbox only
- **Do not touch Obsidian frontmatter fields other than `date modified`**

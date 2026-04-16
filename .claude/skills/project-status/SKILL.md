---
name: project-status
description: Show a per-project status table of open issues, open PRs, items completed since the last check-in, and any agents currently working across aigranthelper, grantspider, wphelper, and ai-assistants. Use when Nathan asks for "project status", "pipeline status", "what's in flight", or runs /project-status.
---

# /project-status — pipeline dashboard

One-table view of the four orchestration repos: what's open, what's landed since the last time this skill was run.

## Invocation

```
/project-status
```

No arguments.

## Repos scanned

- `NathanKrupa/aigranthelper`
- `NathanKrupa/grantspider`
- `NathanKrupa/wphelper`
- `NathanKrupa/ai-assistants`

## State file

Persist the last-run timestamp at:

```
c:/Users/natha/OneDrive/Tech/Python/Oversteward/.claude/skills/project-status/state.json
```

Shape:

```json
{ "last_checked": "2026-04-15T10:00:00Z" }
```

- **First run** (file missing or unparseable): treat `last_checked` as 24h ago and note "first run — baseline is last 24h" in the report.
- **End of run**: overwrite `state.json` with the current UTC timestamp (ISO-8601, `Z` suffix). Do this only if the GitHub scans succeeded for at least one repo.

## What this skill does

### 1. Read prior timestamp

Read `state.json`. If missing/invalid, fall back to 24h ago. Keep both the prior timestamp (for the query) and a flag for "is this a first run".

### 2. Scan each repo

For each repo, run four `gh` queries. Parallelize across repos by running the per-repo block in the background and waiting; per-repo the four calls can be sequential (fast enough).

```bash
TS="<prior-timestamp-ISO8601>"

for r in aigranthelper grantspider wphelper ai-assistants; do
  open_issues=$(gh issue list --repo NathanKrupa/$r --state open --limit 200 --json number --jq 'length')
  open_prs=$(gh pr list --repo NathanKrupa/$r --state open --limit 200 --json number --jq 'length')
  closed_issues=$(gh issue list --repo NathanKrupa/$r --state closed --search "closed:>=$TS" --limit 200 --json number --jq 'length')
  merged_prs=$(gh pr list --repo NathanKrupa/$r --state merged --search "merged:>=$TS" --limit 200 --json number --jq 'length')
  echo "$r $open_issues $open_prs $closed_issues $merged_prs"
done
```

Note: `gh issue list` excludes PRs by default, so no double-counting.

### 3. Render the table

Markdown table, one row per project, plus a totals row. Include the "since" timestamp in the header so Nathan sees the window.

```
Project pipeline status — since 2026-04-14 10:00 UTC

| Project         | Open issues | Open PRs | Issues closed | PRs merged |
|-----------------|-------------|----------|---------------|------------|
| aigranthelper   | 12          | 2        | 3             | 4          |
| grantspider     | 8           | 1        | 1             | 2          |
| wphelper        | 5           | 1        | 0             | 1          |
| ai-assistants   | 14          | 0        | 2             | 0          |
| **Total**       | **39**      | **4**    | **6**         | **7**      |
```

If first run, prefix with: `(first run — "since" window is last 24h; future runs will measure from this moment)`.

### 4. Detect in-flight agents

After the table, list any agents currently working. Two signals, unioned per issue:

1. **Label signal:** issues labeled `agent-in-progress` (set by dev agents at dispatch, cleared on exit).
2. **Branch signal:** open PRs whose head branch matches `^(fix|feat|ci|refactor|cleanup)/issue-(\d+)-` — extract the issue number from the branch.

```bash
for r in aigranthelper grantspider wphelper ai-assistants; do
  # Label signal
  gh issue list --repo NathanKrupa/$r --state open --label agent-in-progress --limit 50 \
    --json number,title,url --jq '.[] | "\(.number)|\(.title)|\(.url)|label|-"'
  # Branch signal
  gh pr list --repo NathanKrupa/$r --state open --limit 50 \
    --json number,headRefName,title,url \
    --jq '.[] | select(.headRefName | test("^(fix|feat|ci|refactor|cleanup)/issue-\\d+-")) | "\(.headRefName | capture("issue-(?<n>\\d+)").n)|\(.title)|\(.url)|branch|\(.number)"'
done
```

Union by `(repo, issue_number)`. Render only when there's ≥1 hit:

```
In-flight agents (2):

| Repo          | Issue | PR   | Signal       | Title
|---------------|-------|------|--------------|----------------------------
| aigranthelper | #169  | —    | label only   | SEC: checkout.session.completed…
| grantspider   | #190  | #193 | label+branch | Replace naive datetime.now()…
```

- `Signal` column: `label only` (no PR pushed yet), `branch only` (label was cleared but PR still open — possible stale), `label+branch` (healthy in-flight).
- If zero in-flight agents, print: `No agents currently in flight.`

### 5. Update state

After rendering, write the current UTC timestamp to `state.json`:

```json
{ "last_checked": "<now-ISO8601-Z>" }
```

## Rules

- **Read-only against GitHub.** No comments, labels, or edits.
- **Per-repo error tolerance.** If a repo's scan fails (404 / auth), show `error` in that row's cells and continue with the others. Do NOT update `state.json` if ALL repos failed.
- **Do not spawn agents.**
- **Timestamp format:** ISO-8601 with `Z` suffix. `gh ... --search "closed:>=2026-04-14T10:00:00Z"` is the exact literal.
- **Limits:** `--limit 200` is a safety cap; if any count hits 200, append a `+` (e.g., `200+`) and note "cap hit" below the table so Nathan knows to raise the limit.

## Related

- `/questions` — which of the open issues are blocked on Nathan
- `/morning-digest` — daily reconciler for `needs-input` issues
- `/answer-flow` — post Nathan's answers back to GitHub

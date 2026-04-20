---
name: project-status
description: "Show a per-project status table of open issues, open PRs, items completed since the last check-in, and any agents currently working across every repo marked `dispatch_target` in registry.yaml (currently aigranthelper, grantspider, wphelper, ai-assistants). Surfaces oldest unscoped issues when the ready queue is thin. Use when Nathan asks for \"project status\", \"pipeline status\", \"what's in flight\", or runs /project-status."
---

# /project-status -- pipeline dashboard

One-table view of the four orchestration repos: what's open, what's landed since the last run, which agents are in flight, and (when the ready queue is thin) the oldest unscoped issue per repo so Nathan can scope it.

All work is done by `scripts/project_status.py` -- a single `conda run` invocation replaces the 16-plus serial `gh` calls the previous version of this skill orchestrated from Claude. The skill's only jobs now are: run the script, present the output, and walk Nathan through any surfaced scoping candidates.

## Invocation

```
/project-status
```

No arguments.

## What the skill does

### 1. Run the dashboard script

```bash
conda run -n Oversteward python scripts/project_status.py
```

- Runs from the Oversteward repo root.
- Finishes in ~2-3s (four repos fetched in parallel).
- Reads/writes state at `.claude/skills/project-status/state.json` (ephemeral, gitignored).
- Exits non-zero only when every repo's `gh` call failed.

The script prints markdown to stdout. Print that output verbatim to Nathan.

### 2. Walk Nathan through any "Next to scope" block

If the script printed a `Next to scope (...)` section, for each surfaced candidate:

1. Fetch the issue body so you can understand what's being asked:
   ```bash
   gh issue view <n> --repo NathanKrupa/<repo> --json title,body,labels,comments
   ```
2. Summarize the ask in one or two sentences.
3. Ask Nathan the *specific* decision question(s) that would block dispatch. Typical blockers:
   - Multiple options presented with none picked
   - Missing acceptance criteria
   - Unclear scope / "how big should this be"
4. When Nathan answers, post his decision as an issue comment, add `## Acceptance` (or a checkbox list) if missing, remove `needs-scoping` (if present), and add `ready-for-agent`.
5. Move to the next candidate.

If Nathan is busy or declines to scope one, leave the issue alone -- the script will surface it again next run.

### 3. No other side effects

The script itself is read-only against GitHub. The only write is `state.json` locally.

## Reading the output

- **Ready queue** column: count of open issues labeled `ready-for-agent` per repo. This is the dispatch runway.
- **Needs scoping** column: count of open issues labeled `needs-scoping`. These have been triaged as "needs Nathan's input before it can be dispatched".
- **PAUSED** section (only if any): lists repos where `/dispatch` is refusing new work because at least one open issue has the `dispatch-paused` label. Remove the label on the referenced issue to resume.
- **In-flight agents** section: union of (a) open issues labeled `agent-in-progress` and (b) open PRs whose branch matches `^(fix|feat|ci|refactor|cleanup)/issue-<n>-`. `label only` = no PR pushed yet; `branch only` = possibly stale (label cleared but PR still open); `label+branch` = healthy.
- **Next to scope** block: only appears when a repo's ready queue is below threshold (`SCOPING_SURFACE_THRESHOLD = 2`). Priority 1 is oldest `needs-scoping`-labeled issue; fallback is oldest open issue that carries none of {`ready-for-agent`, `agent-in-progress`, `agent-done`, `reject-close`, `needs-input`, `wontfix`, `duplicate`, `invalid`, `backlog`}.
- **Pipeline metrics (last 30d)** section: aggregate health over a rolling 30-day window.
  - *PR turnaround*: median + max hours from PR open to PR merge. Proxy for agent-side cycle time; full issue-creation → merge cycle-time (excluding needs-input stalls) is a follow-up.
  - *Merge rate*: merged PRs / (merged + closed-unmerged) in the window. Abandoned PRs drag this below 100%.
  - *Needs-input age*: median + max hours that currently-open `needs-input` issues have been waiting (uses `updatedAt` as a proxy for label-applied-at).

## Snapshot log

Each run appends one JSON line per non-errored repo to `data/pipeline_history.jsonl` (gitignored; per-machine). Fields: `ts`, `since`, `repo`, `open_issues`, `open_prs`, `ready_queue`, `needs_scoping`, `needs_input`, `in_flight`, `closed_since_last`, `merged_since_last`. Intended as raw material for trend analysis; no automatic reading today.

## Tuning knobs

All constants live at the top of `scripts/project_status.py`:

| Constant | Purpose |
|----------|---------|
| `REPOS` | Sourced from `registry.yaml` via `scripts/registry.py` (every context with `dispatch_target: true`); `DISPLAY_ORDER` controls column order |
| `SCOPING_SURFACE_THRESHOLD` | Below this `ready-for-agent` count, surface a scoping candidate |
| `GH_LIMIT` | Per-query page cap (200) |
| `METRIC_WINDOW_DAYS` | Rolling window (days) for pipeline metrics (default 30) |
| `UNSCOPED_EXCLUDES` | Labels that disqualify an issue from the scoping fallback |

Edit the script directly; no re-config needed.

## Related

- `/dispatch <repo> <n>` -- fire an agent on a scoped issue
- `/questions` -- which open issues are blocked on Nathan
- `/morning-digest` -- daily reconciler for `needs-input` issues
- `/answer-flow` -- post Nathan's answers back to GitHub

---
name: kaizen
description: "Surface and fix this session's one recurring process defect — the session-start pass. Shows the next item from the kaizen queue (recurring-lesson clusters Fiscus surfaces, plus `kaizen`-labelled issues), ranked by measured recurrence and drained by durable verdicts. Invoke at the START of every session, when Nathan says \"kaizen\" / \"/kaizen\", or when asked what process defect to fix next."
---

# /kaizen — fix one recurring defect, then get on with the day

The estate had been re-encountering its own defects rather than fixing them:
nine error classes recurring across **9-11 distinct PRs each** as of the
2026-08-08 analysis, every one of them already written down in a trajectory note
that nothing read. This pass makes the first act of every session a fix to how we
work.

Run from the **OverSteward** working tree:

```bash
export PYTHONPATH="$PWD/src"
KAIZEN="python scripts/dream.py kaizen"
```

## Step 1 — build the report and the issue snapshot

```bash
mkdir -p /tmp/kaizen
fiscus review trajectories --all-active --since 60d --min-cluster 3 --format json \
  > /tmp/kaizen/patterns.json
gh issue list --repo NathanKrupa/OverSteward --state open --label kaizen \
  --json number,title,labels > /tmp/kaizen/issues.json
```

## Step 2 — take the next item

```bash
$KAIZEN next --report /tmp/kaizen/patterns.json --issues /tmp/kaizen/issues.json
```

**Exit codes carry meaning — do not collapse them.**

- **0** — a measured result. One item, or an honest "nothing queued".
- **2** — the detector is broken, *not* a clean backlog. Stop and surface it.
  An empty queue reported as good news is the exact failure this pass exists to
  correct (Fiscus #101, which answered "no patterns detected" over 425 notes).

## Step 3 — fix it, then get on with the day

**One item per session. Not a gate.**

- If Nathan opened the session with an explicit task, **his task goes first.**
  Surface the item, do his work, then take the item. An urgent production fix
  must never wait behind a doctrine promotion — the 2026-08-06 *"I told you to
  promote two hours ago"* correction is the standing evidence, and reproducing
  it in the name of process improvement would be its own irony.
- If the session opens with no assigned work, take the item immediately.
- A `promotion` item means: write the lesson into the surface that changes
  behaviour — `shared/references/`, a CLAUDE.md, an agent card, or memory. A
  trajectory note is where lessons are *captured*; it is not where they act.
- An `issue` item is worked normally: scope, branch, PR.

Doctrine and memory changes flow through a worktree PR like everything else
(OS#90 — never commit to the primary checkout's master).

## Step 4 — record the verdict, or the queue never drains

```bash
$KAIZEN resolve --key <key-from-step-2> --verdict promoted --note "→ CLAUDE.md § Verification"
```

| verdict | meaning | stays in queue? |
|---|---|---|
| `promoted` | landed in a behaviour-changing surface | no |
| `declined` | judged not worth promoting, with a reason | no |
| `deferred` | worth doing, not today | **yes** |

`deferred` is deliberately non-terminal. Without it, "not today" silently becomes
"never" — which is precisely the decay this queue was built to stop.

**Recording the verdict is not optional bookkeeping.** The queue ranks by
recurrence, so an unrecorded item is the head of the list again next session, and
the backlog never drains. This is the defect that made the monthly promotion pass
(OS#325) insufficient on its own.

## Reporting

One or two lines: which item was taken, what surface it landed in, and how many
remain queued. On exit 2, report the breakage loudly instead — a broken detector
is a finding, not a quiet morning.

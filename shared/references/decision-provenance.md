ABOUTME: How OverSteward records a durable decision and how a dispatch/scoping agent must respect one already made.
ABOUTME: Adapted from gstack (garrytan/gstack), MIT-licensed — the supersede/don't-re-litigate shape, reshaped onto OverSteward's cross-machine substrate.

# Decision Provenance

A durable decision is a settled call: an architecture choice, a scope boundary, a
tool/vendor pick, a branch-model rule — the kind of thing that should not be
re-argued from scratch every session. gstack keeps these in an append-only
`decisions.jsonl` with a computed "active" set and a `--supersede` reversal event,
and every skill's Context-Recovery block reads them under one rule: *treat active
decisions as prior settled calls — do not silently re-litigate them; if you're
about to reverse one, say so explicitly and why.*

OverSteward steals that **shape**, not that **store**. gstack's ledger lives in a
single-machine `~/.gstack`; OverSteward is cross-machine by design — its durable
memory is the auto-loaded memory index (`~/.claude/projects/.../memory/`) plus
GitHub issues, both of which already sync everywhere the estate runs. Adding a
parallel per-machine jsonl would fracture that. So the convention below leans on
the substrate that is already cross-machine.

This is the companion to `decision-brief.md` (how to *present* a decision that
needs surfacing) and `auto-decide.md` (*whether* to surface a fork at all). This
one is the third leg: how to **record** a decision once it's made, and how to
**respect** one that was already made.

## What counts as a durable decision

Record — and respect — only *durable* decisions. NOT turn-level or trivial ones.

- **Durable:** architecture (layer boundaries, seam shape), scope boundaries
  (what an epic will and won't do), tool/vendor picks (Typesense vs pgvector,
  local GPU vs metered API), branch-model rules (dev→staging→main), a settled
  Nathan-law, or an explicit reversal of any of the above.
- **Not durable:** a variable name, a one-off refactor path, which file to touch
  first, formatting — anything a competent engineer would decide the same way and
  could undo without consequence. These never get a provenance record.

## Where a decision lives (pick the lighter substrate)

**Default: memory frontmatter.** OverSteward memory files already carry YAML
frontmatter and are auto-loaded every session. A durable decision that belongs to
memory gains three optional fields:

```yaml
---
name: project_ag_branch_model_divergence
description: AG adopted dev→staging→main 2026-06-30; registry routes AG dispatch to staging
metadata:
  node_type: memory
  type: project
decided_at: 2026-06-30
supersedes: null              # id/name of the memory this decision reverses, or null
superseded_by: null           # set when a later decision reverses THIS one
---
```

- `decided_at` — the date the call was settled (ISO `YYYY-MM-DD`).
- `supersedes` — the `name` of the memory whose decision this one reverses (or
  `null`). Present only on the reversing record.
- `superseded_by` — set on the OLD record when it is reversed, pointing at the new
  one. The pair forms a two-way link, so reading either end reveals the reversal.
  A record with a non-null `superseded_by` is no longer the active call — it is
  history, kept for the "why did we change our mind" trail (the append-only spirit
  of gstack's event log: nothing is deleted, reversals are additive).

**Alternative: a `decision`-labeled GitHub issue.** For an estate-wide call that
isn't naturally one repo's memory — a cross-repo policy, a decision that needs a
discussion thread — open (or label) an issue with the `decision` label. Reversal =
a new `decision` issue that says "Supersedes #<n>" in its first line and links
back; the superseded issue gets a closing comment pointing forward and, if it's
still open, the `superseded` label. The issue bus is already cross-machine and
carries its own discussion + timestamps for free.

**Rule of thumb:** if the decision is a fact a future session needs auto-loaded,
put it in memory frontmatter. If it needs a thread or spans repos, use a
`decision` issue. Do not record it in both — one home per decision.

## The rule (record + respect)

1. **Respect settled calls.** When a durable decision is in front of you — in an
   auto-loaded memory, in a `decision` issue, or stated in an issue's scope — treat
   it as a *prior settled call with its rationale*. Do not silently re-open it,
   re-argue it, or quietly implement the opposite. This is the direct fix for the
   AG branch-model re-litigation churn (`project_ag_branch_model_divergence`),
   where the same dev→staging→main call kept getting re-decided session to session.

2. **Announce reversals — supersede + why.** If your work would *reverse* a
   durable decision, that is never silent. Say so explicitly: name the decision
   you're overturning, state *why* the new evidence or constraint justifies it,
   and record the reversal via the supersede link (memory `supersedes` /
   `superseded_by`, or a `decision` issue that cites `Supersedes #<n>`). A reversal
   without an announced rationale is a bug, not a decision.

3. **When unsure whether something is settled, check before you build.** A quick
   grep of memory (`grep -ril "<topic>"` in the memory dir) or
   `gh issue list --label decision` is cheaper than re-litigating — and far
   cheaper than shipping a silent reversal Nathan has to catch in review.

---

Adapted from gstack (garrytan/gstack), MIT. The durable-decision + `--supersede` +
"do not silently re-litigate; announce reversals" discipline is gstack's; the
memory-frontmatter / `decision`-issue substrate is OverSteward-native (cross-machine
by design, where gstack's `~/.gstack` ledger is single-machine).

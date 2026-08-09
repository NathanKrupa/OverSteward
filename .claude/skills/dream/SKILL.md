---
name: dream
description: "Run one complete dream cycle — sleep-time memory consolidation over unprocessed session transcripts (docs/memory only, never code). Invoke when the assigned-work queue is empty and Nathan signals end-of-day (sign-off), when a Stop-hook reminder says transcripts are queued, when the cron backstop runs `claude -p`, or when Nathan says \"run the dream cycle\" / \"/dream\". Converges all three triggers on one procedure built on the engine in src/oversteward/dream/."
---

# /dream — the convergent dream cycle

One procedure, three triggers (design `documentation/designs/sleep-time-consolidation.md` §4, §11; OverSteward #114):

- **Sign-off (primary).** Nathan signals he is heading off. Finish every assigned work item first, then run this cycle once.
- **Stop-hook reminder.** `.claude/hooks/dream_stop_reminder.py` enqueued the ending session; this drains the queue.
- **Cron backstop.** `claude -p "run the dream cycle"` (see `shared/scripts/dream/`) runs this same procedure headless over any transcripts no sign-off drained.

All three call the **same** deterministic helpers (`scripts/dream.py cycle …`, backed by `src/oversteward/dream/`). This skill is **orchestration only**: it runs those steps and does the two LLM steps — extraction and judging — **in-session on the Max subscription** (never a metered API). It writes **docs/memory only, never code**.

Run from the **OverSteward** working tree, with the package importable:

```bash
export PYTHONPATH="$PWD/src"
DREAM="python scripts/dream.py cycle"       # use the project venv's python
ROADMAP="python scripts/dream.py roadmap"   # step 5 — a top-level command, not a cycle action
PROMOTION="python scripts/dream.py promotion"  # step 6 — likewise top-level
```

The store is the private `steward-memory` repo; the ledger is OverSteward's `data/dream/`. The `cycle` subcommands default to the live paths — pass `--store` / `--ledger` / `--store-repo` only when testing.

## Step 1 — enumerate unprocessed (no-op fast path)

```bash
$DREAM unprocessed > /tmp/dream/unprocessed.json
```

Each entry is a transcript whose content hash is **not** in the processed ledger. **If the list is empty, stop here** — report "ledger current, nothing to consolidate" and exit clean. This is what makes the cron backstop a safe no-op when a sign-off already drained the queue.

## Step 2 — per transcript: read → extract (in-session) → gate

For each entry, render the transcript and extract candidate facts yourself, in-session:

```bash
python scripts/dream.py transcripts show <session_id> > /tmp/dream/transcript.txt
```

Read it and produce a JSON list of candidate facts following `oversteward.dream.extract.EXTRACTION_PROMPT` (the schema and the strict "when in doubt, omit" rules live there). Each candidate MAY carry the optional two-axis fields `tier` (`standing`|`model`|`cookbook`), `scope` (list), and `digest` (one-line) — leave them out unless confident; a strict deterministic classifier derives `tier` for the always-loaded standing-orders layer when you omit it (and never promotes to a `standing` law on keyword presence). Write that raw JSON to `/tmp/dream/extract_<i>.json`. Then gate + privacy-filter + prefilter it deterministically:

```bash
$DREAM worksheet --extract /tmp/dream/extract_<i>.json > /tmp/dream/worksheet_<i>.json
```

The worksheet drops noise and **hard-blocks secrets** (§7/§8) and attaches, per surviving candidate, the top-K Jaccard-nearest existing memories to judge against.

## Step 3 — judge (in-session) → apply

For each worksheet candidate, judge it against its `prefiltered` memories yourself, in-session, per the §6 bands and the provenance guard:

- score `similarity` (0–1) vs the nearest existing memory;
- name the matched memory's `filename` (or null if nothing is close);
- propose `merged_body` for an auto-merge; set `is_contradiction` when the candidate contradicts the match (a contradiction vs a `nathan-stated` memory is **surfaced, never auto-written**);
- confirm or set the candidate's two-axis `tier`/`scope`/`digest` for a NEW fact (append band) — only set `tier: standing` for a durable law/habit that belongs in every session's lean loaded layer, never for an ordinary ops lesson just because it says never/always/must. Leave `tier` blank to let the strict classifier derive it. `MEMORY.md` is now the grouped **Standing Orders** layer (Laws / Habits / Graveyard / Living-doc pointers); the full flat index lives on-demand in `MEMORY_FULL.md`.

Write a verdicts JSON list **aligned by index** to the worksheet (`[{"similarity":…, "match_filename":…, "merged_body":…, "is_contradiction":…}, …]`), then apply:

```bash
$DREAM apply --worksheet /tmp/dream/worksheet_<i>.json --verdicts /tmp/dream/verdicts_<i>.json \
    --today $(date +%F) --session <session_id> > /tmp/dream/apply_<i>.json
```

`apply` routes each verdict through the existing `consolidate(...)` write ops — auto-merge ≥0.85, then **auto-append everything below** (Nathan's OS#134 ruling: the ambiguous 0.55–0.85 band is auto-approved as a new file, not held) — and reports `flagged` + `written_paths`. The **only** thing still `flagged` is a candidate that contradicts a `nathan-stated` memory (held, never auto-written). **Never** re-implement the band logic here.

## Step 4 — finalize once per run (batched)

Merge every `apply_<i>.json`'s `flagged` and `written_paths` with step 1's transcript list into one results file:

```json
{"flagged": [...all...], "written_paths": [...all...], "transcripts": [...unprocessed.json...]}
```

```bash
$DREAM finalize --results /tmp/dream/results.json > /tmp/dream/finalize.json
```

This regenerates `MEMORY.md`, **merges this run's holds into the durable open set** (`data/dream/flagged.jsonl`, de-duped by key) and rebuilds `MEMORY_REVIEW.md` from the **full** open set — a barren run never wipes prior holds (OS#134 Bug 1). It then **commits the store as a doc-only `[skip ci]` change** (HARD CONSTRAINT #2 / acceptance #5 — memory commits never burn a CI run), records every processed transcript in the ledger (even barren ones, so they are not re-processed), and drains the Stop-hook queue.

## Step 5 — roadmap reconciliation (§13.4 intent pass, OS#231)

After finalize, probe whether `documentation/ROADMAP.md` has fallen behind reality:

```bash
$ROADMAP probe > /tmp/dream/roadmap_probe.json
```

- **`"stale": false`** → report "roadmap current" and move on. Nothing is written.
- **`"stale": true`** → run the reconciliation:

```bash
gh issue list -R NathanKrupa/OverSteward --state all --limit 100 \
  --json number,title,state > /tmp/dream/issues.json
gh pr list -R NathanKrupa/OverSteward --state all --limit 100 \
  --json number,title,state > /tmp/dream/prs.json
$ROADMAP packet --issues /tmp/dream/issues.json --prs /tmp/dream/prs.json \
  > /tmp/dream/roadmap_packet.md
```

Read the packet plus the transcripts already processed this run, then draft a
**dated reconciliation section** in the roadmap's established shape (§3.5/§3.6
pattern: shipped / corrections to prior gap tables / started-not-landed
watch-list) and bump the `*Last updated:*` stamp. Historical sections are never
rewritten — reconciliation is additive, corrections ride in the new section.

**Write path (OS#90 — never commit to the primary checkout's master):**

```bash
scripts/dev/new-session.sh dream-roadmap-$(date +%F)
# edit documentation/ROADMAP.md in that worktree, commit as
#   docs(roadmap): <date> reconciliation (dream cycle) [skip ci]
# push, open the PR, merge it, remove the worktree
```

Intent found in transcripts that was never filed as an issue is **flagged, not
filed** (epic OS#230 decision 2): surface it in the run report for the waking
session; do not open issues from the dream.

## Step 6 — trajectory promotion (§13.5 lesson pass, OS#325)

The estate writes ~1,270 lesson bullets a quarter into trajectory notes and
promotes almost none of them, which is why nine error classes each recurred
across 9-11 distinct PRs. This pass closes that loop monthly.

```bash
$PROMOTION probe > /tmp/dream/promotion_probe.json
```

- **`"due": false`** → report "promotion current" and move on.
- **`"due": true`** → build the report, then the worklist:

```bash
fiscus review trajectories --all-active --since <last-run-or-60d> \
  --min-cluster 3 --format json > /tmp/dream/patterns.json
$PROMOTION packet --report /tmp/dream/patterns.json --record \
  > /tmp/dream/promotion_packet.md
```

**Exit codes carry meaning — do not collapse them.** `0` is a measured result
(the packet says plainly when there is nothing to promote). **`2` means the
detector is broken**, not that the estate is quiet: the report claimed zero
patterns across a corpus far too large for that, or declared no corpus size at
all. On `2`, stop and surface it — an empty worklist reported as good news is
the exact failure this pass exists to prevent (Fiscus #101, which spent its whole
life answering "no patterns detected" over 425 notes).

Read the packet and, for each candidate, make one call: promote it into doctrine
(`shared/references/`, CLAUDE.md, an agent card) or into memory, or record why
not. Each candidate carries its recurrence count and contributing PRs, so the
decision is auditable without re-running the report.

**Write path (OS#90 — never commit to the primary checkout's master):**

```bash
scripts/dev/new-session.sh dream-promotion-$(date +%F)
# edit the doctrine/memory surfaces in that worktree, commit as
#   docs(doctrine): promote <n> recurring lessons (dream cycle) [skip ci]
# push, open the PR, merge it, remove the worktree
```

The `--record` flag stamps the run ledger, so a **skipped month shows as a gap**
in `data/dream/promotion.json` rather than being silently forgotten. Record the
run even when the worklist is empty — a measured nothing is still a measurement.

## Draining the review surface (approve held items)

`MEMORY_REVIEW.md` is no longer a blocking queue — it accumulates only the `nathan-stated`-contradiction holds across runs. When Nathan has adjudicated, clear them explicitly (all, or one by its `key` shown in the surface):

```bash
$DREAM drain                       # approve & clear every hold
$DREAM drain --key <hold-key>      # clear just one
```

`drain` removes the items from the open set and rebuilds `MEMORY_REVIEW.md` from what remains, committing the surface as a doc-only `[skip ci]` change.

## Retiring a dead law (explicit, one memory at a time)

A `user` fact is a law outright, so a rule that has since been LIFTED keeps loading as live law — the worst class of always-loaded content. The cycle handles this on the way in: set `superseded_by` on the candidate and both write paths persist it, which files the fact under `## Graveyard`. That only reaches facts a transcript still raises. A rule nobody discusses any more never comes back through the cycle, so retire it by name:

```bash
python scripts/dream.py supersede <slug> "<what to reach for instead>"
python scripts/dream.py supersede <slug> "no successor — <why it was lifted>"
```

One named memory, one operator-supplied replacement, `MEMORY.md` rebuilt. Never a scan: the Graveyard is explicit-marker-only and retirement vocabulary alone must never drag a fact into it.

## Report

One short summary: sessions processed, facts appended/merged, holds surfaced for review (point Nathan at `MEMORY_REVIEW.md`, drained via `cycle drain`), the roadmap verdict ("roadmap current" or the reconciliation PR number + any unfiled-intent flags), the promotion verdict ("promotion current", the worklist size + PR number, or **a loud stop if the packet exited 2 — a broken detector, not a quiet estate**), and whether the commit landed. On a no-op run, just "ledger current."

## Invariants (do not violate)

- **Docs/memory only — never code.** The cycle's only writes are Markdown.
- **LLM steps are in-session/Max**, never the metered API.
- **Reuse the engine.** Extraction gating, the §6 bands, the provenance guard, and the commit all live in `src/oversteward/dream/`; this skill calls them, it never duplicates them.
- **The Stop hook never runs this cycle** — it only enqueues + reminds. Work runs here, in-session.

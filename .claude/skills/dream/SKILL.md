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
DREAM="python scripts/dream.py cycle"     # use the project venv's python
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

Read it and produce a JSON list of candidate facts following `oversteward.dream.extract.EXTRACTION_PROMPT` (the schema and the strict "when in doubt, omit" rules live there). Write that raw JSON to `/tmp/dream/extract_<i>.json`. Then gate + privacy-filter + prefilter it deterministically:

```bash
$DREAM worksheet --extract /tmp/dream/extract_<i>.json > /tmp/dream/worksheet_<i>.json
```

The worksheet drops noise and **hard-blocks secrets** (§7/§8) and attaches, per surviving candidate, the top-K Jaccard-nearest existing memories to judge against.

## Step 3 — judge (in-session) → apply

For each worksheet candidate, judge it against its `prefiltered` memories yourself, in-session, per the §6 bands and the provenance guard:

- score `similarity` (0–1) vs the nearest existing memory;
- name the matched memory's `filename` (or null if nothing is close);
- propose `merged_body` for an auto-merge; set `is_contradiction` when the candidate contradicts the match (a contradiction vs a `nathan-stated` memory is **surfaced, never auto-written**).

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

## Draining the review surface (approve held items)

`MEMORY_REVIEW.md` is no longer a blocking queue — it accumulates only the `nathan-stated`-contradiction holds across runs. When Nathan has adjudicated, clear them explicitly (all, or one by its `key` shown in the surface):

```bash
$DREAM drain                       # approve & clear every hold
$DREAM drain --key <hold-key>      # clear just one
```

`drain` removes the items from the open set and rebuilds `MEMORY_REVIEW.md` from what remains, committing the surface as a doc-only `[skip ci]` change.

## Report

One short summary: sessions processed, facts appended/merged, holds surfaced for review (point Nathan at `MEMORY_REVIEW.md`, drained via `cycle drain`), and whether the commit landed. On a no-op run, just "ledger current."

## Invariants (do not violate)

- **Docs/memory only — never code.** The cycle's only writes are Markdown.
- **LLM steps are in-session/Max**, never the metered API.
- **Reuse the engine.** Extraction gating, the §6 bands, the provenance guard, and the commit all live in `src/oversteward/dream/`; this skill calls them, it never duplicates them.
- **The Stop hook never runs this cycle** — it only enqueues + reminds. Work runs here, in-session.

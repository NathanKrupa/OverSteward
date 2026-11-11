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

## Step 0 — take the run lock

```bash
$DREAM begin
```

One dream run per machine (OS#690). `begin` records this session's `claude` process as the holder in `~/.claude/dream_run.lock` and appends a row to `~/.claude/dream_runs.jsonl`. **Its exit code decides what comes next — do not collapse them:**

- **`0`** — the lock is held by this run (taken now, or already ours). Go on to step 1.
- **exit 3** — another live run holds the lock (the boot-time timer racing a session's own `/dream`, or the reverse). **Stop here** and report "skipped: locked by <pid>" with the holder, trigger and start time it printed. Do not run any later step; the ledger already records the skip.
- **`2`** — the lock or the holder's liveness could not be read. **Stop and surface it loudly**: a run that cannot look does not write, and this is never a quiet morning.

Every store writer below (`apply`, `finalize`, `drain`, `supersede`) checks the same lock itself and exits 3 or 2 the same way, so a skipped Step 0 still cannot double-write the store; Step 0 only moves the refusal ahead of the expensive extraction. A run that dies holding the lock is reclaimed by the next one, with a `reclaimed` row naming the dead holder.

## Step 1 — enumerate unprocessed (no-op fast path)

```bash
$DREAM unprocessed > /tmp/dream/unprocessed.json
```

Each entry is a transcript whose content hash is **not** in the processed ledger. **If the list is empty, stop here** — measure the store, release the lock and close the run, then report "ledger current, nothing to consolidate" followed by the store-health closing line, and exit clean:

```bash
$DREAM store-health > /tmp/dream/dangling.json   # read-only; prints the closing line in its JSON
$DREAM end --reason "ledger current"
```

Report the `closing_line` from `dangling.json` even on this path ("N dangling (ruled: unmeasured); store X notes / Y KB of Z KB ceiling"): a no-op run is never silent about the store. `store-health` exits **0** under every ceiling, **1** over one (a finding to report, not a stop), and **2** when the store could not be read — report that loudly ("store unreadable"), never as a quiet ledger.

This is what makes the cron backstop a safe no-op when a sign-off already drained the queue. **Any abort after Step 0** closes the same way, with the reason: `$DREAM end --reason "<why>"`.

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

## Step 3b — rule on the dangling-link queue

After every transcript is applied, measure the store and work the oldest dangling links:

```bash
$DREAM store-health > /tmp/dream/dangling.json
```

`queue` lists the oldest 10 `[[targets]]` that resolve to no note (neither a filename stem nor a `name:`), each with the notes citing it and its age. For each queued target, make exactly one ruling, in the store:

- **write the note** — `<target>.md`, whose frontmatter `name:` is the target, built from what the citers and this run's transcripts say. Never set `tier: standing` on it; the strict classifier derives its tier;
- **retarget the link** — when an existing note already covers it, rewrite `[[target]]` to that note's name in every citer;
- **drop the link** — remove the brackets, keeping the words, when nothing is worth writing.

Add every path you created or edited to the run's `written_paths`, so finalize commits it. Exit **1** is a size finding to carry into the report; exit **2** (store unreadable) is a loud stop: close the run with `$DREAM end --reason "store unreadable"` and report it.

## Step 4 — finalize once per run (batched)

Merge every `apply_<i>.json`'s `flagged` and `written_paths` with step 1's transcript list into one results file:

```json
{"flagged": [...all...], "written_paths": [...all...], "transcripts": [...unprocessed.json...]}
```

```bash
$DREAM finalize --results /tmp/dream/results.json --dangling-before /tmp/dream/dangling.json \
    > /tmp/dream/finalize.json
```

`--dangling-before` is the Step 3b snapshot: finalize re-measures the store and counts how many of those targets no longer dangle, which is the "M ruled this run" in its `store_health.closing_line`. Without it the line says "ruled: unmeasured". Finalize exits **2** when the store could not be measured, before any commit or ledger row; over a ceiling it still exits 0, because its exit code speaks for the commit and the ledger — the overage is in `store_health.over` and the closing line.

This regenerates `MEMORY.md`, **merges this run's holds into the durable open set** (`data/dream/flagged.jsonl`, de-duped by key) and rebuilds `MEMORY_REVIEW.md` from the **full** open set — a barren run never wipes prior holds (OS#134 Bug 1). It then **commits the store as a doc-only `[skip ci]` change** (HARD CONSTRAINT #2 / acceptance #5 — memory commits never burn a CI run), records every processed transcript in the ledger (even barren ones, so they are not re-processed), and drains the Stop-hook queue. On success it **releases the run lock** and closes the run with a `completed` row carrying the transcript count; a finalize that fails keeps the lock, so its retry is still this run's.

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
#   docs(roadmap): <date> reconciliation (dream cycle)
# push, open the PR, run the adversarial reviewer, paste its verdict into the
# body, merge it, remove the worktree. No `[skip ci]` on a PR-bound commit: the
# marker suppresses the reviewer-verdict job, and a gate that never runs reads
# as green (both 2026-09-08 dream PRs were BLOCKED on it). Only the memory-store
# commits finalize makes are `[skip ci]` (HARD CONSTRAINT #2).
```

Intent found in transcripts that was never filed as an issue is **flagged, not
filed** (epic OS#230 decision 2): surface it in the run report for the waking
session; do not open issues from the dream. When the flagged intent is one of
Nathan's own ideas, the waking session offers it to the Estate Idea Incubator
note in his vault, not to GitHub (OS#613); an agent finding it files instead
carries `agent-finding`.

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
#   docs(doctrine): promote <n> recurring lessons (dream cycle)
# push, open the PR, run the adversarial reviewer, paste its verdict into the
# body, merge it, remove the worktree — no `[skip ci]`, as above.
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

A `user` fact is a law outright, so a rule that has since been LIFTED keeps loading as live law — the worst class of always-loaded content. The cycle handles this on the way in: set `superseded_by` on the candidate and both write paths persist it, which files the fact under `## Graveyard`. That only reaches facts a transcript still raises. A rule nobody discusses any more never comes back through the cycle.

To find candidates, read the correction worklist (OS#691). It writes nothing to the store, takes no lock, and issues no verdicts. Reading a sibling repo's tree fetches `origin/<branch>` in that checkout first, as `estate_map.py check` does:

```bash
python scripts/dream.py correction worklist   # --limit 10 --min-age-days 30 by default
```

It lists the Laws and Habits least recently reinforced (`last_reinforced`, else `created`, else `modified`; undated notes first), each with evidence from its description, digest and body outside fenced blocks: paths from inline code spans only, `tracked` (a registry checkout tracks a file or directory at that path or ending in it) or `untracked` (a gitignored runtime path reads `untracked` too); `OS#`/`GS#`/`AG#` refs from spans and prose alike, each once, `open`, `closed` or `missing`; and `unchecked`/`named` span tokens nothing verified (another prefix is `unchecked` in a span and ignored in prose). Exit 2 is could-not-look (an absent or empty store, a note that does not parse, a tree or `gh` read that failed, or the "instrument blind" canary), never an empty list. Age only ranks a note, and an `untracked` path is evidence, not a verdict: a law nobody mentions may simply be obeyed.

Then retire a dead one by name:

```bash
python scripts/dream.py supersede <slug> "<what to reach for instead>"
python scripts/dream.py supersede <slug> "no successor — <why it was lifted>"
```

One named memory, one operator-supplied replacement, `MEMORY.md` rebuilt. Never a scan: the Graveyard is explicit-marker-only and retirement vocabulary alone must never drag a fact into it.

## Report

One short summary: sessions processed, facts appended/merged, holds surfaced for review (point Nathan at `MEMORY_REVIEW.md`, drained via `cycle drain`), the roadmap verdict ("roadmap current" or the reconciliation PR number + any unfiled-intent flags), the promotion verdict ("promotion current", the worklist size + PR number, or **a loud stop if the packet exited 2 — a broken detector, not a quiet estate**), and whether the commit landed. **End with the store-health closing line** — finalize's `store_health.closing_line` ("N dangling (M ruled this run); store X notes / Y KB of Z KB ceiling", plus "OVER CEILING: …" when a measure is over). On a no-op run, "ledger current" followed by the closing line from Step 1. A store-health exit 2 is a loud stop, never a quiet report.

## Invariants (do not violate)

- **Docs/memory only — never code.** The cycle's only writes are Markdown.
- **LLM steps are in-session/Max**, never the metered API.
- **Reuse the engine.** Extraction gating, the §6 bands, the provenance guard, and the commit all live in `src/oversteward/dream/`; this skill calls them, it never duplicates them.
- **The Stop hook never runs this cycle** — it only enqueues + reminds. Work runs here, in-session.
- **One run per machine.** Step 0 takes the run lock; finalize or `$DREAM end --reason` releases it. Exit 3 is a skip and exit 2 is a stop, never a run.

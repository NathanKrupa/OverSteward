---
name: pipeline-status
description: "Show the Vintner's corpus & enrichment funnel — counts per stage, coverage % / drop-off, velocity (Δ since last run), running-vs-STOPPED freshness, and the AG-visible gap for the Grant Helper Pro (AG+GS) data pipeline. Reads vintner.corpus_funnel_v read-only via the vintner_reader role. Deterministic, zero LLM. Use when Nathan asks for \"pipeline status\", \"corpus funnel\", \"how's the corpus\", \"is the pipeline moving\", or runs /pipeline-status."
---

# /pipeline-status -- corpus & enrichment funnel

A one-table view of the Grant Helper Pro data pipeline: how many rows have reached each stage, what fraction of the logical parent each stage covers (the leak is the signal), how much each stage moved since the last run, whether each stage is running or has gone cold, and which stages never reach the AG matchmaker.

This is the Vintner's first concrete report surface (design: `documentation/designs/the-vintner.md`). All work is done by `scripts/pipeline_status.py` — a deterministic spine that reads one aggregate view and formats. **Zero LLM** on the path (honors the no-paid-API-until-$1k law); the read is **read-only** through the `vintner_reader` role, which can see only `vintner.*` views.

## Invocation

```
/pipeline-status
```

No arguments.

## Prerequisites

- `VINTNER_RESEARCH_DATABASE_URL` must be set (the `vintner_reader` connection string → GS `neondb`, view-only). It lives in OverSteward `.env`, out of version control. The script exits `2` with a clear message if it is unset.
- The `psycopg` driver (declared in the `vintner` optional extra). `uv run` resolves it.

## What the skill does

### 1. Run the funnel script

```bash
uv run --extra vintner python scripts/pipeline_status.py
```

- Runs from the OverSteward repo root.
- Reads `vintner.corpus_funnel_v` (11 stage rows: `stage_order`, `stage`, `count`, `newest_at`).
- Reads/writes velocity state at `.claude/skills/pipeline-status/state.json` (gitignored, per-machine).
- Exit codes: `0` success, `1` live-read failure (DB unreachable / view missing), `2` `VINTNER_RESEARCH_DATABASE_URL` unset.

The script prints markdown to stdout. Print that output verbatim to Nathan.

### 2. No other side effects

The script is read-only against the database (the `vintner_reader` role cannot write and cannot see base tables). The only local write is the velocity snapshot at `state.json`.

## Reading the output

- **Verdict** (top line): worst structural signal across the funnel — STOPPED (a stage has gone cold), GAPS (a stage has 0 rows), SLOWING (a stage is stale), or HEALTHY.
- **Count**: rows that have reached the stage.
- **Coverage**: the stage's count as a % of its logical parent (e.g. `websites_crawled` / `foundations_with_website`). A low coverage % is where the corpus leaks.
- **Δ since last run**: velocity — `+N` per stage vs the previous run. Appears from the **second run onward** (first run persists the baseline). This is the "moving vs stalled" signal.
- **Freshness**: age of the newest record for the stage (`newest_at`). `—` means the view exposes no freshness stamp for that stage (e.g. `foundations_total`, `display_name_present`).
- **State**: `running` (fresh, ≤48h), `STALE` (48h–7d), `STOPPED` (>7d — the enrichment stages surface here when kill-switched OFF), `empty` (0 rows). A frozen count is **never** reported as healthy.
- **AG-visible**: `yes` if the stage's data reaches the AG matchmaker (only `foundations_v`/`grants_v` are exposed), `INVISIBLE` otherwise. Crawl, sitemap, deadline, and enrichment data is structurally invisible to AG — the highest-value gap column.

## Notes on interpretation

- `sitemaps_discovered` counts sitemap **candidates discovered**, not fetched — do not read it as crawl progress.
- The enrichment stages (`enrichments_active`, `missions_present`, `deadlines_present`) are fed by a currently kill-switched stage; their `newest_at` is what reveals OFF. An old stamp ⇒ STOPPED, not healthy.
- `display_name_present` is a deliberate field-health signal (currently ~0% populated).

## Architecture

- **Spine (MIDDLE):** `src/oversteward/vintner/` — `funnel.py` (coverage / velocity / freshness / verdict, pure Python), `render.py` (formatting), `snapshot.py` (velocity persistence), `models.py`. Fixture-tested; no DB, no LLM.
- **Reader (INNER):** `src/oversteward/vintner/reader.py` — the one read-only adapter to GS `neondb`; connection string injected, only the factory reads env.
- **Skill (OUTER):** this file + `scripts/pipeline_status.py` — thin: invoke, format, print.

## Out of scope (later Vintner phases)

The full health **oracle** — 30-min cron, SLA red/yellow/green thresholds, GitHub-issue alerting, the leashed narrative agent. This skill is the **report surface** only; it becomes the oracle's input layer later.

## Related

- `documentation/designs/the-vintner.md` — the Vintner design doc.
- `/project-status` — the sibling dispatch dashboard (open issues / PRs / in-flight agents).

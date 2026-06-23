ABOUTME: Phase 0 architecture note for OverSteward's sleep-time memory-consolidation loop — a cold-path background process that digests each session's transcript into durable, de-duplicated, contradiction-resolved Markdown memory, automatically, without hand-curation.
ABOUTME: Design gate only (2026-06-23). No Phase 1 code until Nathan signs off the open decisions in §9.

# Sleep-Time Consolidation Loop — Auto-Dream for the Estate's Memory

**Status:** **Phase 0 — design for review (2026-06-23).** No implementation code. Phase 1 clears on Nathan's sign-off of the open decisions in §9.

**Name:** the *sleep-time* loop — the steward labours over the day's ledger while the House is abed, so the books are clean by morning without anyone sitting up to do them.

**Author:** Chestertron, 2026-06-23.

**Kinship:** Reuses the estate's existing nervous system — the per-file Markdown memory store already auto-loaded each session (`~/.claude/projects/.../memory/` + `MEMORY.md`), the `.claude/hooks/` mechanism (already running `guard_main_worktree.py`), and — for the eventual *read* side only — GrantSpider's BM25 + pgvector + Reciprocal Rank Fusion. Sibling to **The Telegraph** (both are background coordinators) and downstream of the existing hand-written-memory discipline this loop automates.

---

## 1. The problem

Memory today is **hot-path only**: the live session writes a memory file when Chestertron remembers to, mid-conversation, competing for the same context window that's doing the work. That depends on diligence at exactly the moment attention is scarcest. The result is real but uneven — 86 files today, written when someone thought of it, never systematically de-duplicated or aged.

The fix is a **cold path**: after a session ends, a background process reads the raw transcript and does the librarian's work — extract the durable facts, resolve them against what's already on the shelves, evict what's gone stale — and commits the result. Memory changes outside any live interaction. The agent dreams.

This is the documented "sleep-time agent" pattern; the design below builds to the surfaced findings rather than from first principles ([Bustamante, *Agent Memory Engineering*](https://nicolasbustamante.com/blog/agent-memory-engineering)).

## 2. Five movements

`trigger → extract → resolve/dedup → write → decay` ([arXiv 2603.15642](https://arxiv.org/pdf/2603.15642)). Each is a section below.

## 3. Schema — feed what already exists, don't reinvent

**Decision: the loop maintains the existing per-file store, it does not create a parallel `## Consolidated Memory` block.** That store already has the right shape — one fact per file, frontmatter-typed (`user | feedback | project | reference`), `[[slug]]`-linked, with a `MEMORY.md` index auto-loaded each session. A second store would silt up beside the first and split recall. The loop becomes the *automated writer/maintainer* of the store humans currently hand-edit. (Markdown beats cleverness — the notable 2026 finding is that a plain Markdown file out-performed vector DBs, graphs, and dedicated memory agents; we already have it, so we do **not** add a graph/vector store in Phase 1 — [Bustamante](https://nicolasbustamante.com/blog/agent-memory-engineering).)

**Frontmatter, extended** (adds the fields the loop needs; existing files migrate lazily on next touch):

```yaml
---
name: <slug>
description: <one-line — the recall-relevance hook>
metadata:
  type: user | feedback | project | reference
  provenance: nathan-stated | claude-inferred   # see feedback_memory_provenance
  source_sessions: [<id>, ...]                   # audit: which sessions produced/reinforced this
  created: 2026-06-23
  last_reinforced: 2026-06-23                     # bumped when a later session re-derives the same fact
  access_count: 0                                 # bumped when recalled into a live session
  last_accessed: null
  confidence: high | medium | low                # extraction confidence; low = verify-before-trust
  decay_status: active | flagged-stale | flagged-merge
---
```

**Fleet-awareness** (§9-7): the store must serve GrantSpider, the Matchmaker, Gaudí, and Design Cortex, so a lesson learned by one is readable by another. Two sub-questions are open (§9): (a) **where the source-of-truth lives** — the per-machine `~/.claude/...` auto-load dir is *not* git-tracked and *not* shared, which contradicts Nathan's "commit to git, each commit is the audit trail" and "fleet-aware" requirements; and (b) the **sync mechanism**. Recommended reconciliation: the **git-tracked source of truth lives in the OverSteward repo** (e.g. `memory/`), the loop commits there (audit trail + fleet-shared), and a deploy step mirrors it into each machine's `~/.claude/.../memory/` auto-load location — exactly the pattern `shared/` already uses to reach `~/.claude/shared/`. This is the single most important decision to confirm.

## 4. Trigger — automatic, never on willpower

Nathan named the constraint directly: *"the system must not depend on my daily diligence."* So the trigger is mechanical, belt-and-braces ([arXiv 2603.15642](https://arxiv.org/pdf/2603.15642)):

- **Primary: a Claude Code `Stop` hook** in `.claude/settings.json` (this repo already runs a `PreToolUse` hook, so the mechanism is proven). On session end it enqueues the just-finished transcript for consolidation.
- **Fallback: a cron / systemd-timer nightly sweep** that consolidates any transcript not yet processed (catches sessions that crashed, were killed, or never fired `Stop` — e.g. the resident Telegraph operator session, which rarely ends cleanly).

The two together mean a session is consolidated whether it exits gracefully or not. Idempotency (a processed-transcript ledger) prevents double-counting.

## 5. Extract — cheap model reads, expensive model reasons

Two models, cheap-then-expensive ([Bustamante](https://nicolasbustamante.com/blog/agent-memory-engineering)):

- **Extraction (cheap — Haiku 4.5):** read transcript → candidate facts, entities, relations, and **procedural lessons** (operational heuristics — "X failed because Y; do Z next time"). High volume, low reasoning, runs per session.
- **Consolidation (expensive — Sonnet/Opus):** take the candidates + the relevant existing memory and do the contradiction-resolution / merge reasoning. Low volume, high stakes.

Procedural-lesson capture is its own first-class output, not just facts ([Analytics Vidhya, *Memory Systems in AI Agents*](https://www.analyticsvidhya.com/blog/2026/04/memory-systems-in-ai-agents/)) — e.g. today's session would yield *"merged GS migrations are not auto-applied to prod; check `alembic_version` vs head and migrate-before-promote since prod deploys from main."*

**Extraction prompt (Phase 1 draft):**

> You are reading a development-session transcript to extract DURABLE memory. Output a JSON list of candidate facts. For each: `{type, description (one line), body, provenance (nathan-stated|claude-inferred), confidence (high|medium|low), is_procedural (bool)}`.
> Extract ONLY facts that will matter in a FUTURE session: user preferences/rulings, operational lessons (what failed and the fix), durable project state not derivable from code/git, and external references. A procedural lesson must state the trigger, the failure, and the corrective action.
> Do NOT extract: anything recoverable from the repo, code, or git history; transient task chatter; one-off values; restatements of CLAUDE.md. When in doubt, omit (the signal gate is strict — §7).

## 6. Resolve / dedup — asymmetric caution, concrete bands

The governing asymmetry ([Decoding AI, *Neo4j graph agent memory*](https://www.decodingai.com/p/understanding-neo4j-graph-agent-memory-system)): **a false merge is silent and unrecoverable; a false split is noisy but recoverable.** So we never silent-merge the ambiguous middle.

For each extracted candidate, the consolidation model scores similarity against existing memories (compared against the ~86 short `description` lines + the slug — cheap to judge in full, no vector store needed; the per-file structure makes this an N-way short-string comparison):

| Band | Similarity | Action |
|---|---|---|
| **High** | ≥ 0.85 | **Auto-merge** — update/refine the existing file; bump `last_reinforced`, append `source_sessions`. A *contradiction* at high similarity does NOT auto-overwrite a `nathan-stated` fact — it gets **flagged** (see `feedback_memory_provenance`). |
| **Ambiguous** | 0.55–0.85 | **FLAG, never silent-merge** — write the candidate to a review queue (`decay_status: flagged-merge`) for human adjudication. |
| **Low** | < 0.55 | **Append** as a new file. |

Phase-1 similarity = the **consolidation model's judgment** over the candidate vs each existing `description` (a closed, cheap comparison), optionally pre-filtered by slug/title token-overlap (Jaccard) to keep the model call small. No embeddings in Phase 1 (§ Phase 2 earns them only if this fails).

**Flag surface (§9-5):** flagged items land somewhere Nathan actually sees them — candidate: a `MEMORY_REVIEW.md` at the store root that the next session surfaces, and/or the loop's commit/PR. Open decision.

## 7. Signal gate — deciding NOT to remember

As important as extraction; without it the store silts up ([Bustamante](https://nicolasbustamante.com/blog/agent-memory-engineering)). Hard *don't-remember* rules (mirroring the store's existing hand-curation guidance):

- Anything recoverable from the repo, code, CLAUDE.md, or git history.
- Transient conversation, task-local state, one-off values.
- Facts already covered by an existing memory with no new information (→ at most a `last_reinforced` bump, no new file).
- Low-confidence single-mention claims with no corroboration (hold, don't write).
- Secrets — handled by the privacy filter (§8) as a hard block, not a judgment call.

## 8. Privacy filter — hard block before any write

Strip/refuse secrets before storage ([agentmemory](https://github.com/rohitg00/agentmemory)). Reuse the estate's existing credential-hygiene denylist (the `check_db_access` patterns already in `~/.claude/hooks/` / `shared/references/credential-hygiene.md`): API keys, `*_DATABASE_URL`, `postgresql://…@`, tokens, `.env` values. Implementation: a regex pass over every candidate body+description **before** the write; a match **drops the candidate and logs** (never writes a redacted-but-still-suspicious fact). This is a gate, not a scrubber.

## 9. Decay / eviction — Ebbinghaus, recoverable

Stale memories age out; frequently-accessed ones strengthen ([agentmemory](https://github.com/rohitg00/agentmemory)). Tracked in frontmatter (§3):

- **Reinforce on access:** when a memory is recalled into a live session, bump `access_count` + `last_accessed`. When a later session re-derives the same fact, bump `last_reinforced`.
- **Decay:** strength ≈ f(recency, frequency). A `reference`/`project` memory not accessed in **N days** (proposed 90) with low `access_count` → `decay_status: flagged-stale`. `user` and `nathan-stated feedback` memories **never auto-decay** (durable law).
- **Eviction is a flag, not a delete** (false-split caution): flagged-stale items are surfaced for one-tap human eviction or moved to an `archive/` (recoverable), never silently removed.

## 10. Verification discipline on read

Recall wraps each fact with **age + a trust hint** ([Bustamante](https://nicolasbustamante.com/blog/agent-memory-engineering)). The session system-prompt already says recalled memories "reflect what was true when written … verify before recommending." This loop makes that concrete: every fact carries `created`/`last_reinforced`, and recall renders e.g. *"(written 2026-03-01, 114 days old, confidence: medium — verify before trusting)."* Older-than-threshold + names-a-file/flag/function ⇒ explicit re-verify nudge.

## 11. Phase 1 — minimal working loop (scope)

Dependency-light, Markdown-only, Python on WSL Ubuntu-24.04, runnable from Claude Code:

1. **Trigger:** `Stop` hook + nightly cron fallback; a processed-transcript ledger for idempotency.
2. **Extract:** Haiku pass over the transcript → candidate JSON.
3. **Gate + privacy:** signal gate drops noise; privacy filter hard-blocks secrets.
4. **Resolve:** consolidation model applies the §6 bands against existing `description` lines — auto-merge high, flag ambiguous, append low.
5. **Write + commit:** update Markdown + `MEMORY.md` index; `git commit` with a descriptive message (the audit trail). Flagged items → review surface.

Explicitly **out of Phase 1:** embeddings/vector store, graph store, cross-fleet transcript ingestion beyond OverSteward, auto-editing CLAUDE.md/architecture-principles (procedural lessons land as `feedback` memories; promotion to standing instructions stays human-gated — auto-editing standing instructions is high-blast-radius).

## 12. Phase 2 — earn the complexity (future, not now)

Only if Markdown demonstrably fails: a richer **read** side reusing GrantSpider's **BM25 + pgvector + Reciprocal Rank Fusion** rather than a new invention — RRF over the memory corpus for relevance recall at scale; optionally a graph layer for `[[slug]]` relationship traversal. Documented here as the sanctioned future path; not built until the Markdown store's recall measurably breaks.

## 13. Open decisions (need Nathan)

1. **Storage source-of-truth: OverSteward repo (git-tracked, fleet-shared, audited) with a deploy-to-`~/.claude` step — vs the existing per-machine `~/.claude/.../memory/` dir.** (Recommend: repo is source of truth, mirrors the `shared/` deploy pattern.) *Central — everything else assumes this.*
2. **Transcript access:** exact path/format Claude Code exposes the just-finished transcript to a `Stop` hook (and how the cron fallback enumerates unprocessed ones).
3. **Extraction model billing:** Haiku via metered API per session — confirm cost tolerance, or run consolidation only on a schedule to batch. (Background API calls are metered, not subscription.)
4. **Dedup compute:** pure consolidation-model judgment vs Jaccard-prefilter + model. (Recommend prefilter to bound cost.)
5. **Flag-review surface:** `MEMORY_REVIEW.md` surfaced next session, a Telegraph push, and/or the consolidation commit/PR?
6. **Decay parameters:** the N-day staleness window (proposed 90) and eviction = flag-vs-archive-vs-delete.
7. **Fleet scope for Phase 1:** OverSteward sessions only first, then generalize — or all fleet repos from the start? (Recommend: OverSteward first.)
8. **Procedural-lesson promotion:** keep lessons as `feedback` memories with human promotion to CLAUDE.md, or let the loop propose CLAUDE.md edits as flagged PRs? (Recommend: human-gated.)

---

*Phase 0 deliverable. Awaiting sign-off on §13 before any Phase 1 code is written.*

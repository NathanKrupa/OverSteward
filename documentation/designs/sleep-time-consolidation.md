ABOUTME: Phase 0 architecture note for OverSteward's sleep-time memory-consolidation loop — a cold-path background process that digests each session's transcript into durable, de-duplicated, contradiction-resolved Markdown memory, automatically, without hand-curation.
ABOUTME: Design gate only (2026-06-23). No Phase 1 code until Nathan signs off the open decisions in §14.

# Sleep-Time Consolidation Loop — Auto-Dream for the Estate's Memory

**Status:** **Phase 0 — design for review (2026-06-23).** No implementation code. Phase 1 clears on Nathan's sign-off of the open decisions in §14.

**Name:** the *sleep-time* loop — the steward labours over the day's ledger while the House is abed, so the books are clean by morning without anyone sitting up to do them.

**Author:** Chestertron, 2026-06-23. **Revised 2026-06-24:** added the two living artifacts (§13a) — the scope-map (present) and the roadmap (present→future intent) — and the intent-reconciliation pass (§13.4) that maintains the roadmap.

**Kinship:** Reuses the estate's existing nervous system — the per-file Markdown memory store already auto-loaded each session (`~/.claude/projects/.../memory/` + `MEMORY.md`), the `.claude/hooks/` mechanism (already running `guard_main_worktree.py`), and — for the eventual *read* side only — GrantSpider's BM25 + pgvector + Reciprocal Rank Fusion. Sibling to **The Telegraph** (both are background coordinators) and downstream of the existing hand-written-memory discipline this loop automates.

---

## Operating rule — when the loop runs (Nathan-stated law, 2026-06-23)

**The gate is work-assignment, not time-of-day** — this supersedes the earlier "no code at night" framing:

> The gate is work-assignment, NOT time-of-day. Assigned work → you may do it, code included, any hour. When the assigned queue is exhausted → automatically enter the dream cycle (doc/memory consolidation only, never code). No "don't code at night" rule.

Two consequences for this design:

- **The loop is queue-triggered, not clock-triggered.** It is what the steward does *when the assigned work runs out*, at any hour — not a nightly window that forbids daytime work, nor one that licenses unsupervised night coding. The dream cycle writes **docs and memory only**; it never writes code. (A hotfix is *assigned* work, handled on the live path, not by the dream cycle.)
- **Doc-changes-skip-CI.** The dream cycle's only writes are Markdown — memory files, `MEMORY.md`, design notes. Doc-only PRs (no Python touched) skip the full pytest suite; ruff/lint still run. That is what lets a consolidation commit land cheaply, without burning a CI run on every memory update.

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

**Fleet-awareness** (§14-7): the store must serve GrantSpider, the Matchmaker, Gaudí, and Design Cortex, so a lesson learned by one is readable by another. Two sub-questions are open (§14): (a) **where the source-of-truth lives** — the per-machine `~/.claude/...` auto-load dir is *not* git-tracked and *not* shared, which contradicts Nathan's "commit to git, each commit is the audit trail" and "fleet-aware" requirements; and (b) the **sync mechanism**. Recommended reconciliation: the **git-tracked source of truth lives in the OverSteward repo** (e.g. `memory/`), the loop commits there (audit trail + fleet-shared), and a deploy step mirrors it into each machine's `~/.claude/.../memory/` auto-load location — exactly the pattern `shared/` already uses to reach `~/.claude/shared/`. **Confirmed by Nathan 2026-06-24 (§14-1).**

## 4. Trigger — automatic, never on willpower

Nathan named the constraint directly: *"the system must not depend on my daily diligence."* So the trigger is mechanical, belt-and-braces ([arXiv 2603.15642](https://arxiv.org/pdf/2603.15642)):

- **Primary: the operating-rule auto-dream.** When a live Claude Code session's assigned queue empties, that same in-session agent (on the Max subscription) runs the consolidation over the just-finished transcript(s). A `Stop` hook in `.claude/settings.json` enqueues the transcript and can surface the prompt; the *work itself runs in-session*, not inside the hook.
- **Fallback: a scheduled headless Claude Code run** — a cron that invokes `claude -p "run the dream cycle"` over any transcripts not yet processed (catches crashed/killed sessions and the resident Telegraph operator, which rarely ends cleanly). This is **still in-session / Max** (headless Claude Code uses the subscription), **not** a metered-API daemon.

The two together mean a session is consolidated whether it exits gracefully or not. Idempotency (a processed-transcript ledger) prevents double-counting.

## 5. Extract — cheap model reads, expensive model reasons

Two stages, cheap-then-expensive ([Bustamante](https://nicolasbustamante.com/blog/agent-memory-engineering)) — **both run IN-SESSION on the Max subscription** (Nathan-stated 2026-06-24), never on the metered API:

- **Extraction (cheap):** read transcript → candidate facts, entities, relations, and **procedural lessons** (operational heuristics — "X failed because Y; do Z next time"). High volume, low reasoning. Runs as an in-session sub-agent (the `Task`/`Agent` tool) — which can use a cheaper model tier but is **billed to the subscription, not metered** — the same Max-vs-metered logic as the dispatch foreground pivot ([[reference_in_session_vs_background_billing]]).
- **Consolidation (expensive):** the session model takes the candidates + the relevant existing memory and does the contradiction-resolution / merge reasoning. Low volume, high stakes.

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

**Flag surface (§14-5):** flagged items land somewhere Nathan actually sees them — candidate: a `MEMORY_REVIEW.md` at the store root that the next session surfaces, and/or the loop's commit/PR. Open decision.

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

## 13. The broader dream cycle — nightly reconciliation

Memory consolidation (§1–§12) is the **first** movement of the estate's dream cycle. The same cold-path, queue-empty trigger (§ *Operating rule*) drives **four** further **reconciliation** passes — each compares what the estate *believes* against what is *actually true*, and either files the drift as memory or issues for the waking session, or maintains a **living artifact** (§13a). All four are read-and-report only: none mutates production, and none writes code.

1. **Ought-vs-actual map.** Reconcile the *declared* state — `architecture.md`, `registry.yaml`, the design docs, the standing invariants — against the *real* repos: open PRs, merged migrations, live seams, deployed code. Drift (a doc that claims a seam not yet live; an invariant a recent merge quietly violated) becomes a flagged memory or a filed issue. The documentation-truth audit the steward runs while the House sleeps.
2. **Nightly Playwright journeys.** Drive the real customer-facing journeys headless against the live app (e.g. AG signup → onboarding → first search) and capture where they break. The 2026-06-22 onboarding-500 that stopped the estate's first real customer before he reached search is exactly the failure a nightly journey catches *before* a human hits it. Output: a pass/fail journey report + screenshots, surfaced for the morning.
3. **Predicted-vs-actual usage.** Compare what the estate predicted customers would do against what they actually did — signups, logins, feature reach, drop-off. Divergence (a customer who signed up but never reached search) is surfaced as a finding, not silently logged.
4. **Intent reconciliation — the roadmap.** Harvest *intent* from the same session transcripts the memory loop already reads (§5) plus the issues filed across the estate, and reconcile it against what's built (pass 1) and what's in-flight (open PRs/issues). The output is a maintained `documentation/ROADMAP.md` — *where we are trying to go* — and, crucially, the **gap**: intent expressed but never filed, filed but never started, started but never landed. This is the steward's answer to the House's standing weakness — *pieces begun and not finished*. Nothing said in a conversation or filed as an issue evaporates: the roadmap is where loose intent is caught and held until it either ships or is consciously shelved. Read-and-report like the others — it proposes a refreshed roadmap and a flagged started-not-landed list; it does not itself do the work.

### 13a. Living artifacts — the estate's self-portrait

Two of the reconciliation passes don't merely file drift; they **maintain a durable, always-current document** so that any agent, on any session, opens with a true picture. They are a facing pair — *present* and *future*:

| Map | Tense | Canonical (rich) | Agent-facing (slim) | Kept current by |
|---|---|---|---|---|
| **Scope-map** — *what's built* | present | `architecture.md` | a slim, auto-loaded digest of §1 repos + §3 invariants | ought-vs-actual pass (§13.1) |
| **Roadmap** — *where we're going* | future | `documentation/ROADMAP.md` | a slim, auto-loaded digest of active horizons + the started-not-landed gap | intent pass (§13.4) |

**Decided (Nathan, 2026-06-24):** the rich canonical docs stay the source of truth; the dream cycle **emits the slim agent-facing digests** rather than expanding the rich docs or letting dispatch agents read the heavy ones. (Confirms option B for the scope-map; the roadmap follows the same shape.) The digest is what a dispatch agent loads for "current scope of the project" — small enough to carry every session, regenerated whenever its canonical parent changes. This resolves the long-standing tension that `architecture.md` is explicitly *not* read by dispatch agents: the rich doc stays a scoping-time tool, the slim digest is the agent-time view.

**Why this matters — a live example.** The instant PR#100 merged (OverSteward became a dispatch target), `architecture.md`'s oversteward row went stale — *"Pickup target: no"* — and nothing caught it. That five-minute-old drift is exactly what the ought-vs-actual pass exists to find and the scope-map digest exists to keep honest. Fittingly, the design for the unfinished-work-catcher was itself an unmerged PR (this one, #94) — the same lesson, one level up.

These inherit the memory loop's discipline — strict signal gate (§7), privacy filter (§8), flag-don't-act on the ambiguous (§6) — and feed the same store and review surface. They are **out of the memory-loop's Phase 1** (§11); their own scope and cadence fold into the same sign-off gate below before any code is written.

## 14. Open decisions (need Nathan)

1. **✅ RESOLVED (Nathan, 2026-06-24):** storage source-of-truth = the **OverSteward repo** (git-tracked `memory/`, audited, fleet-shared), with a deploy step mirroring it into each machine's `~/.claude/.../memory/` auto-load dir — exactly the `shared/` → `~/.claude/shared/` pattern. The existing per-machine store migrates into the repo. *Central — everything else assumes this.*
2. **✅ RESOLVED (2026-06-24):** transcripts are per-repo `.jsonl` at `~/.claude/projects/<dash-encoded-cwd>/*.jsonl`. Caveats: worktrees get their own project dirs (enumerate ALL matching dirs, not just the canonical one); the store is per-machine, so historical reach on a given box is bounded (this box: ~2026-05-21 onward; pre-WSL-migration history lives in the Windows-side `~/.claude`).
3. **✅ RESOLVED (Nathan, 2026-06-24): extraction runs IN-SESSION, never on the metered API.** The loop is Claude Code itself (Max subscription) doing extract + consolidate — not a headless daemon hitting the Anthropic API — so there is no per-token metered cost. See the revised §4/§5.
4. **Dedup compute:** pure consolidation-model judgment vs Jaccard-prefilter + model. (Recommend prefilter to bound cost.)
5. **Flag-review surface:** `MEMORY_REVIEW.md` surfaced next session, a Telegraph push, and/or the consolidation commit/PR?
6. **Decay parameters:** the N-day staleness window (proposed 90) and eviction = flag-vs-archive-vs-delete.
7. **Fleet scope for Phase 1:** OverSteward sessions only first, then generalize — or all fleet repos from the start? (Recommend: OverSteward first.)
8. **Procedural-lesson promotion:** keep lessons as `feedback` memories with human promotion to CLAUDE.md, or let the loop propose CLAUDE.md edits as flagged PRs? (Recommend: human-gated.)
9. **Reconciliation scope/cadence (§13):** which of the four reconciliation passes ships first, and on what trigger (queue-empty vs a fixed nightly tick), given the operating rule is queue-triggered not clock-triggered? (Recommend: ought-vs-actual map first — cheapest, all-local — then the roadmap/intent pass, then Playwright journeys, then usage.)
10. **Digest location + format (§13a):** where the two slim agent-facing digests live and how they auto-load — generated `data/scope_digest.md` / `data/roadmap_digest.md` read at session start, vs a managed block in each repo's `CLAUDE.md`? (Recommend: generated files in `data/`, mirrored like the tool/workflow registries.)
11. **Digest cadence (§13a):** regenerate a digest only when its canonical parent (`architecture.md` / `ROADMAP.md`) changes, vs every dream cycle. (Recommend: on-parent-change — cheap and drift-free.)
12. **Roadmap intent sources + dedup (§13.4):** how to weight and reconcile the two intent feeds — conversation transcripts vs filed issues — so an idea discussed *and* filed isn't double-counted, while a conversation idea never filed still surfaces. And: does the intent pass auto-*file* an issue for un-filed intent, or only flag it for the waking session? (Recommend: flag-don't-file in Phase 1, mirroring §6 flag-don't-act.)

---

*Phase 0 deliverable. The load-bearing decisions §14-1/2/3 are **RESOLVED** (2026-06-24); §14-4 through 12 proceed on the doc's recommendations (Nathan, 2026-06-24). **Phase 1 build is cleared** and tracked as an epic on the OverSteward issue board.*

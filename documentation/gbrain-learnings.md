ABOUTME: Design record of learnings mined from garrytan/gbrain and folded into OverSteward doctrine.
ABOUTME: What was adopted, what was deferred as YAGNI, and the standing watch on gbrain as a source.

# gbrain Learnings

[garrytan/gbrain](https://github.com/garrytan/gbrain) is Garry Tan's production-grade
memory system for AI agents (hybrid search + knowledge graph, PGLite/Postgres engines,
markdown skill packs). OverSteward and gbrain are cousins: both ship **canonical
artifacts** into downstream repos that hold copies, and both run a **file-based
knowledge store**. gbrain has more miles on it and has documented traps OverSteward
will hit. This doc records what we took, what we deliberately left, and why we keep
watching.

Reviewed 2026-06-16 against gbrain HEAD at clone time.

## Why gbrain is a high-signal source

Garry Tan builds **companies, not apps**. gbrain reflects what production agent
infrastructure actually needs once it meets scale and a team — not a toy. That makes
its hard-won conventions (filing rules, contradiction posture, fail-open seams,
two-vs-three-way merge scars) unusually transferable. The expectation is that it keeps
teaching: see the watch marker below.

## Adopted

### 1. Deployment manifest & three-way drift classification (Tier 1)

gbrain's `skillpack reference --apply-clean-hunks` does a **two-way** merge (canonical
vs local) with no record of what was originally deployed, so it clobbers intentional
local edits and accidental drift alike. OverSteward's sow contract had the same shape:
canonical-vs-on-disk, overwrite on mismatch.

Fix: turn drift detection **three-way** — a recorded baseline as well as canonical-now
and the copy-now — and classify every byte-copy path as
`identical / stale / diverged / missing`. Only `diverged` needs human judgment; the rest
are deterministic. The baseline is what lets the byte-copy ratchet treaty **detect** a
violation instead of erasing its evidence.

**The baseline is canon's git history, not the `reports/manifest.json` this section
originally proposed (superseded 2026-08-28, OS#408).** The manifest was never created,
and a first run against an absent one classifies every path `missing` and deploys over
every deliberate downstream edit — the exact failure it existed to prevent. Canon's own
history needs no state to seed and no state to maintain: a copy equal to any blob the
member has ever carried is `stale`, one equal to none is `diverged`. The three-way
lesson stands; only its substrate changed.

- Design: OVERSTEWARD.md § "Drift classification from canon history"
- Operational contract: [sow-safety-gates.md](sow-safety-gates.md) § "Drift classification — from canon history"
- `sync-status` adopts the `identical / stale / diverged / missing` report vocabulary.

### 2. Deterministic, fail-open, zero-token mechanics (Tier 1)

Every gbrain hot path — auto-link, the retrieval pointer layer, the five guardrail
seams — is zero-LLM and **fails open**: "a broken guardrail never breaks an ingest."
Codified as OverSteward design principle 9. Drift detection / diffing / hashing is
cheap Python that fails open and stays silent on the happy path; Claude tokens are
spent only on genuine judgment (conflict resolution, content proposals, scoping).

### 3. Memory-integrity probe (Tier 2 — design, deferred)

gbrain's contradiction probe is the transferable *posture*, not the machinery: sample
the store, flag contradicting pairs, assign **severity**, report a **calibrated**
number (Wilson CI, not vibes), emit **paste-ready resolution commands**, and **never
auto-mutate** — "the probe produces evidence, the operator decides."

OverSteward's recall already warns that a memory "reflects what was true when written —
verify before recommending." A probe operationalizes that. Design when built:

- **Deterministic core (zero-token, build first when friction appears):** scan
  `~/.claude/projects/-home-natha-OverSteward/memory/` for (a) dangling `[[wiki-links]]`
  with no target file, (b) `MEMORY.md` index ↔ file drift (orphans / missing pointers),
  (c) memories naming a repo file / flag / function that no longer exists on disk.
- **Semantic layer (operator- or Claude-gated):** pairwise contradiction between
  memories (e.g. one feedback memory says X, a newer one says not-X). Emits suggestions
  with a supersede/merge/keep-both recommendation; never edits.
- **Trust posture:** read-only. Output is a report, never a mutation. The operator
  pastes the fix.

Deferred deliberately (YAGNI): the corpus is ~50 files today and manual review suffices.
Build the deterministic core first, the day a stale-reference bug actually bites.

### 4. Memory provenance convention (Tier 2)

gbrain's #1 production extraction error was confusing **who holds a belief** with **who
it's about** ("holder ≠ subject"), and its filing rules encode a strict
**source-precedence** (user's direct statements > compiled synthesis > external). The
transferable lesson for OverSteward memory: distinguish **Nathan-stated** (durable law,
high authority) from **Claude-inferred** (a revisable pattern). The former should not be
quietly overturned by a later inference. Captured as a `feedback` memory so it bites at
memory-write time (the harness memory instructions can't be edited directly). Also
adopted from gbrain's output rules: when a memory captures Nathan's pointed wording,
**preserve it verbatim** — the language is the insight.

## Deferred / rejected (YAGNI at estate scale)

These earn their keep at gbrain's 28K-page, multi-user scale and are pure overhead for
an 8-repo personal estate. Revisit only if the estate's shape changes.

| gbrain feature | Why not now |
|---|---|
| Takes/facts dual store, confidence weights on a 0.05 grid | Memory has 4 plain types; weights imply calibration we don't have |
| Knowledge-graph typed edges (`attended`, `works_at`, …) | `[[wiki-links]]` already give the graph we need at this scale |
| Dream-cycle consolidation (hot→cold promotion) | No hot/cold split; memories are written deliberately, not extracted per-turn |
| BullMQ "Minions" durable job queue | Dispatch runs foreground in-session by design; no crash-safe sub-agent queue needed |
| Storage tiering / cloud raw-file sidecars | No large-blob ingest |
| OAuth-scoped MCP (read/write/admin) | Single operator; no team deployment |
| Haiku voice-gate with regen + fallback | No user-facing generated prose surface to police |

## Standing watch

gbrain is a **recurring** source, not a one-time mine. Next review **~December 2026**
(≈6 months out) — Garry's building companies, and the expectation is a fresh crop of
production-agent-infrastructure insight by then. On revisit: diff gbrain HEAD against
this doc's clone-time snapshot, re-run the adopted/deferred ledger, and check whether
any "deferred" row crossed the scale threshold that would flip it to "adopt."

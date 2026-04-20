# Deferred Tasks

Queued work for future horizons. When a MASTER_TODO task completes, the next item from here promotes. Ordered by horizon and dependency.

Plan reference: `OVERSTEWARD.md` (Phase Roadmap).

---

## Horizon 2 — Regression Catalog + Scoped Governance Tooling (target 4 weeks)

### H2-1 — Regression catalog

Audit `feedback_*` memory entries. Classify which are dispatch-agent applicable. Emit:
- `shared/agent-playbooks/common-pitfalls.md` — cross-repo
- `shared/agent-playbooks/{repo}-pitfalls.md` — per-repo

Wire each subagent's briefing to reference its pitfalls file. Turns scar tissue into pre-flight checks rather than memory-only knowledge.

### H2-2 — `scripts/gather.py`

Read-only state extraction. For each context in registry, read the CLAUDE.md file, extract the managed block, compute hashes, emit JSON state snapshot. No writes.

### H2-3 — `scripts/diff.py`

Pure comparison. Takes gather state + registry expectations, emits structured change list. No writes.

### H2-4 — `/sync-status` skill

Runs gather + diff; presents drift across contexts in human-readable form. No writes. Governance's equivalent of `/project-status`.

### H2-5 — DEFER `sow.py`

Hold until a concrete sync task lands that manual sync can't absorb. Forcing-function gate on build effort.

---

## Horizon 3 — Compounding Capabilities (trigger-gated)

### H3-1 — Governance sow bundle

Build `sow.py` + `sweep.py` + `coordinator.py` together when H2-5 trigger fires.

**sow.py safety gates (design pinned in H1-3):**
- CAN write inside `<!-- [oversteward:managed] -->` blocks only
- CANNOT modify inside `<!-- [oversteward:local] -->` blocks
- CANNOT touch files where context has `skip_sow: true`
- CANNOT inject soul for contexts with `soul_in_local: true`
- Bail on dirty working tree; no stacking; dry-run default; lockfile during execution
- Branch name pattern: `oversteward/sync-YYYY-MM-DD`

**sweep.py ownership signal:** `persona-{name}.md` naming convention; hash-compare against template before proposing deletion.

**Machine-readable audit trail:** alongside human reports, emit an append-only JSONL log of every managed block change. Each entry: timestamp, context_id, action, old_hash, new_hash, synced_files.

### H3-2 — Cross-pillar integration

When governance sync detects a rule change affecting a dispatch-target repo, append a brief to that subagent's context. Closes the loop between the two pillars.

### H3-3 — Analyst persona

Build via `/create-persona` when triggered by a Stocks or OpportunityMiner use case.

### H3-4 — Self-critique audit log

Each self-critique gate result logged to `data/pipeline_history.jsonl` (same file as H1-2 metrics). Monthly review.

### H3-5 — GH Actions scheduled governance sync

Phase 3 automation from original roadmap — cron or Actions-triggered coordinator.

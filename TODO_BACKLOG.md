# Deferred Tasks

Queued work for future horizons. When a MASTER_TODO task completes, the next item from here promotes. Ordered by horizon and dependency.

Plan reference: `OVERSTEWARD.md` (Phase Roadmap).

---

## Horizon 2 — Cross-Repo Parity + Scoped Governance Tooling

### H2-1 — Cross-repo `.claude/settings.json` parity

Tracked as issue #49; scoped 2026-06-10 as read-only first (H2-3 + H2-4 + H2-5 cover the settings/hooks surface in their drift report; the write side waits for H2-6's gate).

Open thread from PR #47 (2026-05-26): each pickup repo's project-level Claude Code settings drift independently. `registry.yaml` could carry a `permissions:` block that sows deny-lists, allow-lists, and hook config to each `.claude/settings.json`. Currently the credential-hygiene rules only live at the user level (`~/.claude/settings.json`); per-project rules vary by repo. Since PRs #55–#57 the manually-synced surface also includes `.claude/hooks/guard_main_worktree.py` + `scripts/dev/new-session.sh` byte-copies in every repo.

Touchpoints:
- New registry field (`settings_sync: true` or richer block)
- `scripts/sow.py` extension to write `.claude/settings.json` per context (with diff/merge of Nathan's local rules)
- Conflict policy: managed block vs Nathan-local block (mirrors CLAUDE.md ownership markers)

### H2-2 — Regression catalog

Audit `feedback_*` memory entries (currently ~40 entries in OverSteward project memory). Classify which are pickup-relevant. Emit:
- `shared/pickup-playbooks/common-pitfalls.md` — cross-repo
- `shared/pickup-playbooks/{repo}-pitfalls.md` — per-repo

Wire each per-repo doc in `documentation/repos/*.md` to reference its pitfalls file. Turns scar tissue into pre-flight checks rather than memory-only knowledge.

Note: renamed from "agent-playbooks" to "pickup-playbooks" since `/dispatch` retirement (2026-05-01).

### H2-3 — `scripts/gather.py`

Read-only state extraction. For each context in registry, read the CLAUDE.md file, extract the managed block, compute hashes, emit JSON state snapshot. No writes.

### H2-4 — `scripts/diff.py`

Pure comparison. Takes gather state + registry expectations, emits structured change list. No writes.

### H2-5 — `/sync-status` skill

Runs gather + diff; presents drift across contexts in human-readable form. No writes. Governance's equivalent of `/project-status`.

### H2-6 — DEFER `sow.py` — **TRIGGER FIRED 2026-08-28 (OS#408)**

Hold until a concrete sync task lands that manual sync can't absorb. Forcing-function gate on build effort. H2-1 (cross-repo settings parity) is the most likely trigger.

**Fired.** The trigger was not H2-1 but the canonical family itself: on 2026-08-28 it had drifted in **all 8 repos with local checkouts — 34 drifted/missing rows**, untouched since June, because a manual sync is too expensive to run casually. The sync that did happen (OS#401/#402) took ~3 hours, needed a hand-built script in the session scratchpad, stalled on consumer-side gates in five of seven first attempts, and required every drift's *direction* to be classified by hand. That is "cannot absorb" in practice: the work is not done rather than done manually. Built in OS#408, scoped to the byte-copy family only.

---

## Horizon 3 — Compounding Capabilities (trigger-gated)

### H3-1 — Governance sow bundle — **PARTIALLY BUILT 2026-08-28 (OS#408)**

Build `sow.py` + `sweep.py` + `coordinator.py` together when H2-6 trigger fires.

**Built:** `sow.py`, scoped to the canonical `shared/scripts/dev/` byte-copy family — three-way classification from canon's git history, gates G1–G4/G7/G8 plus a new G9 (the target repo's own `ruff` must accept the copied bytes), a throwaway worktree off `origin/<branch>`, one PR per context, never auto-merged, and the JSONL audit trail below. `--deploy-shared` mirrors `shared/` to both Claude homes.

**Still deferred:** the managed-block / soul / persona / `settings.json` write surface (the marker-boundary gates below), `sweep.py`, and `coordinator.py`. No demand for them appeared in the six months the contract sat pinned; they are re-triggered the same way H2-6 was — by a concrete task manual work cannot absorb.

**sow.py safety gates (design pinned in H1-3):**
- CAN write inside `<!-- [oversteward:managed] -->` blocks only
- CANNOT modify inside `<!-- [oversteward:local] -->` blocks
- CANNOT touch files where context has `skip_sow: true`
- CANNOT inject soul for contexts with `soul_in_local: true`
- Bail on dirty working tree; no stacking; dry-run default; lockfile during execution
- Branch name pattern: `oversteward/sync-YYYY-MM-DD`
- **Dual-target deploy:** writes to both `C:\Users\natha\.claude\shared\` (Windows) and `/home/natha/.claude/shared/` (WSL2). See OVERSTEWARD.md § Dual-target deploy.

**sweep.py ownership signal:** `persona-{name}.md` naming convention; hash-compare against template before proposing deletion.

**Machine-readable audit trail:** alongside human reports, emit an append-only JSONL log of every managed block change. Each entry: timestamp, context_id, action, old_hash, new_hash, synced_files.

### H3-2 — Cross-pillar integration

When governance sync detects a rule change affecting a pickup-target repo, append a brief to that repo's `documentation/repos/*.md` pickup context. Closes the loop between the two pillars.

### H3-3 — Analyst persona

Build via `/create-persona` when triggered by a Stocks or OpportunityMiner use case.

### H3-4 — Self-critique audit log

Each self-critique gate result logged to `data/pipeline_history.jsonl` (same file as H1-2 metrics). Monthly review. Definition of "self-critique fire rate" still undecided.

### H3-5 — GH Actions scheduled governance sync

Phase 3 automation from original roadmap — cron or Actions-triggered coordinator.

### H3-6 — Full issue → merged-PR cycle time (excluding `needs-input` stalls)

Currently `/project-status` reports PR turnaround + merge rate + `needs-input` age. Full cycle time needs timeline-event fetch (label-change events to subtract `needs-input` intervals). Worth doing once enough data accumulates.

---

## Ideas (not yet promoted to backlog)

See [IDEA_STORE.md](IDEA_STORE.md) for ideas reviewed quarterly. Promote to backlog when a trigger lands.

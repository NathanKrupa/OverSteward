# Deferred Tasks

Queued work for future sessions. When a MASTER_TODO task completes, the next item
from here promotes to MASTER_TODO. Ordered by priority/dependency.

---

## Phase 2: Script Implementations

### sow.py — Scope Enforcement

Sow operations should have explicit allow/deny rules:
- CAN write content inside `<!-- [oversteward:managed] -->` blocks
- CANNOT modify anything inside `<!-- [oversteward:local] -->` blocks
- CANNOT create or delete files outside managed blocks
- Must abort with error if local block would be affected

Reference: Alfred's `vault/scope.py` pattern (per-worker operation permissions).

### Sync Reports — Machine-Readable Audit Trail

In addition to the human-readable markdown reports, emit an append-only JSONL log of every managed block change across all repos. Each entry: timestamp, context_id, action (created/updated/unchanged), old_hash, new_hash, synced_files.

Enables: diffing between sync runs, detecting drift, rollback verification.

Reference: Alfred's `vault/mutation_log.py` pattern.

### Script Stubs to Implement

- **coordinator.py** — orchestrates gather → diff → sow cycle
- **gather.py** — reads all managed repo CLAUDE.md files, extracts managed blocks
- **diff.py** — compares gathered state against registry expectations
- **sow.py** — writes managed blocks to target repos (with scope enforcement above)
- **sweep.py** — cleans up orphaned managed markers from deregistered contexts

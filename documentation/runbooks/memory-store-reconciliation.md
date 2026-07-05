# Runbook — reconcile the split-brain memory store (OS#195)

**Operator-run, one-time.** Unifies the two divergent memory directories onto the
single git-backed steward store and symlinks the harness path into it. Requires
Nathan's approval before `--apply` — it moves the live harness memory dir.

## Background

Two physical memory stores drifted apart:

| | Path | Loaded by harness? | Written by |
|---|---|---|---|
| **HARNESS** | `/home/natha/.claude/projects/-home-natha-OverSteward/memory/` | yes | Claude, manually per session |
| **STEWARD** | `/home/natha/steward-memory/memory/` (git repo) | no | the dream cycle |

Consequence: dream-consolidated facts land where no session reads them, and manual
writes sit where the dream never sees them. The fix keeps STEWARD as the single
canonical git-backed store and makes the harness path a **symlink into it**, so
one physical store serves all three roles. No `DEFAULT_STORE_PATH` change.

## What the tool does (`--apply`)

1. **Backs up both directories** to a timestamped tar under the backup root
   (default `/home/natha/steward-memory/reconcile-backups/`) — `harness/` +
   `steward/` arcnames — before any mutation.
2. **Unions** the harness-only facts INTO steward (copy, never delete).
3. For **diverged** files (same name, different content): keeps the **HARNESS
   (curated) version canonical** in steward and writes steward's prior version
   alongside as `<stem>.steward-variant.md`. Nothing is lost; every diverged file
   is listed in the report for human review.
4. **Regenerates `MEMORY.md`** in steward from the unified fact set (reuses the
   dream engine's `MemoryStore.regenerate_index`).
5. **Establishes the symlink** harness-path → `steward-memory/memory` (the
   original harness dir is captured in the backup tar first). Idempotent: a
   re-run through the symlink is a clean no-op.

## Procedure

### 1. Dry run (default — mutates nothing)

```bash
cd /home/natha/OverSteward
.venv/bin/python scripts/dream/reconcile_stores.py
```

Read the printed report: the 4-way divergence counts, the harness-only facts that
will be carried in, and the full list of diverged files (each with its
`.steward-variant.md` sidecar name). Confirm the counts match expectation
(~30 harness-only, ~36 diverged as measured 2026-07-05).

### 2. Apply (operator, with Nathan's approval)

```bash
cd /home/natha/OverSteward
.venv/bin/python scripts/dream/reconcile_stores.py --apply
```

The report prints `APPLIED` and the backup tar path. Then commit the store:

```bash
git -C /home/natha/steward-memory add -A
git -C /home/natha/steward-memory commit -m "reconcile: unify split-brain memory store (OS#195)"
```

### 3. Verify

- `ls -l /home/natha/.claude/projects/-home-natha-OverSteward/memory` shows a
  symlink → `/home/natha/steward-memory/memory`.
- Spot-check a recent manual fact survived (e.g.
  `feedback_operator_orchestrates_not_implements.md`) under the steward dir.
- Each diverged file has a `<stem>.steward-variant.md` sidecar.
- Next session: the harness loads the unified `MEMORY.md`.

### 4. Review the diverged variants

Walk the report's diverged list. For each, compare the canonical file against its
`.steward-variant.md` sidecar and either delete the sidecar (harness version
wins, confirmed) or merge steward's content back in. This is manual curation, not
automated.

## Rollback

- **Remove the symlink and restore both dirs from the backup tar:**

  ```bash
  rm /home/natha/.claude/projects/-home-natha-OverSteward/memory   # the symlink
  mkdir -p /tmp/mem-restore && tar -xzf \
    /home/natha/steward-memory/reconcile-backups/memory-reconcile-<STAMP>.tar.gz \
    -C /tmp/mem-restore
  cp -a /tmp/mem-restore/harness \
    /home/natha/.claude/projects/-home-natha-OverSteward/memory
  ```

- The steward store's union/variant writes are captured in the git commit; revert
  it (`git -C /home/natha/steward-memory revert <sha>`) or restore
  `/tmp/mem-restore/steward` over `/home/natha/steward-memory/memory`.

## Out of scope (follow-up)

Trimming the auto-loaded `MEMORY.md` index to a lean "hot subset" — the ~334
carried-in dream appends will make the loaded index larger. Tracked separately;
see the follow-up issue referencing OS#195.

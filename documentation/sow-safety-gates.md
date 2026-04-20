ABOUTME: Operational contract for scripts/sow.py — every pre-condition, invariant, post-condition the writer must honor.
ABOUTME: sow is the riskiest operation in the OverSteward; this doc pins the design before implementation.

# sow.py Safety Gates

`scripts/sow.py` is the writer side of the governance pillar. It applies approved changes to managed CLAUDE.md blocks, deploys persona skills, and opens sync PRs. It is the riskiest script in the project: a bug can silently overwrite Nathan's hand-crafted instructions, erase persona variants, or produce an unreviewable sync PR.

This document is the **design contract** sow must honor. Implementation has not begun (stubs live in the repo). Before the first real sow run, every gate below must be in place and unit-tested.

## Core principles

1. **Propose, don't impose.** Every change goes through a PR. sow never pushes directly to a context's default branch.
2. **Boundary is sacred.** The `[oversteward:managed]` / `[oversteward:managed:end]` marker pair is the *only* region sow may write. The `[oversteward:local]` block is read-only from sow's perspective.
3. **Fail loud.** Any precondition failure aborts with a clear error to the report. Silent repair is never acceptable.
4. **Dry-run first.** Default invocation produces a report with the diff; writing requires explicit `--apply`.
5. **One run at a time.** Lockfile protects against concurrent sow invocations on the same machine.

## Pre-conditions (enforced before any write)

| Gate | Check | Failure action |
|---|---|---|
| **G1 — clean tree** | Target repo has no uncommitted or untracked changes on default branch | Abort; report "dirty tree on `<repo>`" |
| **G2 — no stacked PR** | No open PR on target repo whose branch matches `oversteward/sync-*` | Abort; report "prior sync PR open on `<repo>`" |
| **G3 — context registered** | Target id appears in `registry.yaml` | Abort; report "unknown context id" |
| **G4 — not skip_sow** | Target context does not carry `skip_sow: true` | Refuse; report "context opts out of sow" |
| **G5 — markers present** | Target CLAUDE.md contains both `[oversteward:managed]` and `[oversteward:managed:end]` markers on separate lines | Abort; report "markers missing — run bootstrap first" |
| **G6 — local markers present** | Target CLAUDE.md contains `[oversteward:local]` and `[oversteward:local:end]` markers OR the file has no local block at all | Abort if local markers are malformed (one present, one missing) |
| **G7 — lockfile** | `.sow.lock` in oversteward repo root can be acquired atomically | Abort; report "another sow run is in progress" |
| **G8 — explicit apply** | `--apply` flag passed (implicit `--report-only` otherwise) | Produce dry-run report only; no writes |

A sow invocation runs G1–G8 as a batch **per target context**. A single failed gate on one context does not abort the entire run; it abortst that context and continues, collecting failures into the final report.

## Per-context content contracts

### Managed-block contract

When rewriting the managed block, sow MUST:

- Preserve the opening and closing marker lines byte-for-byte.
- Replace every line between them with the newly composed content.
- Composed content order: soul import (if any), personas_always_on imports (one per line), trailing newline.
- Update the `synced: YYYY-MM-DD` attribute inside the opening marker to today's UTC date.

Sow MUST NOT:

- Write anything outside the marker pair.
- Emit a soul import when `soul_in_local: true` on the target context (see [registry-schema.md](registry-schema.md) for precise semantics).
- Include personas from `personas_available` in the managed block (those deploy as skill files, not @file imports).

### Local-block contract

- Read-only. sow MUST NOT open the file with write intent if the only planned change is inside the local block.
- If the local block is missing entirely, that is permitted — the context has nothing local-specific. Not an error.

### Skill-file deployment

For `skills_always_on` listed on the target context:

- Source: `shared/skills/<name>.md`
- Destination: `<context_repo>/<skills_path>/<name>.md`
- Deploy = copy + git add. If destination matches source by hash, skip (no-op).

Sow MUST NOT delete skill files that were previously deployed but are no longer in `skills_always_on` — that is sweep's job. Sow is additive.

### Persona skill-file deployment

For `personas_available` listed on the target context:

- Source: `shared/personas/<name>.md`
- Destination: `<context_repo>/<skills_path>/persona-<name>.md` (the `persona-` prefix is the ownership signal for sweep)
- Same hash-short-circuit rule as skills.

## Branch and PR contract

| Step | Behaviour |
|---|---|
| Branch creation | `git checkout -b oversteward/sync-YYYY-MM-DD` on target repo from its default branch |
| Commit message | `oversteward sync: <summary of what changed>` with Co-Authored-By trailer |
| Push | `git push -u origin oversteward/sync-YYYY-MM-DD` — never to the default branch |
| PR | Opened via `gh pr create` with the dry-run report as the body |
| Auto-merge | **Never.** Nathan reviews and merges manually. |

## Post-conditions (verified after each target)

| Check | Action if failed |
|---|---|
| Local working tree clean after sow's writes are committed | Abort remaining targets; flag for manual cleanup |
| PR URL captured in final report | Retry PR creation once; then abort |
| Lockfile released | If release fails, next run's G7 will detect and require manual intervention |

## Failure modes the design rejects

The following "convenient" behaviours are explicitly forbidden because past incidents or adjacent projects have taught us they produce drift or data loss:

- **Silent marker repair** — if markers are malformed, sow aborts. Repair is a conscious, bootstrap-time operation, never inline.
- **`git commit --no-verify`** — pre-commit hooks (linters, secret scanners) run. sow must fix issues, never bypass.
- **Merge conflict auto-resolution** — if branch creation or checkout produces conflicts, sow aborts. The operator resolves.
- **Multi-context single PR** — one PR per target context. Batching PRs hides per-context review.
- **Retrying on auth failure** — one attempt per target. Auth errors abort that target with a clear diagnostic.

## Testing requirements (before first real run)

Each gate (G1–G8) must have a unit test covering (a) the pass path and (b) each failure path.

Beyond gates, integration tests must cover:

- Round-trip: given a context with a known managed block, sow produces an identical block when nothing in the registry changed (no-op preserves bytes).
- `soul_in_local: true`: managed block never contains the soul @file import.
- `skip_sow: true`: context is skipped, no git activity on that repo.
- Lockfile: two concurrent invocations — the second aborts cleanly.

These tests belong in `tests/test_sow.py` when implementation begins.

## Known risks (restated)

1. **Private-repo branch protection.** On GitHub Free tier, private repos cannot enforce branch protection. sow discipline alone prevents direct-to-main pushes. A buggy sow in apply mode could still land on a protected-in-intent branch. Mitigation: hard-coded refusal to push to any branch whose name matches the registry's `branch:` field.
2. **`soul_in_local` drift.** If Nathan later edits the local-block soul variant, sow has no drift detection — the managed block stays in sync while the local block silently diverges. Drift detection is a separate tool (planned) and is explicitly out of sow's scope.
3. **Concurrent humans.** Nathan running `git commit` on a context while sow holds the repo open can race. sow uses short-lived git operations to minimize window; true concurrency safety requires repo-level locking (not implemented).

## Related

- `OVERSTEWARD.md` — project overview; sync workflow description
- [registry-schema.md](registry-schema.md) — schema that sow reads as input
- `scripts/registry.py` — canonical registry reader
- `scripts/sow.py` — target of this contract; currently stubbed

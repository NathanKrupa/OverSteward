ABOUTME: Operational contract for scripts/sow.py — every pre-condition, invariant, post-condition the writer honors.
ABOUTME: sow is the riskiest operation in the OverSteward; this doc is the contract the implementation is tested against.

# sow.py Safety Gates

`scripts/sow.py` is the writer side of the governance pillar. It is the riskiest
script in the project: a bug can silently overwrite a hand-crafted downstream
edit, erase evidence of a ratchet-treaty breach, or push to a repo's trunk.

## Scope (narrowed, OS#408)

**sow deploys the canonical `shared/scripts/dev/` byte-copy family, and nothing
else.** One PR per target repo, proposing the members that are safe to write.

Managed-block rewriting, soul and persona deployment, and `.claude/settings.json`
sync are **deferred, not built** — six months after the contract was pinned no
demand for them has appeared, while the family drifted in all 8 repos with local
checkouts. The gate vocabulary below keeps room for them; the sections that
described them are gone rather than left standing as a promise the code does not
keep. `sweep.py` and `coordinator.py` remain unbuilt.

## Core principles

1. **Propose, don't impose.** Every change goes through a PR. sow never pushes
   to a context's registry branch, and never merges — it prints the
   `gh pr merge` line and stops.
2. **Fail loud, per context.** Any pre-condition failure aborts *that context*
   with a clear line in the report; the run continues with the rest. Silent
   repair is never acceptable.
3. **Dry-run first.** The default invocation measures and writes nothing.
   Writing requires explicit `--apply`.
4. **One run at a time.** `.sow.lock` in the OverSteward repo root, created
   atomically (`O_EXCL`), protects against concurrent invocations on a machine.
5. **Never a bypass.** `--no-verify`, `--force`, `--admin` and `git add -A`
   appear nowhere in sow. Staging is by explicit path; a pre-commit hook that
   objects is a finding, not an obstacle.

## Drift classification — from canon's git history

The deploy decision is **three-way**, never "overwrite on hash mismatch". A
two-way comparison cannot tell a copy that is merely behind from one that was
deliberately edited downstream — they have identical hashes and opposite correct
actions. gbrain hit exactly this with `skillpack reference --apply-clean-hunks`.

The baseline is **canon's own git history**, not a recorded manifest:

```bash
git log --format=%H -- shared/scripts/dev/<member>      # every commit that touched it
git rev-parse <commit>:shared/scripts/dev/<member>      # the blob id at that commit
```

A blob id is a content address git assigns identically in every repository, so
canon's history and a pickup repo's `origin` ref compare directly without either
side handing over its bytes. sow reads the target's copy the same way
(`git rev-parse origin/<branch>:<relpath>`) — never its working tree, which runs
dozens-to-hundreds of commits stale and produced both false drift and false
parity when `/sync-status` hashed it (OS#242).

| State | Condition | Meaning | sow action |
|---|---|---|---|
| `identical` | copy == canonical blob | Up to date | No-op |
| `stale` | copy == **some** historical canon blob | Deployed from canon, left behind | Deploy |
| `diverged` | copy matches **no** canon blob | Edited downstream | **Flag with the diff. Never write.** |
| `missing` | absent, and the repo's `CLAUDE.md` names the file | Broken instruction | Deploy |
| `absent-not-adopted` | absent, and nothing references it | Not adopted here | Leave alone |

Two consequences are load-bearing:

- **`diverged` is never overwritten.** It is either a deliberate downstream
  hotfix to promote upstream, or the evidence of a byte-copy ratchet-treaty
  breach. Both are operator decisions; erasing the file erases the decision.
  Measured on 2026-08-28: 26 stale, 6 diverged — and every diverged one was
  real (two deliberate `.gitleaks.toml` allowlists, a consumer-formatter
  artefact, and two OverSteward-local tests canon had to be promoted *from*).
- **`absent` is not adopted.** sow is additive within a repo but never decides
  that a repo should start carrying a member. Adoption is a registry decision.

**Why not `reports/manifest.json`.** The pinned 2026-02 contract recorded a
deployment baseline per file. That manifest was never created. A first run
against an absent manifest classifies every path `missing` and deploys over
every deliberate downstream edit — precisely the failure the manifest existed to
prevent. Canon history is a better baseline with no state to seed, no state to
maintain, and no first-run hole.

## Pre-conditions (enforced before any write)

| Gate | Check | Failure action |
|---|---|---|
| **G1 — origin readable** | `origin/<registry branch>` can be read in the target checkout | `unreadable`; nothing is measured for that context (exit 2) |
| **G2 — no stacked PR** | No open PR on the target whose branch matches `oversteward/sync-*` | Abort that context: "prior sync PR open". A `gh` that cannot answer is **also** a block — fails closed, never "no PR found" |
| **G3 — context registered** | The id appears in `registry.yaml` | `unreadable`: "unknown context id" (exit 2) |
| **G4 — not skip_sow** | The context does not carry `skip_sow: true` | Refuse; report "skipped by design" |
| **G7 — lockfile** | `.sow.lock` in the OverSteward repo root acquired atomically (`O_EXCL`) | Abort the run: "another sow run is in progress" (exit 2) |
| **G8 — explicit apply** | `--apply` passed | Dry-run report only; no writes anywhere |
| **G9 — consumer format** | The **target repo's own** `ruff format --check --force-exclude` and `ruff check --force-exclude`, run inside the worktree on the copied `.py` files, raise no objection | Abort that context and print the `extend-exclude` entries plus `force-exclude = true` that repo needs |

G1–G4 and G8 are decided in the pure planner and are reportable without touching
anything. G7 is acquired by the CLI before the plan is built. G9 can only run
once the bytes are in the worktree, so it runs there — before the commit.

**G1 replaces the pinned contract's clean-tree check.** sow no longer checks out
a branch in the resident tree, so cleanliness is structural: the worktree is
created from `origin/<branch>` and destroyed after the push. What can still fail
is the *read*, and that is what G1 measures.

**G9 is new (OS#408), and it is not optional.** A canonical member landing in a
repo that never took the OS#241 formatter exclusion is rewritten by that repo's
own formatter in the deploy commit itself — the copy arrives already drifted and
the family audit flags it from the first hash check. Five of seven sync attempts
on 2026-08-28 stalled on exactly this. sow **never edits a consumer's
`pyproject.toml`**; it names what that repo's own PR owes and aborts.

**G5 / G6 (managed-block markers) are unallocated** while managed-block writing
is out of scope. The numbers are reserved rather than reused, so a future
implementation and the historical record stay legible.

## Deployment contract

For every member of canonical `shared/scripts/dev/`:

- **Source:** `shared/scripts/dev/<member>`
- **Destination:** derived from the name, never a per-member table —
  a leading `.` deploys to the repo root, a registered hook to
  `.claude/hooks/`, `test_*.py` to `tests/dev/`, everything else to
  `scripts/dev/`. `src/oversteward/dev_family.py` encodes exactly this.
- **Deploy decision:** the classification table above. Only `stale` and
  `missing` are ever written.
- **Byte-identity is asserted**, not assumed: every copy is compared against its
  source after writing, and a mismatch aborts the context.

sow MUST NOT delete a member that is no longer canonical — that is sweep's job.
sow is additive.

## Branch and PR contract

| Step | Behaviour |
|---|---|
| Fetch | `git fetch origin <branch>` in the target checkout. Refs only |
| Worktree | `git worktree add -B oversteward/sync-YYYY-MM-DD <tmpdir> origin/<branch>` — a throwaway worktree, **never** a branch checkout in the resident tree |
| Copy | Byte-copy each deployable member; compare the written bytes against the source |
| Stage | `git add -- <explicit paths>`. Never `git add -A` |
| Commit | `oversteward sync: N canonical family member(s) (<date>)`, with the per-context report as the message body and a `Co-Authored-By` trailer. Hooks run |
| Verify (opt-in) | With `--verify`: symlink the target's `.venv` into the worktree and run its `make verify`, redirected to a file under `reports/sow/`. The file is read; a failure aborts the context and names the log. Never `\| tail` |
| Push | `push_sync_branch()` — refuses any branch not matching `oversteward/sync-*`, and refuses the registry `branch:` outright |
| PR | `gh pr create --base <registry branch> --body-file <report>` |
| Teardown | `git worktree remove` then `git worktree prune`; the temp holder is removed |
| Auto-merge | **Never.** sow prints the `gh pr merge` line; Nathan reviews and merges |

**Why a worktree.** The pinned contract said `git checkout -b` on the target
repo. That predates the session-worktree discipline: `guard_main_worktree.py`
now refuses that exact command in a primary worktree, and it would yank the
branch out from under whatever the operator has open. The worktree is cut from
`origin`, so it also satisfies the old G1 structurally.

**`--verify` is opt-in** because three repos (AG, GS, exchequer) gate push on a
`.verify-marker` while the rest have no `make verify` at all. Without the flag,
a pre-push refusal aborts that context with the hook's own message — sow never
answers a hook by bypassing it.

## Audit trail and exit codes

Every applied run appends one JSON line per context to
`reports/sow/YYYY-MM-DD.jsonl`: `timestamp`, `context_id`, `action`, `members`,
the old and new blob id per member, and `pr_url` or the abort `reason`. Dates and
timestamps come from `datetime.now(tz=UTC)`.

Exit codes carry meaning and must not be collapsed:

| Code | Meaning |
|---|---|
| **0** | A measured answer — a plan was printed, or an apply ran. "Nothing to do" is 0 **and says so in words**, naming the count of members it checked |
| **1** | A write step sow attempted failed (a G9 objection, a failed commit / verify / push / PR) |
| **2** | It could not look — no registry, no canonical family, the lock held, an unreadable origin, an unknown context id |

An aborted write outranks an unreadable context, because the operator asked for
a write and did not get one; the report names both either way. A run with any
unreadable context prints `NOT MEASURED` rather than "nothing to do" — "I found
nothing" and "I could not look" never print the same.

## Failure modes the design rejects

- **Silent overwrite of a diverged copy** — aborts that path and flags the diff.
  A two-way "canonical wins" overwrite would erase a deliberate downstream edit
  and the evidence of a ratchet-treaty breach (gbrain's `--apply-clean-hunks`).
- **`git commit --no-verify`** — pre-commit hooks run. sow fixes, never bypasses.
- **Deploy-then-exclude** — a canonical member must not land in a repo whose
  formatter would rewrite it (G9). The exclusion is that repo's PR, not sow's.
- **Merge conflict auto-resolution** — the worktree is cut from `origin`, so
  there is nothing to conflict with; any git refusal aborts that context.
- **Multi-context single PR** — one PR per target context. Batching hides
  per-context review.
- **Retrying on auth failure** — one attempt per target, aborting with the
  diagnostic.
- **Auto-merge** — never. Several targets disallow it anyway.

## Testing requirements

Every gate has a pass test and a failure test with injected fakes — no network,
no `gh`, and no git at all for the gate and classification tests. G7 is covered
by two concurrent holders. Beyond gates, `tests/test_sow.py` covers:

- Each classification (`identical`, `stale` against an older canon blob,
  `diverged`, `missing`, `absent-not-adopted`), each seen red first.
- End-to-end on temp git repos: a canon repo with two committed generations of a
  member, and a pickup repo with a real bare `origin`. `--apply` produces one
  commit on `oversteward/sync-<date>` carrying byte-identical copies, leaves the
  diverged member untouched, writes one audit line, and **does not move the
  fixture's default branch**.
- A dry run writes nothing at all — no branch, no PR, no audit file.
- sow passes no bypass flag: no `--no-verify`, `-n`, `--force`, or `-A` reaches
  any git invocation.
- `--deploy-shared` skips `inbox.md` and `__pycache__`, never deletes a
  target-only file, and reports an absent home as unreachable rather than
  creating it.

## Known risks (restated)

1. **Private-repo branch protection.** On GitHub Free, private repos cannot
   enforce branch protection. `push_sync_branch()`'s hard refusal is the whole
   protection the target's trunk has against a buggy sow — which is why it is a
   raise, not a log line, and has both a pass and a fail test.
2. **Concurrent humans.** Nathan committing in a target repo while sow holds a
   worktree open can race. sow's git operations are short-lived and confined to
   the worktree; true repo-level locking is not implemented.
3. **Blob-history horizon.** A copy deployed from a canon commit that was later
   rewritten out of history reads as `diverged`. That is the safe direction —
   it flags rather than overwrites — but it will occasionally ask the operator
   about a file nobody edited.

## Related

- `OVERSTEWARD.md` — § Sow Safety Gates, § Drift classification from canon history
- [registry-schema.md](registry-schema.md) — `skip_sow`, `branch`, `local_path`
- `src/oversteward/dev_family.py` — the family and its deploy-path derivation
- `scripts/diff.py` — the read-only audit sow's classification extends

---
session_date: 2026-05-27
status: complete — 6-recommendation credential-hygiene + CLI-discipline rollout merged across all 5 WSL repos
context: Conversation started as a review of the 2026-05-26 GS Neon credential leak and the feedback memory Nathan wrote in response. Expanded into deep research on cross-repo CLI discipline ("how do we make session agents reach for the right tool consistently without a thousand questions"). Produced a 6-layer plan, implemented all 6 layers, opened 5 PRs, merged all 5.
branch_at_close: feat/trajectory-template (PR #46 still open — pre-existing, untouched)
---

## Where we left off

A single long session covering review → deep research → implementation → merge. Six recommendations crossed the bar; all six are now live in user-level config and committed-to-merged across all five WSL repos (AG, GS, Fiscus, gaudi, OverSteward).

The session started from the 2026-05-26 GS credential leak: a prior session had run `set -a && source .env && set +a && python -c "import psycopg; ..."` to count rows; bash interpreted the `&` in `&channel_binding=require` as job-control separator, and `[N] Done KEY=postgresql://USER:PASS@HOST/...` printed to stderr — into the transcript. Five Neon connection strings leaked. Nathan rotated them and wrote a feedback memory.

The review conversation evolved into recognizing that the memory note prevents *the same agent making the same mistake in the same repo on the next session* but the failure mode is structural, universal, and best fixed at the harness layer. Six layers proposed (initial answer was framed around dispatch agents; Nathan corrected mid-conversation: dispatch is dead, all work is in-session, re-map to user-level CLAUDE.md + user-level settings.json + memory + hooks). Then "fulfill 1-6 across all WSL projects." Then "also offer redirection on prohibited tool calls." Then "block + redirect — you tend to squeeze through loopholes." Then "merge all of those items."

All shipped.

## What was built (six layers)

### 1. User-level deny-list in `~/.claude/settings.json`

Generalized 19 deny patterns covering: `source .env*`, `. .env*`, `set -a*`, `*DATABASE_URL*`, `*_DATABASE_URL=*`, `psql:*`, `*psql postgresql:*`, `python -c *psycopg*` (and Windows/uv/python3 variants), `bash -c *source*.env*`, `bash -c *psycopg*`, `sh -c *source*.env*`, `sh -c *psycopg*`. Backstop deny, applies to every repo automatically.

### 2. Shared credential-hygiene reference

Canonical: `OverSteward/shared/references/credential-hygiene.md`. Deployed: `~/.claude/shared/references/credential-hygiene.md`. Project-agnostic, names the leak mechanism, names the registry → service → CLI escalation ladder, names the `load_dotenv()` in-process fallback.

### 3. User-level CLAUDE.md rule

Added one paragraph under `~/.claude/CLAUDE.md` Compute Efficiency → Shell, next to the existing conda-newline rule. Points to the shared reference. Loads in every session.

### 4. Tool registry backfill (Fiscus + gaudi + OverSteward)

Ported `scripts/tools/generate_tool_registry.py` (universal — `PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent` so it works in any repo). Ran it in each. Added a "Tool Registry" section to each CLAUDE.md pointing at the new file.

| Repo | Tools discovered |
|---|---|
| OverSteward | 8 (regenerated from stale state) |
| Fiscus | 4 (1 console script + 3 in scripts/) |
| gaudi | 3 (`gaudi`, `gaudi-fixture-coverage`, 1 script) |

GS and AG already had registries; left alone.

### 5. Scratch CLI in GS and AG (the paved road)

- **GS:** `src/grantspider/cli/db.py` — `grantspider db scratch --sql "..."`. Uses `build_neon_store()` (pydantic-settings). SQLAlchemy `text()` execution; transaction context manager.
- **AG:** `apps/ops/management/commands/db_scratch.py` — `python manage.py db_scratch --sql "..."`. Uses `django.db.connections[using]`. Honors DATABASES routing via `--using`.

Both: SELECT-only via mutation-keyword regex guard, row-cap default 50 (`--limit 0` lifts), three output formats (table/json/csv), full audit log via project logger.

Fiscus uses duckdb (file-based, no network credential surface) — no scratch CLI needed. gaudi has no DB. OverSteward has no DB.

### 6. Block + redirect PreToolUse hook

`~/.claude/hooks/check_db_access.py` (registered in `~/.claude/settings.json` under `hooks.PreToolUse` with `matcher: Bash`). On every Bash call: if the command matches `_SOURCE_ENV`, `_SET_A`, `_PSYCOPG_INLINE`, `_BASH_C_PSYCOPG`, `_PSQL_DIRECT`, `_BASH_C_SOURCE`, or `_DATABASE_URL_REF` + read-keyword, the hook writes a structured "BLOCKED — credential-hygiene violation / Reason: X / What to do instead: ▶ ..." message to stderr and exits 2. The agent reads the redirect and pivots.

Whitelisted: `git commit|log|diff|show|tag|notes|grep|rebase|cherry-pick|revert|blame|reflog` and `gh pr|issue|release|gist create|edit|comment|view|list|merge|close|reopen|ready` — these accept text payloads (commit messages, PR bodies) that legitimately quote the rule patterns and must pass through.

Per-repo redirect targets: when cwd resolves to a known repo, the redirect names the correct scratch CLI (GS → `grantspider db scratch ...`, AG → `python manage.py db_scratch ...`).

## PRs merged

| Repo | PR | Title | Notes |
|---|---|---|---|
| OverSteward | [#47](https://github.com/NathanKrupa/OverSteward/pull/47) | feat(credential-hygiene): shared reference + tool registry rollout | Includes trajectory note `documentation/trajectories/2026-05-26-PR47.md` |
| grantspider | [#1021](https://github.com/NathanKrupa/grantspider/pull/1021) | feat(cli): db scratch — safe ad-hoc SELECT via settings factory | Targeted staging, rebase-merged |
| aigranthelper | [#700](https://github.com/NathanKrupa/aigranthelper/pull/700) | feat(ops): db_scratch management command — safe ad-hoc SELECT | Targeted staging, rebase-merged. Includes a follow-up refactor commit extracting `_emit_*` helpers to keep SMELL-003 ratchet flat. Trajectory note `documentation/trajectories/2026-05-26-PR700.md` |
| Fiscus | [#48](https://github.com/NathanKrupa/Fiscus/pull/48) | feat(tooling): port tool registry generator + initial registry | Trajectory note `documentation/trajectories/2026-05-26-PR48.md` |
| gaudi | [#224](https://github.com/NathanKrupa/gaudi/pull/224) | feat(tooling): port tool registry generator + initial registry | Auto-merge not allowed on repo; merged manually |

## Gotchas surfaced during the session

- **Hook fires on substring matches inside the outer Bash command, including its own description.** First commit attempt blocked because the commit message body contained the literal phrase "and source .env" describing the rule. Added the git/gh whitelist. Worth watching for other false positives — the regex is in `~/.claude/hooks/check_db_access.py` and is documented inline.
- **Staging-branch merge discipline (GS + AG).** Both repos have `required_linear_history: true` on their staging branch, which forbids merge commits. `gh pr merge --auto --merge` returns "Merge commits are not allowed." Correct flag: `--auto --rebase`.
- **Squash-disable on GS** (Nathan's prior fix from 2026-05-26). `gh api repos/NathanKrupa/grantspider --jq .allow_squash_merge` is `false`. Don't `--squash`. Rebase for staging-target, merge-commit for master-target. Re-evaluate next Tuesday per prior SESSION_STATE.
- **Auto-merge disabled on gaudi.** Manual `gh pr merge 224 --merge --delete-branch` worked. If gaudi acquires more PR throughput, enable auto-merge.
- **AG file got swept mid-session.** After the OS PR landed, the AG worktree was on a different branch than where I'd written `db_scratch.py`; the file vanished. Recreated from in-context memory — same content. Lesson logged in the AG trajectory note: when working across multiple repos in-session, commit each repo's changes on its own branch in the same step rather than leaving uncommitted work across handoffs.
- **`uv.lock` is universally untracked on Fiscus / gaudi / OverSteward.** Not part of any of these PRs — Nathan's pre-existing state, presumably an unfinished decision about whether to commit lock files.

## What's now structurally true across the WSL estate

- Every repo has a `data/tool_registry.md` (or doesn't need one — covered by the user-level rule).
- Every session-Claude sees the credential-hygiene reference in context (via `@~/.claude/shared/references/credential-hygiene.md` link in `~/.claude/CLAUDE.md`).
- Every Bash call across every session goes through the PreToolUse hook before the deny-list. Block + redirect, not silent deny.
- GS and AG have scratch CLIs that the hook redirects to.
- Fiscus / gaudi / OverSteward don't need scratch CLIs (no network DB).

## Open threads

- **OverSteward feature: manage `.claude/settings.json` parity across dispatch_target repos.** Currently each repo's project-level settings (where they exist) drift independently. `registry.yaml` could carry a "permissions" block that sows the deny-list to each repo's `.claude/settings.json`. Filed in OS#47 trajectory's Open Threads.
- **Registry-required contract for dispatch_target repos.** "No `data/tool_registry.md`, no in-session work in this repo." Mostly moot now that dispatch is dead, but the principle generalizes. Same trajectory note.
- **GS staging promote (Tuesday cadence).** Next Tuesday is 2026-06-02. Re-evaluate the `allow_squash_merge=false` setting Nathan applied on 2026-05-26. Check whether rebase-merge on staging has produced acceptable feature-PR history; consider per-branch ruleset alternative (master: merge-commit only; staging: squash or rebase) if rebase noise is too high.
- **Hook regex tightening as needed.** If the hook hits a false positive on legitimate Bash calls outside the git/gh whitelist, the regex needs tightening — log the case as a feedback memory so future sessions can refine `~/.claude/hooks/check_db_access.py` precisely.

## Next session

1. Watch for hook false positives on legitimate Bash calls. Log any cases.
2. Confirm AG and GS merges propagated correctly (notify-ag-on-master should fire on GS staging → master promote; that's a Tuesday concern).
3. PR #46 (feat/trajectory-template) is still open — pre-existing, untouched this session. Whether it merges is Nathan's call.
4. Consider OverSteward feature for cross-repo `.claude/settings.json` sync if drift becomes painful.

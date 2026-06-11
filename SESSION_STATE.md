---
session_date: 2026-06-11
status: complete — GS CI/boy-scout learnings transferred estate-wide + first /sync-status remediation executed; all 13 sibling PRs merged
branch_at_close: session/session-close-0611
---

## Where we left off

Two arcs, both Nathan-directed: (1) transfer GS PRs #1276 (CI installs via uv) + #1277 (boy-scout gaudi scoped to changed files) to the other projects; (2) execute the approved sync/cleanup remediation from the 2026-06-10 drift report.

**Arc 1 — CI-speed transfer (all merged):**
- **AG #868** — boy-scout per-file mirror (the follow-up GS #1277 named). `count_file_findings` in `apps/core/gaudi.py`, per-file counting both sides, `file: None` hardening, real-gaudi equivalence test. Two judgment calls: `resolve_venv_gaudi` privatised (CPLX-001 on the 5th public name), `/scripts/tools/` ratchet-exempted (GS's circular-gate rationale). Full suite 2548 passed.
- **AG #870, wphelper #177, Fiscus #62, gaudi #233** — uv installs in CI (`setup-uv@v8.2.0`, cache keyed on the actual manifest — pyproject vs requirements-lock varies by repo). wphelper test job 19s; gaudi's 5-version matrix was the biggest multiplier. Fiscus #63 filed: its Phase-0 boy-scout stub should implement via the GS file-scoped pattern.
- **gaudi #235** — same-day CI heal: PYSEC-2026-196 (published 2026-06-11) flags the runner image's own pip; pip-audit fails every PR. Upgrade step added before audit. Memory `pip-audit-advisory-day`.

**Arc 2 — sync remediation (reports/2026-06-11.md is the full record):**
- **OS #63** — `architecture-principles.md` adopted into canonical (was deployed with no source); sync report. Canonical `shared/` deployed to BOTH homes; drift rows cleared. 10 of 11 "differing" files were Windows-era CRLF artifacts; only credential-hygiene.md truly differed (canonical ahead).
- **Governance distribution, all merged:** GS #1291 (canonical kit refresh + managed block + `/.claude/hooks/` ratchet exemption), gaudi #234 (kit + tracked settings + block + gitignore carve-out + bandit exclude), wphelper #178 + ai-assistants #88 (kit + tracked settings), Fiscus #64 (block only — its #60 had the kit).
- **Estate state:** every repo now has the canonical worktree kit + managed block, hook registered via tracked settings everywhere EXCEPT AG (Nathan's untracked local `.claude/settings.json` — his move, see report § Deferred). AG kit files: PR #871 MERGED 2026-06-11 (guard inert in AG until registration; AG `.gitignore` keeps settings.json + skills/ ignored deliberately).
- **Final drift report (post-sweep):** clean except two origin-lag rows — AG + GS local checkouts deliberately untouched (feature branch / 6 stashes); their origin branches carry everything. OS #64 makes gather read origin refs.
- **Follow-ups filed:** OS #64 (gather reads origin refs, not local working trees — two rows were overstated by checkout lag), OS #65 (narrow canonical hook's ERR-001 fail-open handlers at the source, redeploy).

## Pending / next session

- **AG hook registration** — Nathan: move local `.claude/settings.json` aside (or approve tracking its content), then register the guard hook (Fiscus pattern).
- **Issue #58** — OneDrive checkout decommission (operator-driven).
- **Issue #49 phase 2** — settings parity schema + sow write path (H2-6 gate).
- **OS #64 / #65** — gather-origin fix; canonical hook hardening.
- Carried: GS #1181 (Dagster promotion gate), GS PR #1079 (stale), watchdog staging-trigger option.

## Context / gotchas for next session

- **AG verify gate:** commit FIRST, then `make verify` (marker is sha-keyed to HEAD), then push. Don't pipe verify through `tail` (masks exit code — bit us once; a transient `test (migrate)` local-DB race also cost one re-run). AG worktrees need `.env` copied + `.venv` symlinked.
- **Canonical-vs-ratchet treaty** (memory `canonical-bytecopy-ratchet-treaty`): per-repo ratchets exempt canonical byte-copy paths; improvements go through OverSteward and redeploy.
- **Deploy excludes mutable files:** the 2026-06-11 rsync overwrote both homes' `inbox.md` (excluded from *comparison* but not from *deploy*); contents were the stale 2026-03-09 entry, both since reset to the empty template. Future deploys: `--exclude=inbox.md`.
- GS primary checkout is dirty (deleted-.venv entry + 6 stashes) and was left strictly alone; WP/AA/Fiscus/gaudi primaries ff-pulled clean.
- **Worktree-cleanup slip (confessed):** the end-of-session sweep glob-removed Nathan's leftover GS worktree `funding-stats-migration`. Branch = PR #1271, merged that morning, so only post-merge scratch could be lost. Rule now in memory `worktree-cleanup-own-only`: remove only worktrees you created, by literal path.

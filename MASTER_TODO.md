# Master TODO — OverSteward

**Vision:** Two-pillar steward — (1) governance sync across 15 contexts, (2) orchestration of in-session pickup work across five production repos (aigranthelper, grantspider, wphelper, ai-assistants, fiscus).

**Workflow:** Completed tasks → TODO_COMPLETED.md | Next tasks pull from → TODO_BACKLOG.md

Plan reference: `OVERSTEWARD.md` (Phase Roadmap); full session history in Stewards_Ledger.

---

## Active

- [ ] **Issue #49 — settings parity, phase 2** (phase 1 SHIPPED: PR #62 tooling, PR #63 + 2026-06-11 sweep remediated the drift — `reports/2026-06-11.md`). Remaining: `settings_managed`/`permissions` registry schema + sow write path, gated per H2-6. Includes the AG hook-registration question (Nathan's untracked local settings.json).
- [ ] **Issue #58 — decommission dormant OneDrive checkouts** (supersedes #39). Operator-driven: triage untracked Windows-only artifacts in the seven dormant checkouts, then delete them.
- [ ] **Issue #64 — gather reads origin refs, not local working trees** (filed 2026-06-11; two drift rows were overstated by checkout lag).
- [ ] **Issue #65 — harden canonical hook's fail-open handlers (ERR-001 ×2) and redeploy** (filed 2026-06-11; GS exempted `/.claude/hooks/` pending this).

## Sentry queue — 2026-08-10 triage (canonical set after dedupe; work top-down)

GS (grantspider):
- [ ] **GS#2007** — `neon_consumption_snapshot_job` failing nightly since 07-30; the Neon cost meter is blind against the $50/mo target. Cheapest check first: is `GRANTSPIDER_ALERT_TO` set in prod?
- [ ] **GS#2165** — `pull_ag_corrections_job` failed every daily run since 08-01; the AG→GS corrections seam is down.
- [ ] **GS#2004** — promote PR#1997 to prod so run-failure Sentry events carry the failure body (unblocks all run-failure root-causing; blocks #1989).
- [ ] **GS#2180** — contamination-repair CLI `_write_repair` crashes on duplicate `mine_url_entity` key (PYTHON-1F); make idempotent **before** the GS#2160 apply is authorized.
- [ ] **GS#1989** — ddg hourlies failing ~19% of runs (PYTHON-9 ×49, PYTHON-A ×41 through 08-10); page_classification_drain (PYTHON-H ×4) folded in.
- [ ] **GS#1987** — snapshot jobs' deterministic ~45-min death (high_value ×26 + markdown ×18 through 08-10); the ~45-min limit still unidentified.
- [ ] **GS#2008** — `foundation_search_index_job` fails nightly: Typesense unprovisioned but schedule ON.
- [ ] **GS#2166** — `db scratch` CLI ships exploratory-SQL typos to Sentry (8 issues / ~25 events); catch-and-print, never capture.
- [ ] **GS#2187** — chore: rename Sentry project `python` → `grantspider` (DSN survives; verify an event after).

AG (aigranthelper):
- [ ] **AG#1517** — public foundation page killed by gunicorn worker timeout blocked on a research-DB query; customer-facing 5xx on cache miss.
- [ ] **AG#1368** — `enriched_since` statement timeout nightly ~03:05 (10 events through 08-10); also crashed the weekly digest (AIGRANTHELPER-21/22).
- [ ] **AG#1516** — HelpArticle/Revision admin pages 500: `_diff_html` calls `format_html` with no args; docs version-diff down.
- [ ] **AG#1518** — Sentry housekeeping triage (stuck demo draft, smoke-client non-JSON crash, one-off shell ImportError).

## Standing (carried across horizons)

- [ ] **Analyst persona** — build via `/create-persona` when a real Stocks/OpportunityMiner use case lands (trigger-gated, not scheduled).
- [ ] **billions registry note** — `soul_in_local: true` design formalized in H1-3; sow.py implementation in Horizon 3.

---

## Horizon 2 / Horizon 3

See TODO_BACKLOG.md.

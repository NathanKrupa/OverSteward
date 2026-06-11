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

## Standing (carried across horizons)

- [ ] **Analyst persona** — build via `/create-persona` when a real Stocks/OpportunityMiner use case lands (trigger-gated, not scheduled).
- [ ] **billions registry note** — `soul_in_local: true` design formalized in H1-3; sow.py implementation in Horizon 3.

---

## Horizon 2 / Horizon 3

See TODO_BACKLOG.md.

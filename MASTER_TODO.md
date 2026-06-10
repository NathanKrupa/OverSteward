# Master TODO — OverSteward

**Vision:** Two-pillar steward — (1) governance sync across 15 contexts, (2) orchestration of in-session pickup work across five production repos (aigranthelper, grantspider, wphelper, ai-assistants, fiscus).

**Workflow:** Completed tasks → TODO_COMPLETED.md | Next tasks pull from → TODO_BACKLOG.md

Plan reference: `OVERSTEWARD.md` (Phase Roadmap); full session history in Stewards_Ledger.

---

## Active

- [ ] **Issue #49 — `.claude/settings.json` parity across repos** (scoped 2026-06-10, read-only first). Phase 1 of the build: `gather.py` + `diff.py` + `/sync-status` skill (H2-3/H2-4/H2-5) covering CLAUDE.md managed blocks, dual-target `shared/` parity, per-repo `.claude/settings.json` + hooks drift, and tracking-doc freshness. Write-side `sow.py` stays gated per H2-6.
- [ ] **Issue #37 — andon issue template + label** (Fiscus channel). Green-lit by Nathan 2026-06-10 (was tracking-only since 2026-05-14). Copy Fiscus's canonical `andon.md` into `.github/ISSUE_TEMPLATE/`; create matching label; confirm Fiscus's aggregator scan list includes OverSteward (it isn't a pickup repo).
- [ ] **Issue #58 — decommission dormant OneDrive checkouts** (supersedes #39, closed 2026-06-10). Operator-driven: triage untracked Windows-only artifacts in the seven dormant checkouts, then delete them. Husk residue from #39 goes with them.

## Standing (carried across horizons)

- [ ] **Analyst persona** — build via `/create-persona` when a real Stocks/OpportunityMiner use case lands (trigger-gated, not scheduled).
- [ ] **billions registry note** — `soul_in_local: true` design formalized in H1-3; sow.py implementation in Horizon 3.

---

## Horizon 2 / Horizon 3

See TODO_BACKLOG.md.

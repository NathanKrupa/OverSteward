---
session_date: 2026-04-30
status: paused (AG cross-DB residual scoped + filed; ready for dispatch)
context: audit + scoping session for the cross-DB M2M debt left by the 2026-04-30 cutover
---

## Where we left off

Audit session for the residual technical debt left in aigranthelper by the morning's research-DB cutover. Three issues filed in dispatch order; data contract and architecture.md refreshed to reflect the new two-Neon-project topology.

## What this session did

Read AG's [SESSION_STATE.md](../../aigranthelper/SESSION_STATE.md) and the cutover artefacts. Audited the AG codebase for the cross-DB M2M residue (`Organization.focus_areas` → `research.NTEECode`) and the test-config paperwork (`MIRROR: default`) that papers over it. Reviewed an initial 5-PR plan for holes; principled decisions made; landed on a tighter 3-issue plan.

### Decisions committed

- **Option 1 over option 2 for #414.** `Organization.focus_areas = ArrayField(TextField())`, not a separate `FocusArea` model. Grep confirms no consumer uses the M2M reverse direction (`nteecode.organizations`); per-row metadata has no concrete need; YAGNI applied.
- **One coherent PR for the storage swap, not three.** Earlier draft staged a service-extract + service-extract + storage-swap sequence. Rejected: the service exists *because of* the swap; pre-extracting it is premature abstraction.
- **Test config moves to a real second Postgres test DB.** SQLite rejected — ArrayField, pgvector, and UUID variances make Postgres-only the only honest test surface. Removes the `MIRROR: default` paperwork in `config/settings/test.py:24` that hides prod-vs-test routing divergence.
- **Old code is hidden-failure surface — Issue 3 lands.** The single-DB legacy fallback in `apps/core/db_router.py:51-57` is dead the moment #415 lands. Delete, don't leave.
- **Doc refresh isn't an issue, it's prescribed maintenance.** Architecture.md §6 obligates it after a §7-surface change. Landed in this session.

## Filed (aigranthelper)

| # | Title | Role |
|---|---|---|
| [#415](https://github.com/NathanKrupa/aigranthelper/issues/415) | Test config: separate research test DB on local Postgres (remove MIRROR) | **Prerequisite.** Dispatch first. |
| [#414](https://github.com/NathanKrupa/aigranthelper/issues/414) | Replace cross-DB M2M with ArrayField + introduce NteeCatalogService | Updated in place. Closes the dual-residence footgun. Depends on #415. |
| [#416](https://github.com/NathanKrupa/aigranthelper/issues/416) | Retire single-DB legacy fallback in db_router (delete dead branch) | Cleanup. Depends on #415. |

Sequencing: 415 → 414 → 416. One AG dispatch in flight at a time per I-2.

## Documents refreshed in this session

- [`documentation/data-contract-grantspider-aigranthelper.md`](documentation/data-contract-grantspider-aigranthelper.md) → **v1.2 (2026-04-30)**. §2 topology rewritten to two Neon projects; `ag_research_reader` named in §4; `RunSQL`/`model_name=None` gap closure documented; aigranthelper #414 referenced as residual debt.
- [`architecture.md`](architecture.md). §2 seam reworded; §3 I-4 promoted to technical-enforcement language with PR #413 cite; §4 adds **L-AG-1** (cross-DB M2M debt) and **L-AG-2** (router fallback / MIRROR test paperwork); §5 logs the cutover at the top, drops oversteward #12 to keep cap.
- [`memory/project_ntee_codes_dual_residence.md`](../../.claude/projects/c--Users-natha-OneDrive-Tech-Python-Oversteward/memory/project_ntee_codes_dual_residence.md) rewritten to point at the three filed issues and the option-1 commitment. Marked for deletion once #414 closes.

## Architectural decisions made this session (load-bearing)

- **`Organization.focus_areas` becomes `ArrayField(TextField())`.** No FK to research; no per-row metadata; no `FocusArea` model. The reverse query `NTEECode.organizations` is unused — verified by grep.
- **Tests run against a real second Postgres test DB.** No SQLite. No `MIRROR`. Prod-vs-test routing must match.
- **The legacy fallback in `db_router.py` is dead code post-#415.** Delete it; don't keep dual paths.
- **NTEE catalog logic lives in `apps/research/services` as `NteeCatalogService`.** `_ntee_codes_grouped` and `_representative_ntee_codes_for_groups` move out of `accounts/views.py` (they were misclassified as outer-layer code).

## Resume sequence

1. Dispatch [#415](https://github.com/NathanKrupa/aigranthelper/issues/415) on aigranthelper.
2. After #415 merges, dispatch [#414](https://github.com/NathanKrupa/aigranthelper/issues/414).
3. After #414 merges and `ntee_codes` is verified absent from AG default DB, dispatch [#416](https://github.com/NathanKrupa/aigranthelper/issues/416).
4. After #414 closes, delete `memory/project_ntee_codes_dual_residence.md` and remove the L-AG-1 row from `architecture.md` §4.

## Memories touched this session

- `project_ntee_codes_dual_residence.md` — updated body and description to point at #415/#414/#416. Will be deleted post-#414.

## Operational notes

- GitHub Actions still off (cost). Local test discipline gates per I-16. AG full suite (~1,518 tests) must run green locally before merge.
- The pre-drop snapshot at `b2://GrantSpider/db-backups/research-pre-drop/20260430T160135Z_phase3_pre_drop.dump` remains the Phase-3 rollback point.

Standing by for resume.

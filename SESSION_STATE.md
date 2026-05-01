---
session_date: 2026-05-01
status: paused (AG cross-DB cutover residue fully closed)
context: dispatch + verify of #415 → #414 → #416, plus #420 (local PG test backend) and #423 (init.sql fix), plus oversteward cleanup
---

## Where we left off

The 2026-04-30 cutover residue is fully closed. Six PRs landed today across two repos: five on aigranthelper, one on oversteward. Architecture is in its target state — two Neon projects (default + research), single-path router (no legacy fallback), no `ntee_codes` dual-residence, ArrayField storage, local Dockerized pgvector test backend.

## What this session did

### Morning (audit + scoping → already in master from PR #30)

Audit of the cross-DB residue left by yesterday's cutover. Filed three aigranthelper issues in dispatch order with principled decisions baked in:

- #415 (prereq) — test config: separate research test DB on local Postgres, remove `MIRROR: default`
- #414 (storage swap) — `Organization.focus_areas` from cross-DB M2M to `ArrayField(TextField())`; new `NteeCatalogService`; drop dual-residence stub. **Option 1 over option 2** committed (no FocusArea model — YAGNI; grep confirms zero consumers of M2M reverse direction).
- #416 (cleanup) — retire single-DB legacy fallback in `apps/core/db_router.py`. Old code is hidden-failure surface; delete fully.

### Afternoon (dispatch + verify + merge)

Dispatched #415 → #414 → #416 serially per I-2. Both #414 dispatches stalled on the harness watchdog mid-test-run; took it home directly from a worktree. Along the way:

- **`pytest-timeout` and `pytest-rerunfailures` installed** in AG venv and added to dev deps. Hangs surface as test failures with usable tracebacks instead of pinning forever; transient Neon flakes self-heal up to two retries. Then `timeout_func_only = true` so first-run migration replay (>60s) doesn't trip the per-test timer.
- **Local Postgres test backend stood up** (#420 / PR #421). Dockerized `pgvector/pgvector:pg17` on `:5433` with two pre-created DBs. Required a Docker Desktop reset partway through — Nathan had deleted the `AppData/Local/Docker/wsl/` directory previously while cleaning up disk space; `wsl --unregister docker-desktop docker-desktop-data` and a clean Docker Desktop relaunch recreated the WSL distros.
- **Followed-up #423**: init.sql had to install pgvector on `template1` so Django's `--create-db` (recreate from template1) inherits the extension. Hotfixed the running container; landed durable fix in #423.
- **Final suite on local PG: 1524 → 1528 passed in ~2 min.** ~6× faster than Neon. #414 verified locally, opened #422, merged.
- **#416** dispatched cleanly (no harness stall this time, ~6 min duration). PR #424 merged. Defending test `test_research_label_blocked_in_all_envs` parametrised across 4 cases.

### Evening (oversteward cleanup → PR #31, merged)

- `architecture.md` §4: dropped L-AG-1 (cross-DB M2M debt) and L-AG-2 (router fallback / MIRROR test paperwork) — both retired.
- `architecture.md` §5: logged the cross-DB residual cleanup at the top; dropped `oversteward #14` to hold cap.
- `last_updated: 2026-05-01`.
- `memory/project_ntee_codes_dual_residence.md` deleted (per-machine, not in repo).

## Merged this session

| Repo | # | What |
|---|---|---|
| aigranthelper | [#419](https://github.com/NathanKrupa/aigranthelper/pull/419) | Test config: separate research test DB (closes #415) |
| aigranthelper | [#421](https://github.com/NathanKrupa/aigranthelper/pull/421) | Local pgvector test backend (closes #420) |
| aigranthelper | [#422](https://github.com/NathanKrupa/aigranthelper/pull/422) | ArrayField + NteeCatalogService (closes #414) |
| aigranthelper | [#423](https://github.com/NathanKrupa/aigranthelper/pull/423) | init.sql template1 pgvector fix |
| aigranthelper | [#424](https://github.com/NathanKrupa/aigranthelper/pull/424) | Retire single-DB router fallback (closes #416) |
| oversteward | [#31](https://github.com/NathanKrupa/OverSteward/pull/31) | Retire L-AG-1, L-AG-2; log cleanup |

## Architectural decisions made this session (load-bearing)

- **`Organization.focus_areas` is `ArrayField(TextField())`.** No FocusArea model. No FK to research. Reverse direction (`NTEECode.organizations`) was unused; option 1 picked over option 2 on YAGNI.
- **Tests run against a real second Postgres test DB.** `MIRROR: default` is gone. Prod-vs-test routing topology now matches.
- **`apps/core/db_router.py` has one code path.** Single-DB legacy fallback deleted. `_has_research_db()` and `_is_grantspider_owned()` deleted. `GRANTSPIDER_OWNED_TABLES` retained in `apps/research/constants.py` (still consumed by `regenerate_research_models.py` codegen and 2 test files).
- **NTEE catalog logic lives in `apps/research/services.NteeCatalogService`.** `_ntee_codes_grouped` and `_representative_ntee_codes_for_groups` moved out of `accounts/views.py`. Outer-layer view code no longer carries middle-layer business logic.
- **Local Dockerized pgvector is the canonical test backend going forward.** ~6× faster than Neon. Documented in AG's CLAUDE.md.
- **`pytest-timeout` + `pytest-rerunfailures` are now baseline AG test infra.** `timeout = 60`, `timeout_func_only = true`, `--reruns 2 --reruns-delay 1`. Hangs surface; transient flakes self-heal.

## Operational learnings worth remembering

- **Harness stall pattern persists on long-running tests.** Both #414 dispatches died on the full pytest run (~13 min on Neon, ~2 min on local). After moving tests to local PG, dispatch #416 ran clean. The stall is correlated with long subprocess steps; the heartbeat-commit pattern (playbook v1.8) preserves work but doesn't prevent the stall. Worth a follow-up watchdog improvement at some point.
- **Docker Desktop on Windows is brittle to `AppData/Local/Docker/` deletion.** WSL keeps the distros registered even after the disk is gone; daemon won't start. Recovery: `wsl --unregister`, then full Docker Desktop relaunch (with Nathan clicking through the EULA / WSL2 backend).
- **`--create-db` with pgvector requires the extension on `template1`.** Per-DB CREATE EXTENSION isn't enough; Django recreates from template1 which doesn't inherit user-installed extensions. #423 codified this.
- **VSCode IDE diagnostics noise on pyproject.toml edits is a red herring.** "Package not installed" hints fire because VSCode's selected interpreter isn't the AG venv — ignore.

## Memories touched this session

- Deleted `project_ntee_codes_dual_residence.md` — obsolete after #414 closed; cross-DB M2M debt no longer exists.

## Resume sequence

Nothing in flight. AG dispatch chain done. Oversteward master clean at `d606e72`. Local AG main has #424 at HEAD.

Open AG follow-ups to consider (NOT in flight):

- AG #87 — old `needs-input` (Grant Radar 8-pointed star chart). Stale per `/project-status`. Run `/answer aigranthelper 87` when ready.
- The harness stall on long pytest runs. Worth scoping a heartbeat-watchdog improvement to playbook eventually.

Standing by for resume.

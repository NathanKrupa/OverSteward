---
session_date: 2026-04-30
status: paused (Nathan splitting to fresh GS + AG sessions)
context: 2026-04-30 disaster recovery + research-DB cutover (full sequence)
---

## Where we left off

Coordinator session for the 2026-04-30 disaster recovery and research-DB cutover. Detailed per-repo state lives in:

- ``~/Tech/Python/grantspider/SESSION_STATE.md``
- ``~/Tech/Python/aigranthelper/SESSION_STATE.md``

**Headline:** GrantSpider's research data is now isolated on a dedicated Neon project. The shared ``neondb`` no longer hosts any GS-owned tables. Both PRs merged.

## What happened (timeline)

1. **Morning incident, ~09:45–10:35 UTC.** ~34 GS-owned tables disappeared from the shared ``neondb``. Forensic root cause: AG's ``apps/research/migrations/0001_create_research_tables.py`` carried ``reverse_sql="DROP TABLE IF EXISTS foundations;"``. Django's router gated by ``model_name`` — but ``RunSQL`` ops have ``model_name=None``, so the gate fell through and the destructive SQL ran.
2. **Restored from B2 dump** (09:45 UTC pre-loss) onto a brand-new dedicated GrantSpider Neon project (``ep-plain-breeze-amopwc5f``).
3. **Phase 1 — GS cutover:** rotated GS ``.env`` (NEW URLs primary, OLD preserved as ``_OLD``); separate B2 backup prefix (``GRANTSPIDER_B2_BACKUP_PREFIX=db-backups/grantspider/``); 3,470 GS unit tests green on new DB.
4. **Phase 2 — AG hardening:** router now refuses every research-label op when a separate research DB is configured (closes the ``RunSQL`` gap); ``apps/research/migrations/0001`` neutralised; stale ``crawl_queue``/``cf_scrape_log`` references dropped. AG full suite: 1,518 passed.
5. **Phase 3 — drop GS-owned tables from old neondb.** Pre-drop snapshot at ``b2://GrantSpider/db-backups/research-pre-drop/20260430T160135Z_phase3_pre_drop.dump`` (168.5 MB). 36 GS tables + ``alembic_version`` dropped in single transaction. AG suite re-ran: ``ntee_codes`` had to be recreated as an empty stub on AG default DB (cross-DB Django M2M tech debt — see [aigranthelper#414](https://github.com/NathanKrupa/aigranthelper/issues/414)).

## Merged

- **[grantspider#626](https://github.com/NathanKrupa/grantspider/pull/626)** — B2 prefix wiring + links v2 / IRS extras housekeeping migrations + ``NteeCode`` model and seed migration (``71e11596ed29``).
- **[aigranthelper#413](https://github.com/NathanKrupa/aigranthelper/pull/413)** — router gate hardened, destructive 0001 neutralised, ``crawl_queue`` / ``cf_scrape_log`` cleanup with state-only ``DeleteModel`` migration ``0006``.

## Resume sequence

Open the per-repo ``SESSION_STATE.md`` in a fresh session for either repo. Each is self-contained.

## Architectural decisions made this session (load-bearing)

- **GS lives on its own Neon project.** ``ep-plain-breeze-amopwc5f`` (pooled) / ``ep-plain-breeze-amopwc5f`` (direct), DB ``neondb``, owner role ``gs_owner``, AG-side reader ``ag_research_reader`` (read-only).
- **AG default DB stays on the original shared ``neondb``** (``ep-solitary-art-aenuetaf``). All Django/Django-Stripe/account/billing tables remain there.
- **Router-as-gate doctrine.** When a separate research DB is configured (``RESEARCH_DATABASE_URL`` set), AG's ``allow_migrate`` returns ``False`` for *every* operation under the research label on either alias. Defense in depth: ``0001``'s destructive ``RunSQL`` is also empty now.
- **``ntee_codes`` lives on both DBs in lockstep.** Canonical on research DB (Alembic ``71e11596ed29``, seeded from ``grantspider.config.ntee.NTEE_SEED``). Stub on AG default for the cross-DB Django M2M (``Organization.focus_areas`` → ``NTEECode``) until that field is refactored. Tracked in [aigranthelper#414](https://github.com/NathanKrupa/aigranthelper/issues/414); see memory ``project_ntee_codes_dual_residence.md``.

## Memories saved this session

- ``project_research_db_cutover.md`` — DB topology + per-DB ownership facts.
- ``feedback_django_runsql_router_gap.md`` — the ``RunSQL`` ops + ``model_name=None`` trap that caused the wipe.
- ``project_ntee_codes_dual_residence.md`` — dual ``ntee_codes`` workaround + refactor pointer.

## Operational follow-ups (not blocking)

- **GitHub Actions billing still failed** — every PR this session reported CI FAILUREs because Actions jobs never started. Per ``project_ci_required_checks.md``, CI isn't required pre-launch, so merges proceeded; local test discipline is the real gate.
- **[aigranthelper#414](https://github.com/NathanKrupa/aigranthelper/issues/414)** — refactor ``Organization.focus_areas`` off the cross-DB M2M; until then the ``ntee_codes`` stub on AG default DB must stay in lockstep with ``NTEE_SEED``.
- Pre-drop snapshot retention: ``db-backups/research-pre-drop/20260430T160135Z_phase3_pre_drop.dump`` is the rollback point if anything Phase-3 needs to be undone.

Standing by for resume.

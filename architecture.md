---
last_updated: 2026-10-31
scope: aigranthelper, grantspider, wphelper, ai-assistants, oversteward, gaudi, fiscus, exchequer
maintenance: pull-based — update on any session that discovers staleness
read_by: scoping / planning sessions only. Read at the start of an in-session pickup if the issue may touch more than one repo or any §3 invariant; routine single-issue work skips this doc.
token_budget: ~2k target, exceeded (~5k after the 2026-10-31 refresh). The next session that needs to grow it splits it per repo instead (§6).
---

# Architecture (machine-readable state)

What has actually been built across the House of Krupa development estate. Authoritative for "what exists today, who owns it, what's known broken." Every row cites its source — if a row's source no longer exists, the row is stale and must be corrected before relying on it.

Every row was re-verified against code on 2026-10-31 (OS#638): AG `origin/main` f2a8d99, GS `origin/main` be9ed67, OverSteward `origin/master` 775accd, the other repos at their default branch on origin. Paths are repo-relative unless a repo is named.

**When to read:** at the start of a scoping or planning session that may touch more than one repo, or that may affect a load-bearing invariant. Routine pickup of a single issue reads the issue body and the dispatch playbook ([`shared/skills/dispatch/playbook.md`](shared/skills/dispatch/playbook.md)).

**When to update:** the session that scopes a §2/§3 change updates §5 with the PR# on landing. The session that discovers a stale row corrects it before continuing.

---

## §1 Repos

| ID | Purpose | Stack | Dispatch target | Local path |
|---|---|---|---|---|
| aigranthelper | Grant-management SaaS — the paying-user surface (aigranthelper.com) | Python 3.14, Django 6.0, HTMX + Tailwind v4 (no SPA); Railway (Railpack from `Procfile`, web + cron services + internal Typesense); tenant DB = Railway Postgres 17 (`config/settings/base.py:217`), research DB = GS's Neon via `RESEARCH_DATABASE_URL` (`base.py:246-266`) | yes | `/home/natha/aigranthelper` |
| grantspider | Grant/foundation data producer — ingestion, crawl, enrichment; sole owner and writer of the research schema | Python 3.14, SQLAlchemy + Alembic, pgvector, Neon; Dagster on Railway (`railway.toml`: dagster-webserver, dagster-daemon, dagster-code, daemon-watchdog cron; assets in `src/grantspider/orchestration/definitions.py`) | yes | `/home/natha/grantspider` |
| wphelper | WordPress client toolkit; canonical home for external connectors (WP REST, Kit, GA4, GSC, FTP, IndexNow) | Python ≥3.11 | yes | `/home/natha/wphelper` |
| ai-assistants | `almoner` package — content authoring, CRM, ingestion, WP integration. No CI | Python | yes | `/home/natha/ai-assistants` |
| oversteward | Estate control plane: `registry.yaml`, canonical `shared/` (souls, agents, skills, hooks, dev scripts), session-start sweeps, dream cycle, review loop | Python, uv, YAML; CI `.github/workflows/ci.yml` (not a required check) | yes | `/home/natha/OverSteward` |
| gaudi | Architecture linter, open source (PyPI `gaudi-linter`); gates AG and OverSteward | Python AST | no | `/home/natha/gaudi` |
| fiscus | Observation-and-kaizen platform: subject contracts, weekly/monthly reviews, lessons corpus | Python ≥3.12, pandas, polars, duckdb, pydantic, Quarto | yes | `/home/natha/fiscus` (lowercase) |
| exchequer | Private counting-house — `exchequer pull` billing connectors, CSV ledgers, monthly close; zero LLM tokens | Python ≥3.12, uv | yes | `/home/natha/exchequer` |
| steward-memory | Private memory source-of-truth for the dream cycle; deployed by `scripts/deploy_memory.py`. Not in `registry.yaml` | Markdown only | no | `/home/natha/steward-memory` |

Source: `registry.yaml` `dispatch_target` flags. Registry also carries non-code contexts (Obsidian vaults, billions, AI Grants, MacGregor, Stocks, OpportunityMiner) and David's Minecraft repo, which estate sweeps exclude. `thankathon` and `wphelper-clients` exist on disk but are in neither the registry nor this table.

### Inside aigranthelper (`apps/`)

| Area | What it is | Source |
|---|---|---|
| Research | Read-only GS mirror (`models/_generated.py`, `_views.py`); match scoring; keyword/semantic/hybrid search; Typesense with fail-open Postgres fallback; public foundation/sector/city pages | `apps/research/`, `apps/research/typesense_search.py` |
| Pipeline / reporting | Grant lifecycle (Program, FunderRelationship, Application, Award, FunderMilestone, UserFunderSignal, SavedGrantor) and post-award compliance | `apps/pipeline/models.py`, `apps/reporting/` |
| Matchmaker | Match telemetry, golden-label evals, the `pipeline_history-YYYY-MM-DD.jsonl` writer | `apps/matchmaker/` |
| Studio | AI-assisted grant drafting (versioned drafts in B2); Anthropic, Gemini, OpenAI via one module | `apps/studio/`, `apps/studio/llm.py` |
| Accounts / billing | Multi-tenant orgs + consultants, magic-link auth; Stripe via dj-stripe 2.11 | `apps/accounts/`, `apps/billing/` |
| SEO / edge | IndexNow, GSC indexation monitor, Cloudflare cache rules + purge + warmer, lead pages; home-page A/B Worker | `apps/seo/`, `edge/home-arm/`, `apps/landing/` |
| Ops / feedback / telemetry | `/internal/ops/` reports + verdicts, visitor DataCorrection, EmailLead, Fiscus telemetry endpoint | `apps/ops/urls_internal.py`, `apps/feedback/`, `apps/telemetry/` |
| Docs / bot / worldmodel | DB-backed help centre; Web Bot Auth key directory; customer world model (beliefs, goals, event spine) | `apps/docs/`, `apps/bot/`, `apps/worldmodel/models/` |

Scheduled work runs as Railway cron services (`render_sitemaps`, `submit_seo_urls`, `monitor_indexation`, `backup_database`, digests/reminders, email outbox), listed in `docs/operations/production-deploy.md:168-242`. GitHub Actions crons are `smoke.yml`, `divergence-watchdog.yml` and `prewarm.yml` (a daily Neon warm-up request, #1341).

### Inside grantspider (`src/grantspider/`)

| Area | What it is | Source |
|---|---|---|
| IRS ingestion | 990-PF Part XV and Schedule I grants (TEOS bulk), BMF monthly sync, SOI annual extract | `services/irs_990_ingestion.py`, `services/irs_990_schedule_i*.py`, `services/irs_bmf_sync.py`, `services/irs_annual_extract_ingest.py` |
| 990-PF facsimiles | IRS XSL → PDF → B2 | `services/facsimile*.py`, `cli/facsimile.py` |
| Other sources | 360Giving; federal opportunities (Grants.gov, SAM, USAspending, agency hydration); community, corporate and diocesan foundation discovery | `connectors/threesixtygiving.py`, `services/gov_pipeline.py`, `connectors/community_foundations/`, `services/corporate_grantmaker_discovery.py` |
| Websites | Discovery (IRS, Wikidata, Brave, DDG, crt.sh providers) + Anthropic verification judge | `services/website_resolver.py`, `services/llm_judge.py`, `services/verification/` |
| Crawl | Railway sitemap/crawlee crawler; laptop crawler with a local SQLite resume ledger; Common Crawl + Wayback; URL-heuristic page classification (no LLM) | `services/sitemap_snapshot*.py`, `services/local_crawl.py`, `connectors/crawl_ledger.py`, `services/page_classification.py` |
| Enrichment | SKIP LOCKED claim queue drained by in-session Sonnet workers (`.claude/workflows/enrich-drain.*`); metered Anthropic key fail-closed; token-free funding profiles | `services/enrichment_queue.py`, `config/metered_api.py:94`, `services/funding_profile*.py` |
| Embeddings / search index | Local all-MiniLM-L6-v2 (384-d), source-hash staleness; GS owns the Typesense indexing | `services/embedding_generation.py`, `services/embedding_hash.py`, `services/foundation_search_index.py` |
| Data quality | Stage-health ledger (`dq health`), freshness SLAs, canaries, Sentry run-failure sensor, Neon consumption canary | `cli/dq_health.py`, `services/stage_health*.py`, `services/freshness_sla.py`, `orchestration/run_failure_sensor.py` |
| Safety | Operator-armed prod migrations (`db migrate-prod arm\|run\|cleanup`), pre-migration backup, weekly backups of research + Dagster + AG tenant DBs, monthly restore drill | `_prod_migration_token.py`, `services/prod_migration.py`, `services/db_backup_weekly.py`, `services/backup_drill.py` |

### Subsystems inside oversteward

| Subsystem | Purpose | Source |
|---|---|---|
| The Telegraph | Membrane over the GitHub-issue bus (Epic Conductor + cross-repo issue filer); transport is Happy | `src/oversteward/telegraph/conductor.py`, `shared/scripts/telegraph/file_cross_repo_issue.py`, `.claude/skills/telegraph-operator/` |
| The Vintner | `/pipeline-status` GS→AG funnel; reads one read-only DSN (`VINTNER_RESEARCH_DATABASE_URL`, GS Neon) | `src/oversteward/vintner/reader.py:21` |
| Session-start sweeps | Sentry triage, Railway liveness, AG ops triage, GS stage health, backup health, operator steps (Todoist) | `src/oversteward/{sentry,liveness,ag_ops,stage_health,backup}/`, `scripts/operator_steps.py` |
| Dream cycle + kaizen | Transcript → memory consolidation (systemd timer); kaizen queue from Fiscus lesson clusters + `kaizen` issues | `src/oversteward/dream/`, `src/oversteward/dream/kaizen.py`, `shared/scripts/dream/dream-cycle.timer` |
| Review loop | Assembled-input adversarial reviewer with a `.review-rounds` ledger; CI `reviewer-verdict` gate | `src/oversteward/review_input.py`, `shared/agents/adversarial-reviewer.md`, `scripts/lint/require_review_verdict.py` |
| Dev family + sow | Canonical worktree/guard/env scripts and hooks, deployed to repos by sow; nightly `sync_repos` timer | `shared/scripts/dev/`, `src/oversteward/sow/`, `shared/scripts/dev/sync-repos.timer` |
| Memory deploy | steward-memory → `~/.claude/projects/*/memory/` | `src/oversteward/memory_deploy.py` |

---

## §2 Cross-repo seams

| Producer → Consumer | What flows | Source-of-truth |
|---|---|---|
| grantspider → aigranthelper (data) | AG reads the research DB through **`ag_research.*` views and functions** (26 unmanaged `_v` models, plus search/match SQL functions), connecting with the read-only `ag_research_reader` role. Nine documented base-table reads remain, each tagged `READS-BASE-TABLE:`. `grantspider.ontology` supplies one type (`NteeCode`) and is not the read path | GS `src/grantspider/ag_research_views/__init__.py`; AG `apps/research/models/_views.py`, `apps/core/grantspider_reads.py`, `docs/CROSS_REPO_SCHEMA.md` rule 1; OverSteward `documentation/data-contract-grantspider-aigranthelper.md` v1.2 |
| grantspider → aigranthelper (code) | AG pins GS by SHA (`requirements.txt:463`, matched by `research_schema.lock`) and imports `grantspider.models`, `connectors.b2_storage` and `services.db_backup` at runtime. A push to GS main fires `repository_dispatch: gs-master-bump`; AG's bump workflow rejects non-`refs/heads/main` refs and force-updates one draft PR onto AG `staging` | GS `.github/workflows/notify-ag-on-main.yml:25-49`; AG `.github/workflows/bump-gs-pin.yml:28,79,203,212`, `apps/research/apps.py:26`, `apps/ops/management/commands/backup_database.py:52,93` |
| grantspider → aigranthelper (schema drift) | AG CI diffs `_generated.py` against GS `schema/research.sql` at the locked SHA. `_views.py` is not checked (G1) | AG `scripts/tools/check_research_drift.py`, `.github/workflows/ci.yml:744` |
| aigranthelper → grantspider | Visitor data corrections: AG serves export + ack at `/internal/corrections/`; GS pulls them into pinned overrides | AG `apps/feedback/urls_internal.py:23`; GS `connectors/ag_corrections.py`, `orchestration/ag_corrections_assets.py` |
| wphelper → aigranthelper, ai-assistants | Connector library: AG pins it by SHA (`requirements.txt:472`) for IndexNow + GSC; ai-assistants depends on it but still duplicates WP REST/FTP (L-AA-1) | AG `apps/seo/management/commands/submit_seo_urls.py:7`; ai-assistants `pyproject.toml:63`, `src/almoner/wp/api.py` |
| oversteward → all repos | `registry.yaml`; `shared/` deployed to both `~/.claude` homes; the dev family by sow PRs. In OverSteward the deployed side is symlinks, elsewhere copies | `registry.yaml`, `src/oversteward/sow/`, `tests/test_deployed_links.py` |
| aigranthelper → fiscus | Paginated NDJSON telemetry at `GET /internal/telemetry/`, RS256 JWT | AG `apps/telemetry/urls_internal.py:11`, `apps/telemetry/auth.py`; Fiscus `subjects/ghp-*/contract.yaml` (`status: stub`) |
| oversteward → fiscus | `data/pipeline_history.jsonl` read from disk (dispatch subject) | Fiscus `subjects/dispatch/contract.yaml` |
| pickup repos → fiscus | `andon`-labelled issues → `shared/andon.jsonl`. **The aggregator is a stub that only echoes** (L-FI-1) | Fiscus `src/fiscus/andon.py:20-27`, `.github/workflows/weekly-review.yml` |
| fiscus → oversteward | `fiscus review trajectories` JSON feeds the dream/kaizen worklist | `scripts/dream.py:215` |
| grantspider → oversteward | `grantspider dq health --json` (stage health, locally or via `railway ssh`); Vintner reads `vintner.corpus_funnel_v` | `src/oversteward/stage_health/sources.py:113,171`; `src/oversteward/vintner/reader.py` |
| aigranthelper → oversteward | `/internal/ops/reports/` read and `/internal/ops/verdicts/` write, bearer tokens | `src/oversteward/ag_ops/client.py:71-73`; AG `apps/ops/urls_internal.py` |
| Railway, Sentry → oversteward | Liveness for contexts with a `railway:` block (AG, GS only); Sentry issues org-wide | `src/oversteward/liveness/config.py:34`, `registry.yaml:166,298`; `src/oversteward/sentry/` |
| billing APIs, GA4 → exchequer | `exchequer pull` → `ledgers/pulled_costs.csv` (Anthropic, Stripe, Neon consumption API, Railway); GA4 funnel events emitted by AG (`sign_up`, `funder_saved`, `purchase`, `lead_captured`) | exchequer `src/exchequer/services/pull.py:59`, `src/exchequer/connectors/neon.py`; AG `apps/core/analytics.py:123-194` |

---

## §3 Load-bearing invariants

Rules that, if violated, break something. IDs are stable and never renumbered; a retired ID stays a gap.

| # | Invariant | Cite |
|---|---|---|
| I-1 | In-session pickup work never touches Nathan's live working tree (worktrees only) | `shared/skills/dispatch/playbook.md:25-28` (grantspider #426 postmortem) |
| I-2 | One in-flight **agent** PR per repo: dispatch refuses while an `<kind>/issue-` PR is open. The two surfaces disagree on whether `docs/` counts (L-DOC-1). `session/<name>` PRs are not covered | `shared/skills/dispatch/playbook.md:36` (includes `docs`), `SKILL.md:79` (omits it) |
| I-3 | Never bypass git hooks (`--no-verify`, `--admin`, hooksPath); never `git add -A` | `playbook.md:15,23`; `.claude/hooks/check_destructive_command.py` |
| I-4 | aigranthelper never writes the research DB: read-only Neon role, and the DB router's `allow_migrate` returns `False` for every research label unconditionally | AG `apps/core/db_router.py:34-46`, `config/settings/base.py:283` |
| I-5 | AG copies of producer fields declare Snapshot or Cache at definition. Partly kept: `foundation_name`/`grantor_name` copies are labelled; `FunderRelationship.accepts_unsolicited`, `typical_award_range_*`, `application_deadline` are not | AG `apps/pipeline/models.py:136,154-157,545,696,749`; data contract §3 |
| I-6 | Data-contract §7 fields are not removed/renamed/re-meant without the §8 dual-write procedure | data contract §7-8 |
| I-7 | GS data migrations use the ORM (ADR-006). **App code is not ORM-only**: ~129 `text()` calls across services/cli/orchestration/connectors, with no lint. Raw SQL must not bypass client-side defaults | GS `docs/adr/006-alembic-data-migrations-use-orm.md`; e.g. `services/address_backfill.py:164-228` |
| I-8 | Pre-migration UPDATEs collapsing many rows to one value audit every sibling UNIQUE (partial + full) on touched columns | memory `feedback_migration_sibling_unique_audit` |
| I-9 | wphelper is the canonical connector home; other repos import rather than duplicate. **Violated by ai-assistants** (L-AA-1) | wphelper `src/wphelper/`; memory `project_wphelper_is_connector_home` |
| I-10 | wphelper does not author content; orchestrating primitives is OK | memory `project_wphelper_orchestration_ok` |
| I-11 | GS is the **sole writer** of research `grants` rows (990-PF, Schedule I, 360Giving, CFCSRA); AG never writes them. A writer census test pins the set | GS `services/irs_990_ingestion.py:348`, `services/irs_persistence.py:732`, `services/three_sixty_giving_ingestion.py:230`, `services/cfcsra_sync.py`, `tests/services/test_grant_source_backfill.py` |
| I-12 | Architect decisions address every audit finding in a STOPPED_FOR_INPUT report, not just the headline | memory `feedback_architect_decision_completeness` |
| I-13 | Tests do not patch module globals when the fix is to expose the dependency as a parameter | `playbook.md:30`; `shared/references/architecture-principles.md` §Dependency Seams |
| I-15 | Issues touching data-contract surface or the workflow name the test that would fail if the change were wrong (norm; not mechanized) | this document, 2026-04-25 |
| I-16 | Required CI checks are mostly off, by design: null on AG main/staging, GS main, OverSteward master, fiscus main. **Exceptions:** GS `staging` requires `ci`; gaudi main requires lint/security/test | GitHub branch-protection API, 2026-10-31; `.github/workflows/ci.yml:10-12` |
| I-17 | Long Neon writes reconnect and commit per batch: `with_reconnect()` invalidates a dropped pooler connection and retries | GS `src/grantspider/connectors/neon.py:95-146` (also `services/sqlite_migrate.py:265` `_bulk_upsert`) |
| I-18 | `grantspider.ontology` must not import `services`, `connectors`, `cli`, `orchestration` — lint + pre-commit | GS `scripts/lint/check_ontology_imports.py:41`, `.pre-commit-config.yaml:64-72` |
| I-19 | AG production pins only GS `main` SHAs, via the human-gated draft bump PR (§2) | GS `notify-ag-on-main.yml`; AG `bump-gs-pin.yml:79,212` |
| I-20 | `main ⊆ staging` in **both** GS and AG; back-merges are true merges, never squash. Each repo's `divergence-watchdog.yml` (push + daily 13:00 UTC) fails and files an issue on divergence | GS and AG `.github/workflows/divergence-watchdog.yml` |
| I-21 | One git worktree per session via `scripts/dev/new-session.sh` → `session/<name>`; `guard_main_worktree.py` refuses checkout/switch in the primary tree. OverSteward links the kit from `shared/`; other repos carry copies, currently drifted (L-DEV-1) | `shared/scripts/dev/new-session.sh:44`, `tests/test_deployed_links.py` |
| I-22 | AG staging and production share **one** tenant Postgres, and with it production's `DatabaseCache` table: a write via staging is a production write. Rendered-output keys go through `env_scoped_cache_key` (`CACHE_KEY_ENVIRONMENT`); some keys do not and are shared across environments (`magic_link_used:*`, `notification:email:last_sent:*`) | AG `config/settings/base.py:317-324` (#1701), `config/settings/production.py:37-41`, `apps/accounts/magic_link.py:17`, `apps/core/notifications.py:167` |

I-14 (AG working-hours boundary) was retired 2026-07-11.

---

## §4 Known liabilities

| ID | Liability | Owner | Tracking |
|---|---|---|---|
| G1 | The drift check covers the `_generated.py` mirror, not `_views.py`, which is AG's real read surface. The check also exits 0 when the GS schema snapshot 404s | aigranthelper | `scripts/tools/check_research_drift.py`; data contract §8.3 |
| G4 | Expired profile enrichments are served on purpose with an "as of" stamp (GS#2459); refill runs only from in-session drains (no scheduled refill) | grantspider | `ag_research_views/__init__.py:260-271`, `services/enrichment_reaper.py` |
| G5 | User signals (UserFunderSignal saved/dismissed, match feedback) live in AG tables, but nothing exports them to GS | aigranthelper | `apps/pipeline/models.py:610`; data contract §12 |
| H1-2 | `/project-status` metrics partial: no issue→merged cycle time, no self-critique fire rate | oversteward | `TODO_BACKLOG.md` H3-4, H3-6 |
| L-OD-1 | Dormant OneDrive checkouts await triage-then-delete | oversteward (ops) | OS#58 (open) |
| L-DISP-1 | **exchequer** `main` has no branch protection. Every other private dispatch repo has protection with `enforce_admins` | exchequer | GitHub API, 2026-10-31 |
| L-AG-2 | AG's primary-checkout `.env` was found 2026-08-05 to hold a `DATABASE_URL` for a deleted Neon project. **Unverified since**: the credential hook rightly blocks probing it. AG's `backup_database` ABOUTME and `docs/CROSS_REPO_SCHEMA.md` still describe a Neon tenant DB | aigranthelper | `apps/ops/management/commands/backup_database.py`, `docs/CROSS_REPO_SCHEMA.md` |
| L-AG-3 | AG test settings accept any DB host, and a failed connect can render the password into a pytest traceback; no host guard, no redaction | aigranthelper | `config/settings/test.py:25-65`, `tests/conftest.py` |
| L-AA-1 | ai-assistants keeps its own WP REST client and FTP module beside the wphelper dependency (I-9) | ai-assistants | `src/almoner/wp/api.py` (363 lines), `src/almoner/wp/ftp.py` |
| L-DEV-1 | Dev-family copies drift: `new-session.sh` is one version behind in every repo; exchequer's `guard_main_worktree.py` differs; `worktree_doctor.py` is absent in wphelper, ai-assistants, exchequer, gaudi and pre-#571 in AG, GS, fiscus | oversteward | `/sync-status`; OS#572 |
| L-FI-1 | Fiscus andon aggregation is a Phase-0 stub, and the AG/dispatch subject contracts are `status: stub`; exchequer and gaudi lack the andon template | fiscus | Fiscus `src/fiscus/andon.py:20-27`, `subjects/*/contract.yaml` |
| L-EX-1 | Exchequer: Railway connector live-unverified, cron unwired, `_ASSUMED_PRO_INFERENCE_COGS = 4.0` hardcoded; `expenses.csv` partly hand-seeded | exchequer | exchequer `src/exchequer/connectors/railway.py:2`, `src/exchequer/services/pull.py:38` |
| L-WSL-1 | Docker Desktop volumes (compose databases) live in the `docker-desktop` distro, outside both the monthly export and the daily restic of `/home/natha`. OS#581–583 shipped the backups and closed; **nothing open tracks this gap** | oversteward (ops) | `documentation/runbooks/wsl-recovery.md:192` |
| L-DOC-1 | Dead pointers: `documentation/issue-to-pr-workflow.md` and `documentation/repos/` never existed but are cited by `ROADMAP.md` and `DETERMINISTIC_AGENTS.md`; the dispatch skill's description omits oversteward as a target; `SKILL.md:79` and `playbook.md:36` disagree on whether an open `docs/issue-` PR blocks dispatch | oversteward | `documentation/ROADMAP.md:62,2282`, `shared/skills/dispatch/SKILL.md:3,79` |

---

## §5 Recent architectural moves

Rolling, capped at ~10. Git history holds the rest (`git log -p -- architecture.md`).

| When | What changed | Source |
|---|---|---|
| 2026-10-31 | **This refresh (OS#638).** Rows corrected against code: §2 read path (views, not ontology), I-7, I-11, I-16, I-17, I-20, the fiscus path, L-DISP-1. Retired as resolved: G2/G7 (GS stage-health + freshness SLAs + `/stage-health`), G6 (`embedding_source_hash`, GS `models/foundation.py:569`), L-GS-1 (`mine_urls` tables are written again by the crawlers). Added I-22 and L-AA-1, L-DEV-1, L-FI-1, L-DOC-1 | this PR |
| 2026-10-10 | OverSteward's deployed hooks, agents, dispatch skill and dev scripts became symlinks into `shared/` | OS#576, `tests/test_deployed_links.py` |
| 2026-10-11/14 | Laptop backup stack: readiness-gated monthly WSL export, daily restic of `/home/natha`, `backup_health.py` sweep | OS#581–583, `src/oversteward/backup/` |
| 2026-10-10 | Post-merge cleanup standing-authorized via `worktree_doctor.py cleanup-merged`; deployment to other repos open (OS#572) | OS#571, `shared/scripts/dev/worktree_doctor.py` |
| 2026-07 | GS Dagster code-location split adds a `dagster-code` gRPC service; `railway.toml` calls it inert until the operator cuts over | GS #1829, `railway.toml` |
| 2026-09-02 | Expired profile enrichments served with a staleness stamp instead of hidden | GS #2459 |
| 2026-07/08 | AG tenant DB moved off Neon to Railway Postgres 17 (AG#1348, closed 07-30); staging and prod share it, so cache keys were environment-scoped (AG#1701, 08-20) | AG `config/settings/base.py:217,317-324` |
| 2026-07-11 | I-14 retired (AG work no longer clock-gated) | Nathan |
| 2026-07-02 | Telegram removed; Happy is the operator transport; the Telegraph membrane kept | OS #180 → PRs #186, #187 |

---

## §6 Maintenance protocol

- **Read at:** scope/plan time. Skim §1-2 for orientation, grep §3-4 for the surface you're touching.
- **Verify the propagation surface exists before scoping cross-repo / "propagate through Y" work.** `git grep` for the managed-block markers or the seam named in §2 and confirm the consumer actually reads it. If the surface is absent, **building it is part of this work, not a follow-up**. (OS#129.)
- **Update at:** any session that learns a row is wrong, lands a §2/§3-surface PR, or discovers a new invariant or liability.
- **Cite or omit:** every row carries a source a reader can open. If you can't cite it, it doesn't belong here.
- **Verify against code, not against this doc.** Read the producer and consumer on their default branch on origin (`git show origin/<branch>:<path>`); primary checkouts run stale.
- **Size:** the ~2k target is exceeded. Do not keep appending — the next growth splits this into an index plus per-repo files.
- **Routine in-session pickup does not require this doc.** Single-issue work reads the issue body and `shared/skills/dispatch/playbook.md`.

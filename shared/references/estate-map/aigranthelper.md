<!-- Generated from estate-map.yaml by `scripts/estate_map.py render --write`. Do not edit by hand: a test compares this file with a fresh render. -->

# Estate map — aigranthelper

**North star.** Provide A+ grant-writing tools to the servants of the poor: the food pantries, parishes and small charities who work on shoestring budgets and are not grant experts. It is not about the money; it is about the people.

This repo's share of OverSteward's `estate-map.yaml`. A wrong row is fixed in the map, never here.

## Capabilities (`id` · status · purpose, then current → target shape)

Each current shape is its first sentence; the full measurement is in the map.

- `ag.research` · live · Research reads: the read-only mirror of GS's research schema and the plumbing every research read goes through.
  - 40 modules, 8,457 lines; 72 feature PRs touched them in 90 days. → `services/__init__.py` and `constants.py` split along capability lines: search into ag.funder-search, indexability and hub lists into ag.search-indexing, page constants into ag.funder-pages. This capability keeps the mirror, the router and the read primitives.
- `ag.funder-search` · live · Funder search and match scoring: keyword, semantic and hybrid search, Typesense with a Postgres fallback, and funding-fit scoring.
  - 24 modules, 3,993 lines; 10 feature PRs in 90 days. → hold
- `ag.funder-pages` · live · Funder pages: foundation and federal-grant profiles, the search pages, and state, sector and city hubs.
  - 41 modules, 10,799 lines; 63 feature PRs in 90 days. → Thin views over research services: views parse the request, call one service per page, and render. Profile and gov-detail context assembly moves into services; the copied cache-control helpers give way to one in `apps/core/cache_headers.py`.
- `ag.search-indexing` · live · What Google may index and how it learns of it: sitemaps, the indexability tier, IndexNow, URL Inspection sweeps and the indexation experiments.
  - 29 modules, 5,726 lines; 30 feature PRs in 90 days. → hold
- `ag.edge` · live · The Cloudflare edge: Cache-Control headers and cache rules, purges, the warmer, the origin lock and the Web Bot Auth key directory.
  - 18 modules, 2,196 lines; 14 feature PRs in 90 days. → One anon/authed Cache-Control helper in `cache_headers.py` that every public view calls (L-AG-5).
- `ag.landing-pages` · live · Conversion pages: the CMS-edited home page, its try-it widget and walkthrough recorder, and the /grants-for/ lead pages.
  - 21 modules, 5,506 lines; 18 feature PRs in 90 days. → hold
- `ag.home-ab-testing` · live · A/B testing on the home page, the estate's experiment surface: hashed arms at the edge, GA4 reads, a per-arm report.
  - 4 modules, 1,281 lines, plus the `edge/home-arm/` Worker; 3 feature PRs in 90 days. → hold
- `ag.pipeline` · live · The grant pipeline: programs, saved funders, contacts, applications, awards and deadlines, and the dashboard over them.
  - 44 modules, 10,420 lines; 54 feature PRs in 90 days. → Thin views over pipeline services: the ORM reads and the dashboard and funder-card assembly move into `services/` (where `dashboard.py` and `pipeline.py` already live); views parse, call, render.
- `ag.reporting` · live · Post-award compliance: reporting requirements, deadlines and reminders, iCal export, and the weekly org digest.
  - 33 modules, 3,170 lines; 13 feature PRs in 90 days. → hold
- `ag.matchmaker` · live · Match quality measurement: impression and interaction telemetry, self-reports, golden labels and offline evals.
  - 33 modules, 5,175 lines; 6 feature PRs in 90 days. → hold
- `ag.studio` · live · Grant Studio: AI-assisted drafting with versioned drafts in B2, question workshops and QA checks; Anthropic, Gemini, OpenAI via one module.
  - 52 modules, 8,067 lines; 21 feature PRs in 90 days. → hold
- `ag.accounts` · live · Accounts: multi-tenant organizations, consultants, magic-link sign-in, onboarding and account deletion.
  - 57 modules, 10,871 lines; 56 feature PRs in 90 days. → hold
- `ag.billing` · live · Billing: Stripe via dj-stripe, plans and plan switches, passes, gifts and trials, renewal and beta notices.
  - 33 modules, 8,353 lines; 50 feature PRs in 90 days. → hold
- `ag.platform` · live · Request plumbing every app shares: tenancy middleware, role and lapsed-access enforcement, internal auth, abuse guards, storage.
  - 30 modules, 3,048 lines; 29 feature PRs in 90 days. → One cron check-in helper here that the 11 commands call (L-AG-4); the tables in `models.py` move to the apps whose capabilities own them.
- `ag.notifications` · live · Notifications and mail: routed notification channels, the staging allowlist, and the mail outbox with its drain.
  - 4 modules, 811 lines; 1 feature PR in 90 days. → hold
- `ag.ops` · live · Operator surface: the ops dashboard and experiment tracker, `/internal/ops/` reports and verdicts, the load test, DB backup and scratch.
  - 24 modules, 2,523 lines; 10 feature PRs in 90 days. → hold
- `ag.acquisition-analytics` · live · Acquisition measurement: GA4 server-side events, first-touch attribution, the signups-from-funder-pages KPI, the GEO probe.
  - 7 modules, 1,045 lines; 6 feature PRs in 90 days. → hold
- `ag.feedback` · live · Feedback: in-app bug reports, visitor data corrections exported to GS, and captured email leads.
  - 13 modules, 1,510 lines; 12 feature PRs in 90 days. → hold
- `ag.telemetry` · live · Telemetry: one emit() for page, auth and billing events, the pipeline-history JSONL, its B2 archive, and the JWT pull Fiscus reads.
  - 19 modules, 1,659 lines; 5 feature PRs in 90 days. → hold
- `ag.worldmodel` · live · Customer world model: belief-shaped state, goals and context assembled on demand, over an append-only event spine.
  - 14 modules, 786 lines; 3 feature PRs in 90 days. → hold
- `ag.help-centre` · live · The help centre: DB-backed articles written as PR-gated drafts by the docs-author agent, with captured screenshots and drift checks.
  - 33 modules, 5,112 lines; 30 feature PRs in 90 days. → hold
- `ag.dev-gates` · live · AG's gates and release tooling: make verify, test settings, CI ratchet counters, the promotion check, the GS pin bump.
  - 7 modules, 1,251 lines, living in `apps/core/` beside product code; 4 feature PRs in 90 days. → hold
- `ag.search-acquisition` · live · Google Search as AG's first customer: the indexable funder-page corpus, offered by sitemap and judged by Search Console.
  - Last measured for epic OS#421 (2026-08-31): indexed pages fell from 66,010 (Jun 11) to 1,605 (Aug 20), and 30 of 40 sampled pages among the 7,108 enriched pages then in the sitemap were unknown to Google. → Every enriched funder page fetched by Google and its indexation read weekly; the indexable set grows by fixing the crawl, never by shrinking it (Nathan, 2026-10-30).
- `ag.search-measurement` · live · Judging shipped pages by Search Console and GA4 through the CLIs: indexation sweeps, per-arm reads, funnel events.
  - Sessions read GSC and GA4 through `wphelper gsc` and `wphelper analytics`, never an MCP server (cli-connection-standard.md). → hold
- `ag.page-red-teaming` · building · Gemini red-teams a page shape before it is built, on static design-bench renders judged under the rater and seeker rubrics.
  - OverSteward's half shipped (#422, #423, #427). → AG#1858 closed, so every page-shape PR publishes a bench render and carries a judge verdict before it ships.
- `ag.resource-outreach` · live · Resource-page outreach: monthly Brave discovery of grant-resource sites, reviewed drafts, and weekday listing-request emails.
  - Scripts and ledgers sit untracked in the primary checkout (L-MKT-1). → The pipeline in a tracked, tested home with its ledgers outside git, so a send is reviewed code (L-MKT-1).

## Seams

- S-1 grantspider → aigranthelper (data): AG reads the research DB through **`ag_research.*` views and functions** (26 unmanaged `_v` models, plus search/match SQL functions), connecting with the read-only `ag_research_reader` role. Nine documented base-table reads remain, each tagged `READS-BASE-TABLE:`. `grantspider.ontology` supplies one type (`NteeCode`) and is not the read path
- S-2 grantspider → aigranthelper (code): AG pins GS by SHA (`requirements.txt:463`, matched by `research_schema.lock`) and imports `grantspider.models`, `connectors.b2_storage` and `services.db_backup` at runtime. A push to GS main fires `repository_dispatch: gs-master-bump`; AG's bump workflow rejects non-`refs/heads/main` refs and force-updates one draft PR onto AG `staging`
- S-3 grantspider → aigranthelper (schema drift): AG CI diffs `_generated.py` against GS `schema/research.sql` at the locked SHA. `_views.py` is not checked (G1)
- S-4 aigranthelper → grantspider: Visitor data corrections: AG serves export + ack at `/internal/corrections/`; GS pulls them into pinned overrides
- S-5 wphelper → aigranthelper, ai-assistants: Connector library: AG pins it by SHA (`requirements.txt:472`) for IndexNow + GSC; ai-assistants depends on it but still duplicates WP REST/FTP (L-AA-1)
- S-6 oversteward → all repos: `registry.yaml`; `shared/` deployed to both `~/.claude` homes; the dev family by sow PRs. In OverSteward the deployed side is symlinks, elsewhere copies
- S-7 aigranthelper → fiscus: Paginated NDJSON telemetry at `GET /internal/telemetry/`, RS256 JWT
- S-9 pickup repos → fiscus: `andon`-labelled issues → `shared/andon.jsonl`. **The aggregator is a stub that only echoes** (L-FI-1)
- S-12 aigranthelper → oversteward: `/internal/ops/reports/` read and `/internal/ops/verdicts/` write, bearer tokens

## Invariants

- I-4: aigranthelper never writes the research DB: read-only Neon role, and the DB router's `allow_migrate` returns `False` for every research label unconditionally (AG `apps/core/db_router.py:34-46`, `config/settings/base.py:283`)
- I-5: AG copies of producer fields declare Snapshot or Cache at definition. Partly kept: `foundation_name`/`grantor_name` copies are labelled; `FunderRelationship.accepts_unsolicited`, `typical_award_range_*`, `application_deadline` are not (AG `apps/pipeline/models.py:136,154-157,545,696,749`; data contract §3)
- I-6: Data-contract §7 fields are not removed/renamed/re-meant without the §8 dual-write procedure (data contract §7-8)
- I-9: wphelper is the canonical connector home; other repos import rather than duplicate. **Violated by ai-assistants** (L-AA-1) (wphelper `src/wphelper/`; memory `project_wphelper_is_connector_home`)
- I-18: `grantspider.ontology` must not import `services`, `connectors`, `cli`, `orchestration` — lint + pre-commit (GS `scripts/lint/check_ontology_imports.py:41`, `.pre-commit-config.yaml:64-72`)
- I-19: AG production pins only GS `main` SHAs, via the human-gated draft bump PR (§2) (GS `notify-ag-on-main.yml`; AG `bump-gs-pin.yml:79,212`)
- I-20: `main ⊆ staging` in **both** GS and AG; back-merges are true merges, never squash. Each repo's `divergence-watchdog.yml` (push + daily 13:00 UTC) fails and files an issue on divergence (GS and AG `.github/workflows/divergence-watchdog.yml`)
- I-21: One git worktree per session via `scripts/dev/new-session.sh` → `session/<name>`; `guard_main_worktree.py` refuses checkout/switch in the primary tree. OverSteward links the kit from `shared/`; other repos carry copies, currently drifted (L-DEV-1) (`shared/scripts/dev/new-session.sh:44`, `tests/test_deployed_links.py`)
- I-22: AG staging and production share **one** tenant Postgres, and with it production's `DatabaseCache` table: a write via staging is a production write. Rendered-output keys go through `env_scoped_cache_key` (`CACHE_KEY_ENVIRONMENT`); some keys do not and are shared across environments (`magic_link_used:*`, `notification:email:last_sent:*`) (AG `config/settings/base.py:317-324` (#1701), `config/settings/production.py:37-41`, `apps/accounts/magic_link.py:17`, `apps/core/notifications.py:167`)

## Liabilities

- G1 (aigranthelper; `scripts/tools/check_research_drift.py`; data contract §8.3): The drift check covers the `_generated.py` mirror, not `_views.py`, which is AG's real read surface. The check also exits 0 when the GS schema snapshot 404s
- G5 (aigranthelper; `apps/pipeline/models.py:610`; data contract §12): User signals (UserFunderSignal saved/dismissed, match feedback) live in AG tables, but nothing exports them to GS
- L-AG-2 (aigranthelper; `apps/ops/management/commands/backup_database.py`, `docs/CROSS_REPO_SCHEMA.md`): AG's primary-checkout `.env` was found 2026-08-05 to hold a `DATABASE_URL` for a deleted Neon project. **Unverified since**: the credential hook rightly blocks probing it. AG's `backup_database` ABOUTME and `docs/CROSS_REPO_SCHEMA.md` still describe a Neon tenant DB
- L-AG-3 (aigranthelper; `config/settings/test.py:25-65`, `tests/conftest.py`): AG test settings accept any DB host, and a failed connect can render the password into a pytest traceback; no host guard, no redaction
- L-AG-4 (aigranthelper; `git grep -l "def _sentry_check_in_start" origin/main -- apps/` (AG f2a8d99); OS#640 comment (SMELL-002 ratchet)): The `_sentry_check_in_start/_finish` pair is copied into 11 management commands across accounts, ops, reporting, research, seo and studio; with docstrings and comments stripped the copies fall into three variants. No shared helper exists
- L-AG-5 (aigranthelper; `git grep -n "def _apply_[a-z_]*cache_control" origin/main -- apps/` (AG f2a8d99)): `city_views.py`, `sector_views.py` and `seo/lead_views.py` each copy the anon-public / authed-no-store branch that `research/views.py`'s `_apply_detail_cache_control` reaches through `_apply_read_cache_control`, instead of calling one shared helper
- L-MKT-1 (oversteward (ops); OS#644 (open); `reports/2026-10-29-resource-page-outreach/` (untracked); `systemctl --user list-timers ag-outreach*`): The resource-page outreach pipeline, which sends live email on a weekday timer, is untracked files in the primary OverSteward checkout: no review, no tests, no history. Its user systemd units point at that path, and the laptop backups (restic and the WSL export) are its only copies
- L-AA-1 (ai-assistants; `src/almoner/wp/api.py` (363 lines), `src/almoner/wp/ftp.py`): ai-assistants keeps its own WP REST client and FTP module beside the wphelper dependency (I-9)
- L-DEV-1 (oversteward; `/sync-status`; OS#572): Dev-family copies drift: `new-session.sh` is one version behind in every repo; exchequer's `guard_main_worktree.py` differs; `worktree_doctor.py` is absent in wphelper, ai-assistants, exchequer, gaudi and pre-#571 in AG, GS, fiscus
- L-FI-1 (fiscus; Fiscus `src/fiscus/andon.py:20-27`, `subjects/*/contract.yaml`): Fiscus andon aggregation is a Phase-0 stub, and the AG/dispatch subject contracts are `status: stub`; exchequer and gaudi lack the andon template

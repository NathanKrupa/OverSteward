<!-- Generated from estate-map.yaml by `scripts/estate_map.py render --write`. Do not edit by hand: a test compares this file with a fresh render. -->

# Estate map — grantspider

**North star.** Provide A+ grant-writing tools to the servants of the poor: the food pantries, parishes and small charities who work on shoestring budgets and are not grant experts. It is not about the money; it is about the people.

This repo's share of OverSteward's `estate-map.yaml`. A wrong row is fixed in the map, never here.

## Capabilities (`id` · status · purpose, then current → target shape)

Each current shape is its first sentence; the full measurement is in the map.

- `gs.research-schema` · live · Research schema: the ORM models and Alembic history GS alone writes, and the `ag_research` view manifest that is AG's read surface.
  - 89 modules, 15,425 lines; 76 feature PRs in 90 days, because nearly every feature adds a table. → hold
- `gs.ontology` · live · Ontology: typed entities (Foundation, Grant, NteeCode), semantic types and property lineage; the one GS package AG imports for types.
  - 24 modules, 4,479 lines; 11 feature PRs in 90 days. → hold
- `gs.runtime` · live · Runtime: settings (the one env reader), Neon sessions with reconnect, B2 storage, logging, Sentry, the operations ledger and the CLI root.
  - 16 modules, 2,767 lines; 48 feature PRs in 90 days. → hold
- `gs.outbound-http` · live · Outbound HTTP: one client factory composing bot identity, Web Bot Auth, robots, per-host limits and breaker; SSRF guard; the request audit log.
  - 26 modules, 6,310 lines; 14 feature PRs in 90 days. → hold
- `gs.llm-access` · live · Model access: the Anthropic connector and the provider-neutral LlmClient, each Anthropic client built only behind the metered-key arm.
  - 10 modules, 1,628 lines; 2 feature PRs in 90 days. → hold
- `gs.irs-ingestion` · live · IRS filings: TEOS cache, BMF monthly sync, SOI extract, 990-PF and 990 XML extraction, Part XV and Schedule I grant lines, officers.
  - 39 modules, 14,386 lines; 32 feature PRs in 90 days. → Repairs that have run are retired: each one-shot is deleted once `operations_ledger` shows its apply and its target set measures empty, and a scheduled backfill is renamed as the producer it is (L-GS-2).
- `gs.grant-records` · live · Grant rows after landing: 360Giving ingest, recipient EIN and NTEE, PCS coding, source precedence, reconciliation and amount repairs.
  - 21 modules, 7,875 lines; 12 feature PRs in 90 days. → Repairs that have run are retired: each one-shot is deleted once `operations_ledger` shows its apply and its target set measures empty, and a scheduled backfill is renamed as the producer it is (L-GS-2).
- `gs.facsimiles` · live · 990-PF facsimiles: the filing printed onto the IRS's own blank with Schedule B and statements, rendered with Neon idle, stored in B2.
  - 17 modules, 10,847 lines; 31 feature PRs in 90 days. → hold
- `gs.fiscal-synopsis` · live · Fiscal synopsis: a two-page funder PDF (giving line, sector box plot) rendered by WeasyPrint and stored in B2.
  - 10 modules, 2,757 lines; 6 feature PRs in 90 days. → hold
- `gs.federal-opportunities` · live · Federal openings: Grants.gov with detail hydration, SAM listings and contracts, USASpending, agency page hydration, NOFO PDFs.
  - 35 modules, 10,227 lines; 16 feature PRs in 90 days. → hold
- `gs.state-opportunities` · live · State and local openings: state portals, municipal leagues, vendor tenants (Submittable, AmpliFund, WebGrants) and RSS feeds.
  - 41 modules, 8,172 lines; 4 feature PRs in 90 days. → hold
- `gs.funder-discovery` · live · Grantmaker discovery beyond the BMF: candidate queue, corporate sweeps and giving-platform probes, corporate-direct programmes, diocesan foundations.
  - 30 modules, 6,039 lines; 4 feature PRs in 90 days. → hold
- `gs.community-foundations` · live · Community foundations: the COF locator and directory, ACF affiliates, site-platform detection, CFCSRA funds and scholarships.
  - 16 modules, 4,607 lines; 4 feature PRs in 90 days. → hold
- `gs.funder-records` · live · Funder record fields: display names from filer names, acronym casing, slugs, addresses, source labels, Haiku-beautified IRS text.
  - 21 modules, 4,397 lines; 3 feature PRs in 90 days. → Repairs that have run are retired: each one-shot is deleted once `operations_ledger` shows its apply and its target set measures empty, and a scheduled backfill is renamed as the producer it is (L-GS-2).
- `gs.entity-resolution` · live · Entity resolution: Splink, Jaro-Winkler/TF-IDF and name-cluster resolvers over an organization spine with exact-EIN edges.
  - 16 modules, 4,618 lines; 2 feature PRs in 90 days. → hold
- `gs.grantmaker-status` · live · Grantmaker status: one versioned derivation over override, disposition, behaviour and classifier signals, kept fresh by a dirty-flag drain.
  - 14 modules, 4,121 lines; 8 feature PRs in 90 days. → hold
- `gs.corrections` · live · Corrections: AG visitor corrections pulled and promoted by a human into pinned overrides; operator one-field edits with lineage.
  - 7 modules, 1,970 lines; 9 feature PRs in 90 days. → hold
- `gs.website-resolution` · live · Websites: finding each funder's site (IRS, Wikidata, Wikipedia, GiveFreely, Brave, DDG, agent proposals), verifying identity, clearing wrong ones.
  - 46 modules, 17,784 lines; 64 feature PRs in 90 days (95 counting promotions). → One resolver: the providers and the agent's proposal become candidate sources into one confirm step (fetch, identity rules, verdict), retiring the finder, find-and-confirm and CSV write paths. One verifier: the rule table and the Haiku judge as one ordered stage on the verification spine, retiring `llm_judge.py`. One evidence store: every verdict, write and clear lands in `verification_records`, and the three clearing repairs become one verb. The cohort helpers move out of `enrichment_apply.py` into a module both capabilities import.
- `gs.crawl-frontier` · live · Crawl frontier: the crawl graph (`mine_urls` + links), tiered cadence, and URL sources (sitemaps, homepage links, Common Crawl, on demand).
  - 31 modules, 9,479 lines; 21 feature PRs in 90 days. → hold
- `gs.crawl` · live · Capture: the Railway snapshot drain and the laptop crawler with its SQLite resume ledger; Wayback; markdown snapshots to B2.
  - 35 modules, 12,790 lines; 32 feature PRs in 90 days. → hold
- `gs.page-triage` · live · Page triage: URL-and-content heuristic page labels (no LLM), and the safety pass over untrusted crawl text before prompts and embeddings.
  - 7 modules, 1,291 lines; 2 feature PRs in 90 days. → hold
- `gs.enrichment` · live · Funder profiles: the enrich-drain pull and apply, the two-pass research bench, section and about passes, gates, generations and TTL.
  - The largest capability: 58 modules, 28,267 lines (16,792 code); 94 feature PRs in 90 days, 139 counting promotions. → `enrichment_apply.py` split along its seams: the cohort and pull (`CohortSpec`, `pull_batch`, the clauses website resolution imports) into one module; the generation lifecycle (archive, renew, reactivate) into `enrichment_generation.py`; the site contact and address write-through; disposition routing with its Sonnet corroboration (GS#2776). `apply_results` stays as the orchestrator. The four passes share one pull, one gate tuple and one writer.
- `gs.metered-enrichment` · live · Metered-key enrichment: the `enrich` CLI, the on-demand SKIP LOCKED queue and worker, and LLM snapshot extraction.
  - 13 modules, 3,425 lines; 5 feature PRs in 90 days. → hold
- `gs.funding-profile` · live · Funding profiles: token-free facets and prose derived from a funder's grant set, refreshed only for funders whose grants moved.
  - 11 modules, 3,744 lines; 15 feature PRs in 90 days. → hold
- `gs.giving-stats` · live · Giving statistics: per-funder fingerprints and distributions, top funders by state, city and sector, and the one sector taxonomy.
  - 9 modules, 3,040 lines; 8 feature PRs in 90 days. → hold
- `gs.deadlines` · live · Deadlines: deterministic extraction from crawled pages and the 990-PF, rolling-cue classification, and the one open-to-applications predicate.
  - 8 modules, 2,493 lines; 5 feature PRs in 90 days. → hold
- `gs.embeddings-search` · live · Embeddings and search: local all-MiniLM-L6-v2 (384-d) for funders, open opportunities and page chunks; Typesense reindexes.
  - 18 modules, 4,510 lines; 4 feature PRs in 90 days. → hold
- `gs.authority-map` · building · Funding-authority map: who passes public money down, from FAC audits and USASpending subawards, with county closure and attribution.
  - 14 modules, 4,082 lines; 23 feature PRs in 90 days. → hold
- `gs.data-quality` · live · Data quality: the write gate, nightly snapshots and drift scans, freshness SLAs, the stage-health ledger, canaries, the Vintner funnel, operator stats.
  - 43 modules, 18,616 lines; 46 feature PRs in 90 days. → hold
- `gs.safety` · live · Database safety: operator-armed prod migrations, pre-migration and weekly B2 backups, the restore drill, wipe canaries, the Neon budget canary.
  - 20 modules, 4,847 lines; 5 feature PRs in 90 days. → hold
- `gs.dagster-runtime` · live · Dagster runtime: definitions, schedules, sensors and run guards; zombie and orphan reapers; the out-of-band daemon watchdog; cron check-ins.
  - 19 modules, 5,258 lines; 20 feature PRs in 90 days. → hold
- `gs.dev-gates` · live · Dev gates: the gaudi boy-scout ratchet, migration and reader-privilege drift, Dagster lints, the pin-bump notice to AG, the divergence watchdog.
  - 15 modules, 3,439 lines; 15 feature PRs in 90 days, 13 of them on `dev/boy_scout.py`. → hold

## Seams

- S-1 grantspider → aigranthelper (data): AG reads the research DB through **`ag_research.*` views and functions** (26 unmanaged `_v` models, plus search/match SQL functions), connecting with the read-only `ag_research_reader` role. Nine documented base-table reads remain, each tagged `READS-BASE-TABLE:`. `grantspider.ontology` supplies one type (`NteeCode`) and is not the read path
- S-2 grantspider → aigranthelper (code): AG pins GS by SHA (`requirements.txt:463`, matched by `research_schema.lock`) and imports `grantspider.models`, `connectors.b2_storage` and `services.db_backup` at runtime. A push to GS main fires `repository_dispatch: gs-master-bump`; AG's bump workflow rejects non-`refs/heads/main` refs and force-updates one draft PR onto AG `staging`
- S-3 grantspider → aigranthelper (schema drift): AG CI diffs `_generated.py` against GS `schema/research.sql` at the locked SHA. `_views.py` is not checked (G1)
- S-4 aigranthelper → grantspider: Visitor data corrections: AG serves export + ack at `/internal/corrections/`; GS pulls them into pinned overrides
- S-6 oversteward → all repos: `registry.yaml`; `shared/` deployed to both `~/.claude` homes; the dev family by sow PRs. In OverSteward the deployed side is symlinks, elsewhere copies
- S-9 pickup repos → fiscus: `andon`-labelled issues → `shared/andon.jsonl`. **The aggregator is a stub that only echoes** (L-FI-1)
- S-11 grantspider → oversteward: `grantspider dq health --json` (stage health, locally or via `railway ssh`); Vintner reads `vintner.corpus_funnel_v`

## Invariants

- I-4: aigranthelper never writes the research DB: read-only Neon role, and the DB router's `allow_migrate` returns `False` for every research label unconditionally (AG `apps/core/db_router.py:34-46`, `config/settings/base.py:283`)
- I-6: Data-contract §7 fields are not removed/renamed/re-meant without the §8 dual-write procedure (data contract §7-8)
- I-7: GS data migrations use the ORM (ADR-006). **App code is not ORM-only**: ~129 `text()` calls across services/cli/orchestration/connectors, with no lint. Raw SQL must not bypass client-side defaults (GS `docs/adr/006-alembic-data-migrations-use-orm.md`; e.g. `services/address_backfill.py:164-228`)
- I-8: Pre-migration UPDATEs collapsing many rows to one value audit every sibling UNIQUE (partial + full) on touched columns (memory `feedback_migration_sibling_unique_audit`)
- I-11: GS is the **sole writer** of research `grants` rows (990-PF, Schedule I, 360Giving, CFCSRA); AG never writes them. A writer census test pins the set (GS `services/irs_990_ingestion.py:348`, `services/irs_persistence.py:732`, `services/three_sixty_giving_ingestion.py:230`, `services/cfcsra_sync.py`, `tests/services/test_grant_source_backfill.py`)
- I-16: Required CI checks are mostly off, by design: null on AG main/staging, GS main, OverSteward master, fiscus main. **Exceptions:** GS `staging` requires `ci`; gaudi main requires lint/security/test (GitHub branch-protection API, 2026-10-31; `.github/workflows/ci.yml:10-12`)
- I-17: Long Neon writes reconnect and commit per batch: `with_reconnect()` invalidates a dropped pooler connection and retries (GS `src/grantspider/connectors/neon.py:95-146` (also `services/sqlite_migrate.py:265` `_bulk_upsert`))
- I-18: `grantspider.ontology` must not import `services`, `connectors`, `cli`, `orchestration` — lint + pre-commit (GS `scripts/lint/check_ontology_imports.py:41`, `.pre-commit-config.yaml:64-72`)
- I-19: AG production pins only GS `main` SHAs, via the human-gated draft bump PR (§2) (GS `notify-ag-on-main.yml`; AG `bump-gs-pin.yml:79,212`)
- I-20: `main ⊆ staging` in **both** GS and AG; back-merges are true merges, never squash. Each repo's `divergence-watchdog.yml` (push + daily 13:00 UTC) fails and files an issue on divergence (GS and AG `.github/workflows/divergence-watchdog.yml`)
- I-21: One git worktree per session via `scripts/dev/new-session.sh` → `session/<name>`; `guard_main_worktree.py` refuses checkout/switch in the primary tree. OverSteward links the kit from `shared/`; other repos carry copies, currently drifted (L-DEV-1) (`shared/scripts/dev/new-session.sh:44`, `tests/test_deployed_links.py`)

## Liabilities

- G1 (aigranthelper; `scripts/tools/check_research_drift.py`; data contract §8.3): The drift check covers the `_generated.py` mirror, not `_views.py`, which is AG's real read surface. The check also exits 0 when the GS schema snapshot 404s
- G4 (grantspider; `ag_research_views/__init__.py:260-271`, `services/enrichment_reaper.py`): Expired profile enrichments are served on purpose with an "as of" stamp (GS#2459); refill runs only from in-session drains (no scheduled refill)
- L-GS-1 (grantspider; `git grep -n "def \(_coerce_positive_int\|_base_url_for\|_parse_us_date\|_in_list\|_check_in\|_db_url\)\b" origin/main -- src/ scripts/audits/` (GS be9ed67)): Copied helpers, identical once docstrings are dropped: `_coerce_positive_int` in `enrichment_reaper.py`, `enrichment_ttl.py` and `opportunity_reaper.py`; `_base_url_for` in `homepage_fallback.py`, `sitemap_discovery.py` and `sitemap_enumeration.py`; `_parse_us_date` in the US Chamber spider and `ga_gma.py`; `_db_url` in six `scripts/audits/` scripts. Five models render a `column IN (...)` CHECK body with `_in_list` (2) or `_check_in` (3), which differ only in quoting. `read_foundation_ids` lives in `cli/cleanup_websites.py`, and five other CLIs import it from there
- L-GS-2 (grantspider; `git ls-tree -r --name-only origin/main -- src/grantspider | grep -E "cleanup|repair|backfill|clear|rescore|reprocess"` (GS be9ed67; the `fix` stem matches only `*_fixture.py`)): 41 modules (27 services, 13 CLIs, 1 asset) are named for a cleanup, repair, backfill, clear, rescore or reprocess, and nothing retires one after it has run. 18 of them have not changed since before 2026-08-02; at least four of those are scheduled producers rather than repairs (NTEE, filer-name index, page classification). `services/operations_ledger.py` exists to stamp out-of-band ops, so a run can be proven before a repair is deleted
- L-GS-3 (grantspider; Import graph at GS be9ed67. The 23: `config/crawl_politeness.py`; `connectors/` `_rate_limiter`, `corporate_foundations/` (4), `hydration/doe_osti`, `irs_stylesheets`, `nofo_pdf_store`, `storage`; `services/` `contact_extractor`, `crawlee_bridge`, `csr_registry`, `enrichment_coverage`, `fetch_strategy_classifier`, `matcher`, `nofo_enrichment`, `nofo_prompts`, `opportunity_tracker`, `page_triage`, `pdf_extractor`, `peer_similarity`, `vendor_lifecycle`): 23 modules have no live importer: no CLI command, Dagster definition, script, Alembic file, AG import or dotted-path string reaches them, only tests. Among them are `page_triage.py`, a Haiku page labeller beside the standing rule of no LLM tokens on page classification, the NOFO summariser, the US Chamber connector package and the local-filesystem store
- L-DEV-1 (oversteward; `/sync-status`; OS#572): Dev-family copies drift: `new-session.sh` is one version behind in every repo; exchequer's `guard_main_worktree.py` differs; `worktree_doctor.py` is absent in wphelper, ai-assistants, exchequer, gaudi and pre-#571 in AG, GS, fiscus
- L-FI-1 (fiscus; Fiscus `src/fiscus/andon.py:20-27`, `subjects/*/contract.yaml`): Fiscus andon aggregation is a Phase-0 stub, and the AG/dispatch subject contracts are `status: stub`; exchequer and gaudi lack the andon template

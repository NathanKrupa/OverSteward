# Context brief: the GrantSpider / AI Grant Helper search system (read before researching)

Two repos. **GrantSpider (GS)** is a Python crawler + data pipeline (SQLAlchemy, Alembic,
Dagster on Railway) that owns the corpus in a **Neon Postgres** database. **AI Grant Helper (AG)**
is a Django SaaS that reads GS data read-only and renders search for grant writers at small
nonprofits. Budget is shoestring: no paid search SaaS, no metered LLM calls on the query path,
Neon target ~$50/month, everything self-hosted on Railway single-node services.

## Corpus shape
- `foundations`: ~300,000 rows (US IRS-derived grantmakers; name, display_name, EIN, city, state,
  NTEE code, foundation_code, asset_amount, slug, free-text enrichment prose, 384-dim embedding
  on ~293k rows). Names are IRS-abbreviated ("Lpr Charitable Tr", "Smith Family Fdn"); renames
  happen (filer_name vs name); many near-duplicate names.
- `gov_opportunities`: ~9,000 open federal/state opportunities (title, description, agency, dates).
- `grants` (Schedule I / 990-PF grant rows): hundreds of thousands to millions of rows; not yet
  a search surface but planned ("Search 206,400 grants" on the homepage).
- Enrichment prose per foundation (crawled website text summarized), stored in `enrichments`.

## Current architecture (as built, Sept 2026)
1. **Postgres-native path (fallback + semantic arm):**
   - generated `search_tsv` tsvector (weighted A/B/C/D: name, application_info, restrictions,
     enrichment text) + GIN; `pg_trgm` word_similarity on name; `unaccent`.
   - `ag_research.search_foundations_keyword(q, n)` and `search_foundations_semantic(vec, n)` are
     SECURITY DEFINER SQL functions; AG's role has EXECUTE only (no base-table SELECT).
   - `ag_research.match_foundations(vec, state, min_assets, k, include_national)` = the
     "matchmaker": filtered KNN over pgvector HNSW (cosine), `hnsw.ef_search=200`,
     `hnsw.iterative_scan=relaxed_order`. Measured 1.7–2.8 s on prod vs a "tens of ms" target;
     eligibility predicate (`is_active_grantmaker AND foundation_code<=4 AND country='US'`)
     passes ~60% of rows, so post-filtering wanders. Candidate fixes unranked: partial HNSW
     index, ef_search tuning, pgvector 0.8 max_scan_tuples, materialized eligibility column.
   - AG fuses keyword + semantic with weighted **reciprocal rank fusion**, with a **name tier**
     promoted above RRF (exact/prefix name matches), and an EIN short-circuit before search.
2. **Typesense path (primary keyword search since ~Aug 2026):**
   - Single `typesense/typesense:30.2` container on Railway (AG project), persistent volume,
     ~203k foundation docs + ~9k gov docs. Fields: id, ein(num_typos:0), name, display_name,
     city, state(facet), ntee_code(facet), foundation_code(facet), country, asset_amount(facet,
     int64 sort), slug. No embeddings in Typesense yet (Phase 2 idea: push vectors, retire
     pgvector for search).
   - GS rebuilds **nightly via alias-swap full reindex**: create `foundations_<ts>`, batch
     upsert everything, repoint alias `foundations`, prune old collections. Takes **3.5–4 h**
     for 203k docs (slow!), gets killed by a Dagster zombie reaper at 45 min on some nights,
     leaving a half-built orphan collection and a served corpus 2+ nights old. No incremental
     updates, no CDC, no reconciliation check beyond "alias resolves".
   - AG queries the alias with a search-only key, `query_by=name,display_name,ein`, filter_by
     for state / min_assets / foundation_code<=4 / country=US; fails open to Postgres path
     (2 s connect timeout) if Typesense is down. So **two ranking paths can disagree**.
3. Freshness: foundations change slowly (IRS data yearly, enrichment drains continuous,
   display_name backfills in bulk). Gov opportunities change daily (close dates).

## Known open problems we want the research to speak to
- Index ↔ database **consistency/freshness**: full rebuild is slow and fragile; how do mature
  projects keep a derived search index consistent with a Postgres source of truth (CDC,
  outbox, watermarks, incremental upsert with tombstones, blue/green aliases, reconciliation
  and count-parity canaries, resumable/checkpointed reindex)?
- **Two-engine drift**: keyword in Typesense vs semantic in pgvector vs fallback FTS — results
  and ranking differ by path. Is a single engine (hybrid inside Typesense / Meilisearch /
  Vespa / OpenSearch / ParadeDB-in-Postgres) the better shape at this scale?
- **Filtered vector search** recall/latency (the #2025 problem).
- **Entity/name search quality**: IRS abbreviations, renames/aliases, typo tolerance, exact
  EIN, near-duplicate names; synonyms/abbreviation dictionaries; how do open-source entity
  matchers (OpenSanctions yente/nomenklatura, Splink, dedupe) approach this?
- **Evaluation**: a golden query set + offline metrics (ranx, ir_measures, BEIR-style) so a
  ranking change is measured, not eyeballed; zero-result and click logging.
- **Ops on a small box**: RAM sizing, snapshots/backups, restore, version upgrades, single-node
  durability; what does each engine need at 300k–5M docs?
- Licensing must be genuinely open source or source-available with free self-hosting.

Deliver evidence with URLs (docs pages, GitHub repos, issues, blog posts), note release
cadence / last commit / license / stars where relevant, and be explicit when something is
your inference rather than documented fact. Flag anything that would be a bad fit and why.

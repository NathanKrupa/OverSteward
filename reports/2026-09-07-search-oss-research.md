# Open-source search research for the GS/AG search system

Date: 2026-09-07. Five research lanes (engines, consistency, ranking, Postgres-native,
domain references) ran in parallel against a shared brief; their full findings, every
claim URL-backed, are in `reports/2026-09-07-search-oss-research/`. This document is the
synthesis, plus one measured finding the lanes could only guess at.

## 0. Bottom line

1. **The 3.5-hour nightly reindex is a one-line bug, not an engine or transport problem.**
   `iter_foundation_documents` omits `display_name` from `load_only`, and the mapper's
   `getattr` lazy-loads it once per row: 203k round trips to Neon. Measured on the bench:
   201 SQL statements for 200 rows as shipped, 1 with the column loaded. Filed as
   **GS#2597** (`ready-for-agent`); it is the root cause of the zombie-reaper kills in
   GS#2551 and the two-nights-stale corpus. Fix this before any architecture change.
2. **Keep Typesense. Do not switch engines to fix a producer bug.** Meilisearch is the
   standby target if Typesense stalls (no stable release since v30.2 on 2026-04-19, 878 open
   issues, commit rate down ~4x this quarter). Re-check at year end.
3. **Consistency: the nightly alias-swap is the vendor-documented shape; it lacks a gate,
   a stamp, and a janitor.** Add a blocking parity check before the swap (total count and
   per-state facet counts vs Postgres, two-sided), stamp `built_at` and `expected_doc_count`
   in the collection metadata, sweep orphans on start, and alarm when the served collection
   is older than 36 h. Then add a watermark-upsert lane for gov opportunities. Decline CDC:
   a logical-replication subscriber pins Neon compute awake (floor about $20/month).
4. **The highest-leverage quality change is a schema change, not a ranking change:** one
   multi-valued aliases field (every historical `filer_name`, IRS-abbreviated and expanded
   forms) plus a US-charitable abbreviation dictionary applied at index time. No public
   nonprofit search has this: ProPublica returns 140 results for "Smith Family Foundation"
   and 1 for "Smith Family Fdn".
5. **#2025 (filtered KNN at 1.7–2.8 s):** at 60% selectivity with `ef_search=200` the
   post-filter cannot be starving, so `max_scan_tuples` tuning will do nothing. Read
   `EXPLAIN (ANALYZE, BUFFERS)` twice first; then a partial HNSW index on the constant
   eligibility predicate; then `halfvec`. Neon's new `lakebase_ann` (prefilter, storage-
   resident index) is worth a timeboxed spike but is proprietary and unbenchmarked.
6. **Evaluation costs a day:** turn on Typesense analytics (`nohits_queries`,
   `popular_queries`), log `is_zero_result` per query, hand-judge 100 queries, and gate
   nDCG@10 with `ranx` in pytest. Replace RRF with a normalized convex combination only
   once that gate exists; published comparisons put RRF last among fusion methods.
7. **Time-sensitive item, no action needed:** Neon removes ParadeDB `pg_search` on
   2026-09-21. GS does not use it (verified by grep). ParadeDB-on-Neon is off the table.

## 1. Where the system stands (read from the code, not the design doc)

| Path | Engine | Serves | Fusion / tiering | Freshness |
|---|---|---|---|---|
| Typesense keyword | `typesense:30.2`, single node, AG Railway project | AG foundation + gov text search | Typesense text match; `query_by=name,display_name,ein` | Nightly alias-swap full rebuild, 3.5–4 h, reaped some nights |
| Postgres keyword (fallback) | `search_tsv` GIN + `pg_trgm` via SECURITY DEFINER fn | Fallback when Typesense unreachable (2 s timeout) | AG: name tier above weighted RRF | Transactional |
| Postgres semantic | pgvector HNSW, `ef_search=200`, iterative scan | Hybrid arm + matchmaker `match_foundations` | Same RRF; matchmaker separate | Transactional; embeddings drain |

Three query paths carry two eligibility definitions (Typesense `filter_by` vs the SQL
predicate inside the functions), the name tier lives only in AG's Python, and the fallback
path has no facet counts. Those are the drift generators, and none of them is the engine.

## 2. The measured finding: the reindex lazy-loads one column per row

`services/foundation_search_index.py` streams with `load_only(*_INDEXED_COLUMNS)` and
`yield_per=1000`. `_INDEXED_COLUMNS` lists nine columns and omits `display_name`.
`foundation_to_document` then reads `getattr(foundation, "display_name", None)`. That guard
predates GS#1560; the column and the indexer merged the same day (2026-06-29), so from the
first real run the attribute has existed as a deferred column, and SQLAlchemy emits one
`SELECT display_name WHERE id = ?` per row.

Probe on the compose bench (`probe_lazy_load.py`, rows inserted in a rolled-back transaction,
`before_cursor_execute` listener):

```
rows_scanned=200 probe_rows=200 statements_as_shipped=201 statements_with_display_name_in_load_only=1
```

At roughly 60 ms per Neon round trip, 203k rows is about 3.4 hours, which is the observed
duration. Typesense's own benchmark is about 10,000 docs/sec; the gov indexer (9k docs,
about a minute) does not have the pattern. Lanes 1 and 2 hypothesized transport, batch size
and OFFSET pagination; all three are wrong for this job, though their diagnostic (time one
10k-document import call in isolation) remains the right habit.

Consequences once fixed: the rebuild should take minutes, the 45-minute reaper becomes
irrelevant, the orphan collections stop appearing, and Typesense backups become
unnecessary because rebuild-from-Postgres is cheap. GS#2551's per-batch heartbeat is still
worth shipping as defence.

## 3. Engine landscape

Lane 1 rubric'd thirteen engines with live GitHub and PyPI data. The short version:

| Engine | License | Latest release | Hybrid in one call | Typo tolerance | Verdict |
|---|---|---|---|---|---|
| Typesense | GPL-3.0 | v30.2, 2026-04-19 | yes (rank fusion, `alpha`) | best in class, per-field `num_typos` | keep; watch cadence |
| Meilisearch | MIT + BUSL (sharding only) | v1.53.2, 2026-09-07 | yes (`semanticRatio`) | excellent; synonyms limited | standby migration target |
| Manticore | GPL-3.0 | 29.0.2, 2026-08-14 | yes (RRF, KNN prefilter) | good | spike for the future `grants` surface |
| OpenSearch | Apache-2.0, Linux Foundation | 3.8.0 | yes (normalization or RRF processor) | weak (`fuzziness`) | JVM on a 2–4 GB box; no |
| Elasticsearch | AGPL/ELv2/SSPL | 9.5.3 | yes | weak | no (AGPL + feature tiers) |
| Vespa | Apache-2.0 | weekly | best | weak | needs 4–5 GB to boot; no |
| Quickwit | Apache-2.0 | 0.9.0 | partial | none | no document updates; disqualified |
| Weaviate / Qdrant | BSD / Apache | current | yes | weak / none | vector DBs with bolt-on BM25; no |
| ZincSearch | Apache-2.0 | 2024-01 | no | none | repository archived; dead |
| ParadeDB pg_search | AGPL-3.0 | 0.25.6 | in SQL | fuzzy | removed from Neon 2026-09-21 |

Points that change decisions:

- Typesense accepts externally computed 384-dim vectors (`num_dim: 384`) and does
  filtered vector search with `flat_search_cutoff`, so pushing the pgvector arm into
  Typesense is feasible at about 0.8 GB RAM. Its rank-fusion issues #2162 and #2163 are
  closed (2025-01-30 and 2025-06-30; lane 3 reported them open, which was wrong), but the
  engine still does not expose per-arm ranks, so fusion inside Typesense is less
  controllable than fusion in our own code.
- Typesense has no object-storage snapshot target; a snapshot on the Railway volume it
  protects is not a backup. With a minutes-long rebuild this stops mattering.
- Meilisearch's ordered ranking rules (`exactness` as a lexicographic tier) express AG's
  name tier declaratively, and its async task queue makes a slow producer loop impossible
  to confuse with the engine. Its synonym limits (one-way, 3-word terms, 50 per term,
  silent truncation) are a poor fit for an abbreviation-heavy corpus.
- Nightly full rebuild is a choice, not a Typesense requirement: `emplace`,
  `PATCH ?filter_by` and `DELETE ?filter_by` already support incremental upsert and
  tombstones.

## 4. Consistency: keeping a derived index honest

Lane 2's patterns matrix, compressed to what applies at 300k slow-changing documents on a
$50 Neon budget:

| Pattern | Complexity | Failure mode | Who uses it |
|---|---|---|---|
| Blue/green rebuild behind an alias | low | orphan index; no resume; stale for the build window | Typesense, Meilisearch `swapIndexes`, Solr, Algolia, yente, Simpler.Grants.gov |
| Watermark upsert + tombstones | low–medium | out-of-order commits skip rows forever; eligibility flips invisible if scanning the eligible view | Typesense's own guide; USAspending |
| Trigger-based outbox | medium | write amplification | Debezium outbox; Simpler.Grants.gov built then deleted it |
| CDC via logical decoding | high | slot retains WAL until the DB stops; Neon drops idle slots after ~40 h; compute pinned awake | Debezium, PGSync (Elasticsearch only) |
| Index inside Postgres | lowest | search RAM/CPU on the OLTP box; extension availability | pgvector, tsvector (already ours) |

What to do, in order (each is days, none adds a bill):

1. Fix GS#2597, then keep the nightly alias-swap. Algolia's guidance for its equivalent is
   "1–3 times a month"; ours becomes cheap enough that nightly is fine and it bounds any
   drift to 24 h, which is the rebuild's most underrated property.
2. Parse the import response and count successes per batch. Typesense's import endpoint
   returns HTTP 200 regardless of per-document failures; today a truncated collection can
   be swapped in unnoticed.
3. A `@asset_check(blocking=True)` before the alias repoint: `num_documents` and per-state
   facet counts vs Postgres, two-sided threshold (larger-than-source means the janitor is
   failing). Ship it with a negative fixture (delete 50 docs from a scratch collection and
   watch it go red).
4. Stamp collection `metadata` at creation (`build_id`, `built_at`, `source_max_updated_at`,
   `expected_doc_count`); the liveness sweep can then alarm on a served collection older
   than 36 h with one HTTP call.
5. Orphan janitor on start; drain window before deleting the previous collection.
6. One eligibility definition: a stored `is_search_eligible` boolean on `foundations` that
   the indexer, the three SQL functions and the canary all read. This also enables the
   partial HNSW index in §6.
7. Gov opportunities (9k docs, daily close dates): either an hourly full rebuild
   (Simpler.Grants.gov's shape) or the first watermark-upsert lane. Scan the base table,
   not the eligible view, so an eligibility flip becomes a delete.
8. Instrument the fallback: log which path served each query and alert on the fallback
   rate. A fallback rate quietly at 100% is the "check that cannot fail" shape.

Declined: CDC. Neon documents that a connected subscriber prevents scale-to-zero; at
0.25 CU and $0.106/CU-hour that floors near $20/month, and the slot hazards land on the
production database. Revisit only if `grants` becomes a search surface.

## 5. Ranking, names and evaluation

**Fusion.** Bruch et al. (TOIS 2023) show a convex combination of min-max-normalized scores
beats RRF in and out of domain; Vespa's tutorial publishes nDCG@10 of 0.3423 for linear
fusion vs 0.3233 for RRF, barely above BM25 alone at 0.3210; Weaviate measured +6% recall
moving to score fusion and made it the default. Our exact failure (a dual-arm generic hit
outranking a single-arm exact name match) is RRF arithmetic: rank 5 in both arms scores
0.0308, rank 1 in one arm scores 0.0164. The name tier above RRF is the right instinct and
matches how Typesense (`sort_by: _eval(...)`), Meilisearch (`exactness`) and Vespa (phased
ranking) do it. The defect is that the tier exists only in AG's Python. Expressing it as a
Typesense `_eval` sort tier makes both paths tier identically.

**Names.** OpenSanctions is the reference design and it is MIT: FollowTheMoney types
`name`, `alias`, `previousName`, `abbreviation` and `weakAlias` (display-only, never
matched) as multi-valued properties; yente indexes trigrams instead of query-time fuzzy,
demotes org-class tokens ("Foundation", "Trust") to 0.7 rather than removing them, and
sets BM25 `b: 0.25` on the names field so a well-enriched record is not out-ranked by a
sparse duplicate. That last point likely applies to our concatenated weighted tsvector
today: the foundations we know most about are length-penalized. rigour's 3,559-line
org-type dictionary has zero US charitable forms, so the schema transfers and the content
must be authored, roughly 150–300 entries derivable from our own corpus by frequency-
ranking non-dictionary tokens in `foundations.name`. Apply the dictionary at index time
(the corpus is abbreviated, not the query), and reserve a synonym set for genuine query-
side equivalences. For a name rescorer over the top 50, rapidfuzz (MIT, Jaro-Winkler,
term-frequency weighting, OFAC-style best-of-all-name-pairs) beats a cross-encoder, which
has no notion that "Fdn" abbreviates "Foundation". Reserve cross-encoders (MiniLM-L6 at
about 144 pairs/s on CPU) for the prose and matchmaker surfaces.

**`ts_rank` has no corpus-level IDF.** This is a real, previously unnamed reason the
Postgres fallback ranks names worse than Typesense, independent of fusion. Document it;
do not "simplify" by retiring Typesense for pure Postgres FTS.

**Evaluation.** Turn on Typesense analytics (`--enable-search-analytics`, `nohits_queries`
and `popular_queries` rules; verify no-hit recording actually fires, issue #2419). Log
`is_zero_result` per query the way Simpler.Grants.gov does. Judge 100 queries binary (head
from popular, tail from zero-result, plus hand-written pathological cases: abbreviation,
rename, near-duplicate, EIN, leading "The", state-qualified) and gate nDCG@10 with `ranx`
in pytest, with a deliberately broken ranking as the negative fixture. `ranx` also
optimizes fusion weights, which is the tuning step the convex combination needs. Once the
beta cohort is live, Team Draft interleaving (about 50 lines) is the only online method
that reaches significance at our traffic.

## 6. Postgres-native: Neon facts and the #2025 fix order

Neon availability (from Neon's extensions table): pgvector 0.8.0, `pg_trgm`, `unaccent`,
`fuzzystrmatch`, `rum` (PG14–17 only) are available; `pg_search` is removed 2026-09-21;
`pgvectorscale`, VectorChord, `pg_bigm`, `pgroonga`, `zombodb` are absent and would mean
leaving Neon. Neon shipped **Lakebase Search** in June: `lakebase_text` (BM25 with Block-Max
WAND top-K pushdown, `tsvector`-compatible) and `lakebase_vector` (`lakebase_ann`,
IVF + RaBitQ, pgvector-API drop-in, a `prefilter` GUC, index in storage rather than compute
RAM). Every performance number is vendor marketing; both extensions are proprietary; lane 4
says PG16+ is required and the page I fetched does not state it, so verify the project's
version before a spike.

The #2025 diagnosis needs revising. With `ef_search=200` and a 60% pass rate, the first
non-iterative pass yields about 120 survivors for k=50, so the iterative scan should not be
firing and its knobs will not help. A SIGMOD 2026 study measures pgvector filtered search at
10–100 ms on 1M x 1536 vectors when memory-resident; our 293k x 384 workload should be
faster still. The gap is I/O or planning. Lane 4 blamed cold Local File Cache after
scale-to-zero. That is partly right: GS runs a 12-hour work window (12:00–23:59 UTC) and the
compute idles outside it, so AG searches in the other half of the day meet a cold cache,
while inside the window #1968 recorded a sustained ~1.5 CU background load competing for
the same cache. Either way the currency is page accesses, and page accesses on Neon can be
network round trips. Fix order:

1. `EXPLAIN (ANALYZE, BUFFERS)` on `match_foundations`, twice back to back, plus
   `neon_stat_file_cache`. If run 2 is 30 ms, it is a cache problem and no index change
   helps. Also confirm the planner is not choosing a seq scan at 60% selectivity.
2. Partial HNSW index on the constant predicate (`is_search_eligible`), documented pgvector
   guidance; the filter becomes free and the index shrinks ~40%.
3. `halfvec(384)` with a full-precision rerank of the top 200, halving the working set.
4. Spike `lakebase_ann` with `prefilter = on`, measured against 2 and 3; it targets both the
   post-filter pathology and the cold-start tail, and is one `CREATE INDEX` to try or revert.
5. Do not spend time on `max_scan_tuples` or `scan_mem_multiplier`; consider lowering
   `ef_search` to 80.

Lane 4's broader argument stands: a $50 Neon target and an always-warm vector index are
mutually exclusive. Its preferred architecture (a nightly Tantivy or SQLite FTS5 artifact
built by GS, shipped to B2, pulled by AG and swapped by file rename, so the query path
touches no network) is genuinely attractive, MIT-licensed, and builds in minutes. It is
also a new pipeline to own and loses typo tolerance. My recommendation is to defer it: fix
GS#2597 and the #2025 measurement first, and revisit the artifact option only if Typesense
stalls or `grants` needs a surface Typesense's in-memory model cannot afford.

## 7. What the domain has already learned

- **Simpler.Grants.gov** (HHS, open source, OpenSearch): hourly full refresh into a
  timestamped index with an atomic alias swap; built a trigger-based change queue, never
  rolled out the loader, and deleted it (PR #7748) because at ~10k documents a full
  refresh is cheaper. Identifiers boosted 16:1 over prose and indexed twice (tokenized and
  keyword); three request-switchable scoring profiles as a live relevancy harness; every
  query logs `is_zero_result`. No vectors at all.
- **USAspending** (CC0): the only mature incremental pattern in the domain. Watermark from a
  `last_load_date` table, a separate delete pass with its own watermark, a watermark-
  ordering assertion, extraction through a named SQL view, id-range partitions with an
  explicit null partition, and the same command doing full rebuild + alias swap. Copy it
  when the gov lane goes incremental.
- **OpenSanctions yente**: the name-search reference (§5), plus a reindex lock and
  alias-swap-only-on-verified-completion.
- **Grantmakers.io**: the closest product analogue (100k 990-PF foundations, static site,
  SEO play) uses hosted Algolia, not static search. Static/edge search (Pagefind, Orama,
  Stork) is ruled out for a 300k directory. Its facet set includes 990-PF Part XV Line 2
  ("grants only to preselected charities"), the single most valuable filter for a grant
  writer, which GS already parses and AG does not expose. It also warns that grantee names
  on Schedule I are free text with no legal-name requirement, which matters the day
  `grants` becomes a search surface.
- **grants.gov search2** returns facet counts (with nested sub-agencies) and a did-you-mean
  slot inline with every result set. Our Postgres fallback has no facet counts, which makes
  it a different product rather than a fallback.
- **OpenCorporates** demotes inactive and foreign-branch companies in score rather than
  filtering them out. Turning our eligibility predicate into a demotion is a legitimate
  alternative to filtered ANN for the matchmaker.

## 8. Recommended sequence

| Phase | Work | Repo | Notes |
|---|---|---|---|
| 0 (this week) | Fix GS#2597; ship GS#2551 heartbeat; import-success counting; blocking parity check + metadata stamp + orphan janitor + 36 h alarm | GS | Dissolves the consistency incident class; no new infra |
| 0 | `EXPLAIN (ANALYZE, BUFFERS)` twice on `match_foundations`; record in GS#2025 | GS | Decides whether #2025 is cache or index |
| 1 (weeks) | Aliases field (`string[]`, every `filer_name` / abbreviated / expanded form, weak-alias flag) in `foundations`, the indexer, `search_tsv`, and AG `query_by` with `query_by_weights` | GS + AG | Fixes GS#2311 renames, abbreviations, near-duplicates |
| 1 | US-charitable abbreviation dictionary (~150–300 entries) in rigour's three-tier shape, applied in the display_name drain | GS | Novel open-source output; a marketing claim vs ProPublica |
| 1 | Typesense analytics on; `is_zero_result` logging; 100 judged queries + `ranx` gate with negative fixture | AG | One day; prerequisite for any ranking change |
| 1 | Stored `is_search_eligible`; partial HNSW index; `halfvec` if needed | GS | Closes #2025 or narrows it to cache |
| 2 | Gov lane: hourly full rebuild or watermark upsert from the base table with tombstones | GS | USAspending's contract |
| 2 | Convex-combination fusion in `ag_research`; name tier as Typesense `_eval` sort tier; curation rules for state extraction | GS + AG | Only after the gate exists |
| 3 (decision) | Single engine: vectors into Typesense (0.8 GB, `flat_search_cutoff`, fusion opaque) vs keep pgvector; `lakebase_ann` spike; Meilisearch if Typesense has no release by year end | both | Re-read this report then |

## 9. Corrections to the lane reports

- Lanes 1 and 2 attributed the 16 docs/sec to transport, batch size or OFFSET pagination.
  The measured cause is the per-row lazy load (GS#2597). Their "time one 10k import in
  isolation" diagnostic remains good practice.
- Lane 3 reported Typesense rank-fusion issues #2162 and #2163 as open and unassigned. Both
  are closed (2025-01-30 and 2025-06-30). The concern about hidden per-arm ranks stands.
- Lane 4 modelled Neon compute as idle by default. GS's work window keeps it active about
  12 h/day, and #1968 recorded ~1.5 CU sustained load inside it; cold-cache exposure is real
  for the other 12 h. Both hypotheses stay live until the buffers are read.
- Lane 4's "PG16+ required" for Lakebase Search is not on the overview page; verify.
- GS does not use `pg_search`; the 2026-09-21 removal requires no action.

## Appendix

- `reports/2026-09-07-search-oss-research/BRIEF.md`: the shared brief the lanes read.
- `lane1-engines.md`: thirteen engines rubric'd; throughput arithmetic; answers on hybrid-
  in-one-call, incremental upsert, and object-storage snapshots.
- `lane2-consistency.md`: patterns matrix; reconciliation designs; Dagster partitioning and
  ledger shape; ranked options.
- `lane3-ranking.md`: fusion comparisons with numbers; reranker CPU throughput; OpenSanctions
  design; evaluation tooling.
- `lane4-postgres.md`: Neon availability table; Lakebase Search; #2025 analysis; three
  candidate architectures.
- `lane5-domain.md`: Simpler.Grants.gov, USAspending, yente, Grantmakers.io, ProPublica
  probes; seventeen ranked lessons.
- `probe_lazy_load.py`: the statement-counting probe behind GS#2597.

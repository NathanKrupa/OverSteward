# Lane 4 — Postgres-native search: could the whole search live inside Neon?

Research date: 2026-09-07. Every factual claim carries a URL. Statements that are my
reasoning rather than documented fact are marked **[INFERENCE]**.

---

## 0. The two findings that reframe this lane

**Finding A — ParadeDB `pg_search` on Neon dies in 14 days.**
Neon's docs state: *"As of March 19, 2026, `pg_search` is no longer available for new Neon
projects"*, existing projects keep it *"until September 21, 2026"*, when it is removed
entirely. Neon's own migration advice points at `tsvector`/`tsquery`, `pg_trgm`, `pgvector`,
and **`lakebase_text`** — or ParadeDB's standalone self-hosted `pg_search`.
<https://neon.com/docs/extensions/pg_search> · <https://neon.com/docs/changelog/2026-04-03>

So "ParadeDB inside our Neon" is **off the table**, permanently, and would have been a trap
even before that: Neon pinned `pg_search` at **0.15.26** while ParadeDB shipped 0.21.x, and
0.15.26 carries three planner-hook bugs that break exactly our use case — `paradedb.score()`
returns NULL when BM25 is combined with a SQL `WHERE`, and BM25 scores go zero/incorrect when
additional filters are applied. <https://github.com/neondatabase/neon/issues/12853>

**Finding B — Neon shipped a replacement that is a better fit than pg_search ever was.**
**Lakebase Search** went GA to *all* Neon users on **Postgres 16+**: two extensions,
`lakebase_vector` (index type `lakebase_ann`) and `lakebase_text` (index type
`lakebase_bm25`). <https://neon.com/docs/changelog/2026-06-26> ·
<https://neon.com/docs/ai/lakebase-search> · <https://neon.com/blog/lakebase-search-on-neon>

Two properties matter enormously for us, and both attack problems we actually have:

- `lakebase_ann` uses **IVF partitioning + RaBitQ quantization**, and **the index lives in
  storage rather than compute memory**, which Neon explicitly frames as *"compatible with
  Neon's scale-to-zero model without warmup requirements after cold starts"*. Claimed index
  builds **50–100× faster than HNSW**, scaling past 1B vectors.
  <https://neon.com/docs/ai/lakebase-search>
- `lakebase_ann` has a **`lakebase_ann.prefilter` GUC** that *"evaluates non-vector filters
  before distance reranking"* — i.e. genuine prefiltering, not pgvector's post-filter +
  iterative-scan dance. <https://neon.com/docs/extensions/lakebase-vector>
- `lakebase_text` works with **standard `tsvector`/`tsquery`** — no migration from our
  existing `search_tsv` — and adds true BM25 plus **top-K pushdown via Block-Max WAND**,
  which native GIN lacks (GIN scores *every* match before `LIMIT` applies).
  <https://neon.com/blog/lakebase-search-on-neon>

That last point is the direct answer to "the limits of built-in tsvector/ts_rank": it is not
just that `ts_rank` isn't BM25 — it's that GIN has no top-K pushdown, so ranking cost scales
with matches, not with `k`.

---

## 1. Neon extension availability table

Source for all rows unless noted: <https://neon.com/docs/extensions/pg-extensions>

| Extension | On Neon? | Version | Notes |
|---|---|---|---|
| `vector` (pgvector) | **Yes**, all plans, no add-on | **0.8.0** (PG14–17), 0.8.6 (PG18) | Neon also allows installing one version back. <https://neon.com/docs/extensions/pgvector> |
| `pg_trgm` | **Yes** | 1.6 (PG14–18) | Already in use |
| `unaccent` | **Yes** | 1.1 (PG14–18) | Already in use |
| `fuzzystrmatch` | **Yes** | 1.1 (PG14–15), 1.2 (PG16–18) | levenshtein/soundex/dmetaphone — relevant to name matching |
| `btree_gin` | **Yes** | 1.3 | Lets a GIN index carry scalar cols alongside tsvector |
| `bloom` | **Yes** | 1.0 | |
| `rum` | **Yes** | 1.3 (PG14–17); **absent on PG18** | Faster ranked FTS than GIN, but still `ts_rank`, **not BM25** |
| `pg_search` (ParadeDB) | **Deprecated — dead 2026-09-21** | 0.15.26 (PG14–17) | Not available for new projects since 2026-03-19; AWS regions only. <https://neon.com/docs/extensions/pg_search> |
| **`lakebase_text`** | **Yes — GA, all users** | — | Requires **PG16+**; index type `lakebase_bm25` |
| **`lakebase_vector`** | **Yes — GA, all users** | — | Requires **PG16+**; index type `lakebase_ann`; depends on pgvector (`CASCADE`) |
| `pg_ivm` | **Not for new installs** | 1.9 / 1.12 | Closes off incremental matviews as a maintenance trick |
| `pgvectorscale` | **No** | — | Not in Neon's table. Self-host only (Tiger/Timescale). <https://github.com/timescale/pgvectorscale> |
| `vchord` / `vchord-bm25` (VectorChord) | **No** | — | Not in Neon's table. Self-host / pgEdge / VectorChord Cloud |
| `pg_bigm` | **No** | — | Not in Neon's table |
| `pgroonga` | **No** | — | Not in Neon's table |
| `zombodb` | **No** | — | Not in Neon's table (and it just proxies to Elasticsearch — wrong shape anyway) |
| `pg_similarity` | **No** | — | Not in Neon's table |
| `pgtap` | Yes | 1.3.3 | |

**Bottom line on availability:** on Neon our *only* BM25 option after 2026-09-21 is
`lakebase_text`. Every third-party BM25 or advanced-ANN extension (ParadeDB standalone,
VectorChord, pgvectorscale) requires **leaving Neon** for self-hosted Postgres, because they
all need `shared_preload_libraries` and/or custom access methods that a managed provider must
explicitly whitelist. ParadeDB documents this plainly: *"If you are using a managed Postgres
service like Amazon RDS, you will not be able to install `pg_search` until the Postgres
service explicitly supports it"*, and pg_search must be in `shared_preload_libraries` on
PG<17. <https://pgxn.org/dist/pg_search/0.15.20/pg_search/README.html>

---

## 2. BM25 in Postgres — the options, honestly compared

### 2.1 ParadeDB `pg_search`
- **License: AGPL-3.0** for ParadeDB Community; ParadeDB Enterprise is separately commercially
  licensed. ~9.2k stars, actively developed. <https://github.com/paradedb/paradedb>
- Tantivy-based (Rust Lucene analogue). Real BM25, faceting, fuzzy/typo tolerance, hybrid with
  pgvector — as of pg_search 0.25.0 **pgvector is a hard dependency** because pg_search uses
  pgvector's `vector` type.
- **Where it runs:** self-hosted Docker, or managed platforms that explicitly bundle it —
  ParadeDB lists Railway, Render, Fly.io, DigitalOcean, Dokku. **Not Neon after 2026-09-21.**
- **AGPL is a real consideration [INFERENCE]:** AGPL's network clause attaches to the
  *modified extension*, not to AG's Django code merely querying a database, so running stock
  pg_search on our own Railway Postgres does not oblige us to publish AG. But it is the sort
  of thing that wants a deliberate decision rather than a shrug.
- **Verdict for us:** would mean moving the corpus off Neon onto a self-managed Railway
  Postgres. That trades the sync problem for a database-operations problem (backups, PITR,
  upgrades, single-node durability) on a shoestring. Bad trade **[INFERENCE]**.

### 2.2 VectorChord-BM25 (`vchord_bm25`)
- Implements Block-WeakAnd BM25 as a native operator + index, deliberately lightweight and
  Postgres-native in syntax (unlike ParadeDB's separate query language).
  <https://github.com/tensorchord/VectorChord-bm25>
- Claims **~3× higher Top-1000 QPS than Elasticsearch** averaged across the `bm25-benchmarks`
  datasets.
  <https://blog.vectorchord.ai/vectorchord-bm25-revolutionize-postgresql-search-with-bm25-ranking-3x-faster-than-elasticsearch>
  · <https://docs.vectorchord.ai/vectorchord/benchmark/elasticsearch.html>
- **Not on Neon.** Self-host only.

### 2.3 `rum`
- Available on Neon (1.3, PG14–17). Stores lexeme positions in the index so ranked FTS avoids
  heap lookups — meaningfully faster `ts_rank` than GIN. **But it is still `ts_rank`, not
  BM25**, and gives no typo tolerance. It is a speed patch on a ranking-quality problem.
- Note the PG18 gap: adopting `rum` pins us off PG18 until upstream catches up.

### 2.4 Built-in `tsvector` / `ts_rank` — the actual ceiling
What we already run, and what it can't do:
- **No BM25.** `ts_rank` ignores corpus-wide document frequency and average document length;
  `ts_rank_cd` adds proximity but not IDF weighting. Ranking quality on a 300k-doc corpus of
  short abbreviated names is poor **[INFERENCE, but the reason `lakebase_text` exists]**.
- **No top-K pushdown** — GIN scores every matching document before `LIMIT`.
  <https://neon.com/blog/lakebase-search-on-neon>
- **No typo tolerance.** `pg_trgm` similarity and `fuzzystrmatch` levenshtein can be bolted
  on, but they're a separate ranking signal you have to fuse yourself — which is precisely the
  hand-rolled RRF we already maintain.
- **No facets.** Facet counts are `GROUP BY` over the filtered set; on 300k rows that is fine,
  at 5M grant rows it is not **[INFERENCE]**.

### 2.5 `lakebase_text` — what we'd actually get
Real BM25 scoring, Block-Max WAND top-K pushdown, `tsvector`-compatible so `search_tsv` is
reused verbatim, `<@>` operator and `to_bm25query()` helper, `WITH (default_limit = N)` on the
index. <https://neon.com/guides/lakebase-vector-bm25-search>

**Documented gaps I could not close:** Neon's docs and guide are silent on (a) incremental
index maintenance under `UPDATE`/`DELETE`, (b) typo tolerance / fuzzy matching, (c) facets,
(d) any concrete benchmark. The launch blog says *"a follow-up post with the full
benchmarks"* and does not deliver numbers. **Treat every performance claim here as vendor
marketing until we measure it ourselves.**

**Critically: `lakebase_text` gives us BM25, not typo tolerance.** Typesense's `num_typos`
behaviour has no equivalent. On a corpus of IRS abbreviations where users type "Smith Family
Foundation" and the row says "Smith Family Fdn", losing typo/prefix tolerance is a genuine
regression that `pg_trgm` only partially covers.

---

## 3. Filtered vector search — the #2025 problem

### 3.1 The arithmetic says our 1.7–2.8 s is *not* the filter [INFERENCE — high confidence]

This is the most important analytical point in this report.

pgvector's post-filter pathology is: with `ef_search = N` and a filter passing fraction `p`,
you expect `N × p` surviving rows. The pgvector README's own worked example is a filter
matching 10% of rows with the default `ef_search = 40`, yielding *"only 4 rows"*.
<https://github.com/pgvector/pgvector>

Our numbers: `ef_search = 200`, eligibility passes **~60%**, `k = 50`.
Expected survivors on the *first, non-iterative* pass: `200 × 0.6 = 120` ≫ 50.

**The iterative scan should essentially never fire.** A 60%-selectivity filter is the *easy*
regime for post-filtering — it is 1–5% selectivity that destroys HNSW. So `relaxed_order`,
`max_scan_tuples`, and `scan_mem_multiplier` are almost certainly **not** where our 1.7–2.8 s
lives, and tuning them is likely to produce no improvement.

Corroborating scale check: the SIGMOD 2026 study measured pgvector filtered-vector-search
latency on **OpenAI-1M (1M vectors, 1536-dim)** at roughly **10–100 ms** across the whole
selectivity range, with `pg_prewarm` loading table *and* index into buffers and
`shared_buffers = 64GB`. Duo Lu, Caminal, Chatzakis, Papakonstantinou, Chronis, Jain, Özcan,
*"An In-Depth Study of Filter-Agnostic Vector Search on a PostgreSQL Database System"*, Proc.
ACM Manag. Data 4(3) (SIGMOD), Article 134, June 2026, Fig. 1.
<https://arxiv.org/abs/2603.23710> · <https://arxiv.org/pdf/2603.23710>

Our workload is **3× fewer vectors at a quarter the dimensionality** than theirs. If memory
resident, it should be **single-digit to low-tens of milliseconds**. We measure 1.7–2.8 s —
**~50–100× off**. That gap is an I/O or planning gap, not an algorithmic one.

### 3.2 The cold-cache hypothesis is strong and cheap to test

The brief asks specifically whether autosuspend could dominate. The evidence says: very
plausibly, yes.

- Neon's compute cache is the **Local File Cache (LFC)**, sized to as much as **75% of the
  compute's RAM**; each CU ≈ **4 GB RAM**. <https://neon.com/docs/guides/autoscaling-algorithm>
  · <https://neon.com/docs/extensions/neon>
- Scale-to-zero default is **5 minutes** of inactivity, and *"when compute restarts after
  scale-to-zero, it comes up with a cold local file cache, so the next several queries read
  from storage instead of memory."* This *"shows up as multi-second p95 spikes in RAG and
  search endpoints."* <https://www.cloudthinker.io/blogs/neon-postgres-performance-guide> ·
  <https://neon.com/blog/1-year-of-autoscaling-postgres-at-neon>
- Wake-up itself is only ~300–800 ms; the *cache* refill is the long tail.
  <https://neon.com/docs/connect/connection-latency>

**Sizing [INFERENCE]:** 293k × 384-dim float32 = **~450 MB** of raw vectors. A pgvector HNSW
index stores the full vector inline plus neighbour lists (m=16), so the index alone is roughly
**600–800 MB**, *before* the `foundations` heap (which the post-filter must touch, because the
eligibility columns aren't in the index). At **1 CU** the LFC is ~3 GB and is also serving
every other AG query; at **2 CU**, ~6 GB. A single `ef_search=200` traversal touches thousands
of scattered index pages. On a cold LFC each miss is a pageserver round trip — *"single-digit
milliseconds on page fetches."* A few hundred cold page fetches **is** 1.7 seconds.

### 3.3 The ranked fix list for #2025

**Rank 0 — measure before tuning (costs nothing, and everything below is guesswork without it).**
`EXPLAIN (ANALYZE, BUFFERS)` on `ag_research.match_foundations`, run twice back to back, plus
`SELECT * FROM neon_stat_file_cache`. Three questions:
1. Is the HNSW index used at all, or did the planner pick a **seq scan + sort** over 293k
   rows? At 60% selectivity a planner can easily decide the index isn't worth it — and a
   `SECURITY DEFINER` SQL function with parameterised filters is exactly where a generic
   cached plan goes wrong. A full scan computing 293k cosine distances *and* reading ~450 MB
   of heap from a cold LFC lands squarely at 1.7 s. **[INFERENCE — my leading hypothesis.]**
2. `shared hit` vs `read` in BUFFERS — that is the cold-cache question, answered directly.
3. Second run vs first run. If run 2 is 30 ms, the index is fine and this is entirely a cache
   problem, and every index change below is wasted effort.

**Rank 1 — partial HNSW index matching the fixed predicate.**
The eligibility predicate `is_active_grantmaker AND foundation_code <= 4 AND country = 'US'`
is **constant across every query**. That is the textbook case for pgvector's documented
partial-index recommendation: `CREATE INDEX ON items USING hnsw (embedding vector_l2_ops)
WHERE (category_id = 123)`. <https://github.com/pgvector/pgvector>
Effect: the filter becomes **free** (it's the index's own predicate, checked at plan time, no
heap fetch), and the index shrinks to ~60% of its size — **[INFERENCE]** ~176k vectors,
~400–500 MB, materially more likely to stay resident in a 1–2 CU LFC. Only the *variable*
filters (`state`, `min_assets`, `include_national`) remain post-filtered, and those pass a
much larger fraction. This is the single highest-value change and it is cheap.

**Rank 2 — shrink the working set so it fits the LFC.**
pgvector's own performance guidance: use **`halfvec`** *"instead of `vector` for a smaller
working set"*, and **binary quantization** for *"smaller indexes and faster build times."*
<https://github.com/pgvector/pgvector>
`halfvec(384)` halves the vectors to ~225 MB (~88 MB on the partial index). Combined with
Rank 1, the whole ANN structure plausibly fits in cache at 1 CU **[INFERENCE]**. Rerank the
top ~200 with full-precision cosine to recover recall.

**Rank 3 — `lakebase_ann` with `lakebase_ann.prefilter = on`.**
This is the structurally right answer and it directly targets both failure modes:
- **Prefilter** evaluates the non-vector filters *before* distance reranking — no
  post-filtering pathology at any selectivity.
- **Storage-resident index**, explicitly designed so scale-to-zero needs no warmup — which
  removes the cold-LFC tail rather than papering over it.
- **Drop-in pgvector compatibility** — same `vector` type, same `<=>` operator, same
  `vector_cosine_ops`. Migration is a `CREATE INDEX`, not a rewrite.
- Tuning knobs: `lakebase_ann.probes` (default `auto`), `lakebase_ann.epsilon` (default
  `auto`), `lakebase_ann.prefilter` (default **off**).
- Supports `CREATE INDEX CONCURRENTLY` / `REINDEX INDEX CONCURRENTLY`, and `rabitq` 8-bit and
  4-bit storage variants alongside `vector` and `halfvec`.
<https://neon.com/docs/extensions/lakebase-vector>
**Prerequisite to verify: our Neon project must be on Postgres 16+.** I did not check this —
do not skip it.
**Caveat:** Neon's docs note prefilter is *"optimal for cheap filters that remove most rows"*.
Our eligibility filter removes only 40%, so prefilter may not be the win there — but it is
exactly right for `state = 'MI'` (~2% of rows), which is the filter that *does* bite.

**Rank 4 — materialise the eligibility flag as a stored boolean column.**
If `is_active_grantmaker` is a view expression or function rather than a stored column, every
candidate costs an evaluation. Making it a stored, indexed `BOOLEAN` is a prerequisite for the
partial index anyway. **[INFERENCE — depends on schema I did not read.]**

**Rank 5 — tune `hnsw.max_scan_tuples` / `scan_mem_multiplier`. Expected value: near zero.**
Defaults are `max_scan_tuples = 20000`, `scan_mem_multiplier = 1`, `ef_search = 40`.
<https://github.com/pgvector/pgvector> Per §3.1 the iterative scan shouldn't be firing at 60%
selectivity. Worth noting the *opposite* risk: `ef_search = 200` is already 5× default and, if
the cache is cold, **raising it makes things worse**. Try `ef_search = 80` with the Rank 1
partial index and measure.

**Rank 6 — not available to us:** `pgvectorscale` StreamingDiskANN with label-based filtering
(28× lower p95 vs Pinecone s1 at 99% recall on 50M×768 Cohere, 0.9.0 Nov 2025, parallel index
builds) <https://github.com/timescale/pgvectorscale>, and VectorChord's prefiltering (*"up to
3× faster search when pre-filtering is applicable"* vs VBASE post-filtering; 100M vectors
indexed in <20 min on 16 vCPU vs pgvector's >50 h)
<https://blog.vectorchord.ai/vectorchord-04-faster-postgresql-vector-search-with-advanced-io-and-prefiltering>.
Both are excellent and **neither is on Neon.** Listed so we know what we're forgoing.

### 3.4 What the SIGMOD paper says we should *not* expect

The paper's central finding is a caution against exactly the kind of algorithm-shopping this
lane invites: *"the optimal algorithm is not dictated by the cost of distance computations
alone, but that system-level overheads that come from both distance computations and filter
operations (like page accesses and data retrieval) play a significant role."* Graph
filter-first methods (ACORN, NaviX) *"can incur prohibitive numbers of filter checks and
system-level overheads"* in a real DBMS, *"often canceling out their theoretical benefits."*
And: *"techniques that appear attractive in libraries… can become memory-bound in a DBMS,
where every neighbor dereference triggers multiple page accesses."*
<https://arxiv.org/pdf/2603.23710> §7

Read against our situation: **page accesses are the currency**, and on Neon a page access can
be a network round trip. Which is why Rank 1 and Rank 2 (make the working set smaller) beat
Rank 5 (make the algorithm cleverer).

---

## 4. Consistency: what going all-in-Postgres buys and costs

### Buys
- **Transactional indexes.** A committed `UPDATE` is visible to search in the same
  transaction. No drift, no reindex job, no alias swap, no orphan collection, no
  "served corpus is 2 nights old", no Dagster zombie reaper killing a 45-minute-capped
  3.5-hour rebuild. ParadeDB's own pitch names the prize: *"Your application data and search
  engine live in one database, with no second system to deploy and nothing to sync."*
  <https://github.com/paradedb/paradedb>
- **One ranking path.** The two-engine drift problem (Typesense vs pgvector vs FTS fallback,
  with a fail-open that silently switches ranking mid-incident) disappears by construction.
- **One security model.** The existing `SECURITY DEFINER` + EXECUTE-only grant already works;
  no second system's API keys to scope.
- **Neon branching.** *"Branching creates instant search index availability without
  re-indexing"* — a staging branch gets a working search index for free.
  <https://neon.com/docs/ai/lakebase-search>

### Costs — be honest about these
- **Typo tolerance is lost.** Nothing in the Neon-available set replicates Typesense's
  `num_typos`. `pg_trgm` + `fuzzystrmatch` levenshtein are a partial, hand-fused substitute.
  On IRS-abbreviated names this is the sharpest regression.
- **Facet speed.** Facets become `GROUP BY` over the filtered set. Fine at 300k; unproven at
  the planned millions of grant rows **[INFERENCE]**.
- **Search traffic now consumes Neon compute-hours, and the budget doesn't allow a warm box.**
  This is the structural tension of the whole lane. Neon Launch is **$0.106/CU-hour**;
  storage **$0.35/GB-month**; read replicas are billed as their own compute at the same
  CU-hour rate. <https://swyftstack.com/blog/neon-pricing-explained> ·
  <https://neon.com/docs/introduction/plans>
  **[INFERENCE — arithmetic]** 1 CU × 730 h × $0.106 = **$77/mo**; 2 CU 24/7 = **$155/mo**.
  Against a **$50/month Neon target**, we cannot afford an always-warm compute. Therefore the
  compute *must* idle and autosuspend. Therefore search *will* routinely meet a cold LFC.
  **The $50 budget and sub-100 ms pgvector-HNSW search are in direct conflict**, and no amount
  of index tuning resolves it. Only two things do: an index that doesn't need warm RAM
  (`lakebase_ann`), or search that doesn't touch Neon (§6).
- **HNSW build time on 300k rows.** Manageable but not free: `maintenance_work_mem` default is
  64 MB and a build that doesn't fit falls back to a disk path *"10–50× slower"*; Neon
  documents testing `maintenance_work_mem = '10 GB'` on a 7 CU / 28 GB compute (<50% of RAM),
  and parallel builds cut HNSW build time ~30×.
  <https://neon.com/docs/extensions/pgvector> ·
  <https://neon.com/blog/pgvector-30x-faster-index-build-for-your-vector-embeddings>
  **[INFERENCE]** For 293k × 384-dim with adequate `maintenance_work_mem` and parallel
  workers, expect single-digit minutes — but the compute must scale up for the build, and
  that costs CU-hours. `lakebase_ann`'s claimed 50–100× faster builds matter here.
- **Index bloat under UPDATE churn.** Enrichment drains and `display_name` backfills rewrite
  rows continuously. Every `UPDATE` is a new heap tuple and a new index entry; HNSW entries
  for dead tuples are only pruned by vacuum, and HNSW graph quality degrades under heavy
  churn. `REINDEX INDEX CONCURRENTLY` is the remedy and it is supported for `lakebase_ann`.
  <https://neon.com/docs/extensions/lakebase-vector>
  **[INFERENCE]** Plan for a periodic concurrent reindex — note this is a *smaller* version of
  the same maintenance job we were trying to escape, not its total elimination.
- **Vendor concentration.** `lakebase_text` / `lakebase_vector` are **Neon/Databricks
  proprietary extensions**, not open source. Adopting them makes leaving Neon a rewrite. Given
  that Neon just deprecated `pg_search` with six months' notice, that is a real risk, and it
  sits awkwardly against the brief's "genuinely open source or source-available" requirement.
  The mitigation is that `lakebase_text` is `tsvector`-compatible and `lakebase_ann` is
  pgvector-compatible, so the *fallback* (GIN + HNSW) is always one `CREATE INDEX` away.

---

## 5. Read replicas and offloading

- Neon read replicas are *"independent read-only compute instances that serve requests from
  the same storage as the primary compute"* — **no data duplication**, they read the same
  pageservers. They support autoscaling and scale-to-zero, and are explicitly intended to
  *"distribute read traffic"* and *"offload analytics queries."*
  <https://neon.com/docs/introduction/read-replicas>
- **Pricing:** each replica is its own compute billed at the same CU-hour rate.
  <https://swyftstack.com/blog/neon-pricing-explained>
- **Assessment [INFERENCE]:** a search replica does *not* help us. Because storage is shared,
  a replica gets no dedicated index copy — it gets its own **cold LFC**, which is precisely
  our problem, duplicated and separately billed. A replica helps when the primary is
  CPU-saturated; ours isn't, it's cache-cold. Sole legitimate use: isolating a heavy index
  build from the serving compute.
- **Railway Postgres replica via logical replication holding only the search projection:**
  technically sound and it *would* deliver a warm, always-on cache with a flat Railway price
  rather than metered CU-hours. But it reintroduces exactly what this lane exists to
  eliminate: a second system, replication lag, slot management (a stalled subscriber pins WAL
  on the publisher and can fill Neon's storage), schema-change coordination, and single-node
  durability we'd own. **[INFERENCE]** If we're standing up a second always-on box anyway,
  §6's read-only artifact is strictly simpler than logical replication — no slots, no lag, no
  publisher risk.

---

## 6. Postgres as truth + a colocated lightweight engine

This is the option the brief asks to "evaluate seriously," and it deserves it — because it is
the only architecture that resolves the $50-budget-vs-latency conflict outright.

**The shape:** GS builds a read-only index artifact from Neon nightly, publishes it to B2, AG
pulls it to the container volume and swaps by atomic `rename()`. Query path: **zero network,
zero Neon compute-hours, no cold start.** GS already publishes to B2 (`markdown_b2_key`), so
the transport is a paved road.

### 6.1 Build time — the standout number
Tantivy indexes **5 million English Wikipedia articles in ~3 minutes**.
<https://github.com/quickwit-oss/tantivy>
Our 203k–300k docs are ~4% of that corpus. **[INFERENCE]** Expect **seconds to low minutes** —
against Typesense's current **3.5–4 hours**. That is a ~100× improvement in the exact
operation that is currently fragile, and it makes the zombie-reaper problem vanish rather than
being worked around.

### 6.2 The candidates

| Option | License | Fit | Notes |
|---|---|---|---|
| **Tantivy via `tantivy-py`** | MIT (Tantivy) | **Best** | Real BM25, phrase/prefix/fuzzy queries, facets, segment merges, battle-tested on-disk format. Same engine ParadeDB and Quickwit are built on — so we get ParadeDB's retrieval quality **without AGPL, without `shared_preload_libraries`, and without leaving Neon.** In-process in Django: no server, no port, no container. <https://github.com/quickwit-oss/tantivy> · <https://tantivy-py.readthedocs.io/en/latest/> |
| **SQLite FTS5 (+ `sqlite-vec`)** | Public domain / Apache-2.0+MIT | **Good** | FTS5 is BM25-ranked and ships in the stdlib `sqlite3` — literally zero new dependencies for keyword. `sqlite-vec` is dual Apache-2.0/MIT, 8.1k stars, supports float/int8/binary vectors and **metadata filtering via partition-key and auxiliary columns** — but it is explicitly **pre-v1** ("expect breaking changes"). <https://github.com/asg017/sqlite-vec> |
| **DuckDB FTS + VSS** | MIT | **Avoid** | The FTS "index" is a set of SQL tables, not a real index, and *"will not update automatically when the input table changes."* <https://github.com/duckdb/duckdb/issues/3543> · <https://duckdb.org/docs/current/core_extensions/full_text_search> Worse, VSS's HNSW *"can only be created on tables in in-memory databases"* unless `hnsw_enable_experimental_persistence` is set, and that flag risks *"data loss or corruption of the index"* on unclean shutdown. <https://duckdb.org/docs/current/core_extensions/vss> Not production-grade for this. |

**[INFERENCE] — the staleness objection is void for our corpus.** DuckDB's non-updating index
is disqualifying for a live database; it is *irrelevant* for a nightly-built immutable
artifact, where "rebuild from scratch" is the design. The reason to still prefer Tantivy is
ranking quality and query features, not staleness.

### 6.3 Sizing [INFERENCE — arithmetic, not measured]
- Vectors, 293k × 384: float32 **450 MB**; int8 **112 MB**; binary **14 MB**.
- Tantivy/FTS5 text index over 300k foundation docs with enrichment prose: **~200–500 MB**.
- Total artifact **~300 MB–1 GB**, compressible. Trivially within a Railway volume, and B2
  egress at nightly cadence is negligible.

### 6.4 Honest costs
- **Freshness floor of one rebuild interval.** Foundations change slowly (IRS yearly, bulk
  backfills) — nightly is genuinely fine. **`gov_opportunities` change daily and close dates
  matter**, so those ~9k rows should stay on the live Postgres path. That is a defensible
  split, not a fudge **[INFERENCE]**.
- **Writes are invisible until the next build.** Any user-visible write-then-search flow must
  read through Postgres.
- **Multi-container coherence.** N AG containers each hold their own artifact copy and can
  briefly disagree during a rollout. **[INFERENCE]** At our scale this is cosmetic.
- **A new artifact pipeline to own** — build, publish, verify, pull, swap, and a
  count-parity/checksum canary that can actually go red. The `.gitkeep`-style trap here is a
  swap that silently keeps serving the old file; the canary must assert freshness on every
  run, not just on failure.

---

## 7. Three candidate architectures

### A — All-in-Postgres (Neon Lakebase Search)
`lakebase_bm25` on the existing `search_tsv` + `lakebase_ann` with `prefilter` replacing HNSW;
retire Typesense entirely.

- **Consistency:** perfect. Transactional. No sync, no drift, one ranking path. *This lane's
  whole thesis, delivered.*
- **Latency [INFERENCE]:** the storage-resident index removes the cold-start cliff Neon itself
  documents; steady-state plausibly tens of ms. **Unverified — Neon published no benchmarks.**
- **Cost:** search traffic on metered CU-hours, but no warm-compute requirement, so
  autosuspend stays viable and the $50 target survives.
- **Gives up:** typo tolerance; facet speed at grant scale; **open-source portability** (both
  extensions are Neon/Databricks proprietary).
- **Risk:** GA for ~10 weeks, zero independent benchmarks, and this is the same vendor that
  just killed `pg_search` on six months' notice.

### B — Postgres as truth + embedded index artifact (Tantivy or FTS5+sqlite-vec on B2)
Neon stays canonical; GS builds and publishes nightly; AG queries a local file.

- **Consistency:** eventually consistent with a **bounded, monitorable** staleness — a
  timestamp in the artifact makes lag *measurable*, which the current alias-swap explicitly is
  not. Still exactly one ranking path at query time.
- **Latency:** best of the three — no network on the query path at all.
- **Cost:** ~zero marginal Neon compute for search. Best fit to the budget by a wide margin.
- **Build:** minutes, not hours. Kills the 3.5–4 h rebuild and the zombie-reaper failure.
- **Gives up:** real-time writes; needs the gov-opportunities carve-out; a new pipeline to own.
- **Licensing:** MIT / public domain throughout. No AGPL, no vendor lock.

### C — Postgres + external engine (status quo, or Typesense done properly)
- **Consistency:** the problem we have. Full rebuild, no CDC, no tombstones, no reconciliation,
  a fail-open that silently changes ranking.
- **Latency:** good when up.
- **Cost:** a second always-on Railway container plus its RAM.
- **Gives up:** consistency, and a single ranking path. Keeps typo tolerance — which is the
  one thing it genuinely does better than A or B.

| | A: All-in-Postgres | B: Embedded artifact | C: External engine |
|---|---|---|---|
| Consistency | **Transactional** | Bounded, measurable | Unbounded, unmeasured |
| Query latency | tens of ms *(unverified)* | **best — local file** | good |
| Cold-start exposure | low (storage-resident) | **none** | none |
| Marginal Neon cost | metered CU-hours | **~zero** | ~zero |
| Index build (300k) | 50–100× faster than HNSW *(vendor)* | **seconds–minutes** | **3.5–4 h** |
| Typo tolerance | ✗ | partial (Tantivy fuzzy) | **✓** |
| Ranking paths | **1** | **1** | 3, silently switching |
| Licensing | proprietary | **MIT / PD** | Apache-2.0 |
| Ops surface | **none new** | build+publish+swap | container, volume, RAM, backups |

---

## 8. Recommendation

**For #2025 specifically — the filtered-KNN latency — in order:**

1. **`EXPLAIN (ANALYZE, BUFFERS)`, run twice, plus `neon_stat_file_cache`.** My strong
   inference is that this is a cold-LFC or seq-scan problem, *not* a filtering problem — at
   60% selectivity with `ef_search = 200` the post-filter mathematically cannot be starving.
   Every fix below is guesswork until this is read. Cost: minutes.
2. **Partial HNSW index on the fixed eligibility predicate.** Documented pgvector guidance,
   exactly matches our constant predicate, makes the 60% filter free and shrinks the index
   ~40%. Highest value per unit of effort.
3. **`halfvec` + full-precision rerank** to halve the working set so it survives in a 1–2 CU LFC.
4. **`lakebase_ann` with `prefilter = on`**, verifying PG16+ first. Structurally the right
   answer to *both* the filtering pathology and the cold-start tail, and a drop-in on the
   pgvector API. Measure it against 2+3 rather than assuming the vendor numbers.
5. **Do not spend time on `max_scan_tuples` / `scan_mem_multiplier`.** Consider *lowering*
   `ef_search` to 80.

**For the wider search architecture:** the honest answer is that **the $50/month Neon target
and a warm-RAM vector index are mutually exclusive**, and that constraint — not any ranking
consideration — should drive the choice. **Architecture B is the best fit**, and Tantivy is
its best instantiation: it gives ParadeDB-grade BM25 retrieval under MIT, in-process, with no
`shared_preload_libraries`, no AGPL, no second server, no Neon dependency, and a build that
takes minutes instead of hours. **Architecture A is the strong second** and is worth a
timeboxed spike precisely because it makes the consistency problem cease to exist — but it is
ten weeks old, unbenchmarked by anyone independent, proprietary, and offered by a vendor with
a fresh deprecation on its record.

**Do not pursue** ParadeDB-on-Neon (dead in 14 days), pgvectorscale or VectorChord (not on
Neon; would mean self-managing Postgres), DuckDB VSS (experimental persistence, documented
corruption risk), or a Neon read replica for search (shared storage means a second cold cache,
separately billed).

**Standing caveat:** every Lakebase Search performance number in this report is Neon's own
marketing. No independent benchmark exists yet. Nothing here should be treated as measured
until we measure it.

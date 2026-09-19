# Lane 1 — The open-source search-engine landscape, judged against GrantSpider / AI Grant Helper

Research date: **2026-09-07**. All GitHub star / issue / release figures were pulled live from the
GitHub REST API on that date (`gh api repos/<owner>/<repo>`), not from memory or from third-party
comparison blogs. Where a claim is my own reasoning rather than a documented fact it is tagged
**[INFERENCE]**.

**Corpus this is judged against:** ~300k `foundations` (small docs: name, EIN, city, state, NTEE,
foundation_code, asset_amount, slug, prose) with 384-dim embeddings on ~293k of them; ~9k
`gov_opportunities`; a future `grants` surface of 200k–several million rows. Target box: a single
Railway service, ~2–4 GB RAM. Budget: no paid SaaS.

---

## 0. The headline findings, before the detail

Four things surfaced that change the shape of the decision:

1. **16 docs/sec is not a Typesense speed — it is roughly 600× slower than Typesense's own published
   benchmark**, and ~70–100× slower than the *worst* case in Typesense's own bug tracker. This is
   almost certainly a client/transport defect in GS's indexer, not an engine limit. Section 6 lays
   out the arithmetic and the five candidate causes, of which **cross-Railway-project HTTP** is the
   strongest.
2. **Typesense's commit velocity has collapsed.** Last stable release `v30.2` on **2026-04-19** —
   nearly five months ago. The last 12 weeks of commit activity on `typesense/typesense` read
   `[1,1,1,3,0,1,0,12,0,2,1,2,1,0,1]` per week, against 878 open issues. This is a real
   sustainability signal and it did not show up in any comparison blog I read.
3. **Meilisearch is no longer purely MIT.** As of 2026 the repo is `SPDX-License-Identifier:
   MIT AND BUSL-1.1`. The BUSL-1.1 "Enterprise Edition" carve-out currently covers **only sharding**
   — everything GS/AG needs stays MIT — but the mechanism now exists to move features behind it.
4. **`pg_search` is deprecated on Neon.** Unavailable for new Neon projects since 2026-03-19, and
   **existing projects lose it on 2026-09-21 — two weeks from now.** This effectively deletes
   ParadeDB-in-Neon as an option for this system. (Lane 4 owns the depth here, but this is
   decision-changing and belongs in front of Nathan today.)

---

## 1. Comparison table

Stars / open issues / last release captured live 2026-09-07 via the GitHub API.

| Engine | License | Governance | Stars | Open iss. | Latest release | Released | Hybrid in ONE query? | Fusion | Typo tol. | Incremental upsert+delete | Snapshot → object store | RAM @300k+384d | Verdict for GS/AG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Typesense** | GPL-3.0 | Single company (Typesense Inc.) | 26,522 | 878 | v30.2 | 2026-04-19 | **Yes** | rank fusion, `alpha` (0.7 kw / 0.3 vec default) | **Best in class** (`num_typos` per-field) | Yes (`upsert`/`emplace`, `PATCH ?filter_by`, `DELETE ?filter_by`) | Snapshot API → local dir, then you ship it yourself | ~1.1 GB **[INFERENCE]** | **Keep — but fix the indexer** |
| **Meilisearch** | MIT **AND** BUSL-1.1 | Single company (Meili SAS) | 59,206 | 319 | v1.53.2 | 2026-09-07 | **Yes** | `semanticRatio` (0.0–1.0) | Excellent (≤2 typos, per-attribute) | Yes (task queue, partial updates) | Snapshots + dumps to local disk only | Low — LMDB memory-mapped | **Strongest switch candidate** |
| **OpenSearch** | Apache-2.0 | **Foundation** (Linux Foundation) | 13,675 | 3,177 | 3.8.0 | 2026-08-05 | **Yes** | `normalization-processor` (min-max/L2) or `score-ranker-processor` (RRF) | Weak (`fuzziness`, not real typo tolerance) | Yes | **Yes — native `repository-s3`** | JVM; ~2 GB heap min, wants more | Add only if you need Lucene depth |
| **Elasticsearch** | AGPLv3 / ELv2 / SSPL (tri) | Single company (Elastic NV) | 77,904 | 6,065 | v9.5.3 | 2026-09-03 | Yes (RRF native) | RRF | Weak (`fuzziness`) | Yes | Yes (S3 repo plugin) | JVM, heavy | **No** — AGPL + tiering risk |
| **Apache Solr** | Apache-2.0 | **Foundation** (ASF) | 1,673 | 176 | 10.0.0 | 2026-03-03 | Yes (10.0 improved) | manual / LTR | Weak | Yes | Yes | JVM + big OS page cache | No — wrong ergonomics |
| **Vespa** | Apache-2.0 | Single company (Vespa.ai, ex-Yahoo) | 7,077 | 253 | v8.751.13 | 2026-09-07 | **Yes, best-in-class** | `reciprocal_rank_fusion()` in rank profile, phased ranking | Weak | Yes (true real-time) | Yes | **≥4–5 GB just to boot** | No — footprint + complexity |
| **Quickwit** | Apache-2.0 | **Datadog** (acquired) | 11,575 | 807 | v0.9.0 | 2026-07-25 | Partial | — | No | **No — no document updates** | Native (index *lives* on S3) | Low | **No — disqualified** |
| **Tantivy** (library) | MIT | Datadog / community | 16,048 | 449 | 0.26.1 | 2026-05-10 | n/a (library) | n/a | n/a | n/a | n/a | n/a | Not a server; underpins pg_search |
| **Manticore** | GPL-3.0 (Columnar lib Apache-2.0) | Single company (Manticore Software) | 11,992 | 659 | 29.0.2 | 2026-08-14 | **Yes** | **RRF** | Yes (fuzzy + CJK) | Yes (REPLACE, real-time indexes) | **Yes — native S3 backups (25.0.0+)** | Low (row + columnar) | **Interesting dark horse** |
| **Sonic** | MPL-2.0 | Single maintainer | 21,335 | 64 | v1.8.1 | 2026-08-16 | No | — | Yes (prefix) | Yes | No | Tens of MB | **No — ID index only** |
| **ZincSearch** | Apache-2.0 | **ARCHIVED** | 17,885 | 48 | v0.4.10 | **2024-01-14** | No | — | No | Yes | No | Low | **No — dead** |
| **OpenObserve** | AGPL-3.0 (+ commercial EE) | Single company | 21,672 | 573 | v1.0.0-rc2 | 2026-09-03 | No | — | No | Append-oriented | Native (Parquet on S3) | Low | **No — observability, not app search** |
| **Weaviate** | BSD-3-Clause | Single company (Weaviate B.V.) | 16,788 | 719 | v1.39.3 | 2026-09-07 | **Yes** | `alpha` + RRF or relative score | Weak | Yes | **Yes — `backup-s3` module** | ~0.9 GB | Add-only; overlaps pgvector |
| **Qdrant** | Apache-2.0 | Single company (Qdrant Solutions) | 34,420 | 707 | v1.19.1 | 2026-09-04 | **Yes** (since 1.15.2 native BM25) | RRF / DBSF in Query API | **No** (exact token match) | Yes | **Yes — snapshots to S3** | ~0.6–1 GB **[INFERENCE]** | No — no typo tolerance |
| **ParadeDB pg_search** | AGPL-3.0 | Single company (ParadeDB Inc.) | 9,238 | 201 | v0.25.6 | 2026-08-27 | Yes (in SQL) | manual/SQL | Yes (`fuzzy_term`) | Yes (Postgres MVCC) | Postgres backup | In-Postgres | **Blocked — deprecated on Neon** |

---

## 2. Per-engine detail

### 2.1 Typesense — *the incumbent*

**1. License / governance.** GPL-3.0 ([license API](https://github.com/typesense/typesense/blob/master/LICENSE)).
GPL, **not** AGPL — running it as a network service imposes no source-disclosure obligation on AG, so
self-hosting for a SaaS is genuinely unencumbered. Governance is a single VC-adjacent company
(Typesense Inc.), no foundation.

**2. Activity — the concerning part.**
- Stars 26,522; forks 970; **open issues 878**; last push 2026-09-01.
- Releases: `v30.2` **2026-04-19**, `v30.1` 2026-01-29, `v30.0` 2026-01-27, `v29.0` 2025-06-30
  ([releases](https://github.com/typesense/typesense/releases)).
- Weekly commit counts, most recent 15 weeks (GitHub `stats/participation`):
  `1, 1, 1, 3, 0, 1, 0, 12, 0, 2, 1, 2, 1, 0, 1`. Earlier in the same 52-week window the project was
  running 4–11 commits/week. **The trend is roughly a 4× slowdown over the last quarter.**
- Recent commits are narrow bug fixes (`Fix union search returning fewer hits than found`,
  `fix scoped limit_hits`) rather than feature work
  ([commits](https://github.com/typesense/typesense/commits/master)).

  **[INFERENCE]** Nearly five months with no stable release plus 878 open issues plus single-company
  governance is a bus-factor risk worth naming explicitly. It is not an emergency — the engine works
  and the data model is small — but it argues against *deepening* the Typesense investment (i.e.
  against the Phase-2 "push vectors into Typesense, retire pgvector" plan) without a considered look
  at Meilisearch first.

**3. Architecture.**
- **In-memory inverted index**; disk (RocksDB) is used for durability and Raft logs, not for the
  query hot path ([system requirements](https://typesense.org/docs/guide/system-requirements.html)).
- **Durability:** Raft write-ahead log + snapshots. `POST /operations/snapshot` compacts Raft logs
  into a snapshot ([cluster operations](https://typesense.org/docs/30.2/api/cluster-operations.html)).
- **Replication:** Raft, requires ≥3 nodes for HA
  ([high availability](https://typesense.org/docs/guide/high-availability.html)). GS/AG runs a single
  node — so there is no replica, and a volume loss is a full-rebuild event.
- **Updates:** real-time. `action=create|upsert|update|emplace`; `emplace` accepts partial docs and
  creates-or-updates ([documents API](https://typesense.org/docs/30.2/api/documents.html)).
- **Zero-downtime reindex:** collection aliases — index into `foundations_<ts>`, then repoint the
  `foundations` alias ([collection aliases](https://typesense.org/docs/30.2/api/collection-alias.html)).
  This is exactly what GS already does and it is the documented, sanctioned pattern.

**4. Hybrid search.** Genuine single-query hybrid. `rank_fusion_score = 0.7 * K + 0.3 * S` where K
and S are the keyword and semantic *ranks*; the split is tunable via `alpha`
([vector search](https://typesense.org/docs/30.2/api/vector-search.html)). `vector_query` accepts an
externally-computed embedding — **so AG's existing 384-dim vectors can be pushed straight in without
Typesense doing any embedding**, and `num_dim: 384` is explicitly supported. Filtered vector search
works via ordinary `filter_by`, with `flat_search_cutoff` falling back to brute force when the
filtered candidate set is small — **this is precisely the escape hatch for the pgvector #2025
problem**, because a highly selective state/asset filter degrades to exact search rather than
wandering HNSW. HNSW knobs: `M` (default 16), `ef_construction` (200), `ef` (10).
Typo tolerance is the best of any engine here — per-field `num_typos` (e.g.
`num_typos=2,0,0` to keep EIN exact), max 2 typos by design
([ranking and relevance](https://typesense.org/docs/guide/ranking-and-relevance.html)). Prefix,
faceting with min/max/sum/avg on numerics, global synonyms and curation (new in v30), and `sort_by`
on int64 are all first-class.

**5. Footprint.** Documented rules of thumb
([system requirements](https://typesense.org/docs/guide/system-requirements.html)):
- keyword: `2X–3X MB` RAM for `X MB` of *indexed field* data;
- vectors: `7 bytes * dims * records`. For GS: `7 × 384 × 300,000 ≈ 806 MB`.
- **[INFERENCE]** GS's indexed text is small (names, city, state, slug — call it 40–100 MB raw),
  so ~0.2–0.3 GB keyword + ~0.8 GB vectors ≈ **~1.1 GB total**. That fits a 2 GB box with headroom
  and comfortably fits 4 GB. Adding the enrichment prose to `query_by` would raise the keyword side
  materially; that should be measured, not guessed.
- Container gotchas: minimum 2 vCPU, but **"a minimum of 4 CPU cores is recommended for high volume
  writes"**; under write pressure Typesense returns HTTP 503 `Not Ready or Lagging` as deliberate
  backpressure ([syncing data](https://typesense.org/docs/guide/syncing-data-into-typesense.html)).
- Disk: "at least the size of your raw dataset". Note
  [issue #2005](https://github.com/typesense/typesense/issues/2005) — a user doing *daily full bulk
  imports* saw the data volume grow to ~12× RAM (255 GB) in 2–3 days from RocksDB accumulation.
  **This is directly relevant: GS does a nightly full reindex.** Worth checking the Railway volume's
  actual growth curve.

**6. Import throughput — see §6 below.** Short version: vendor benchmark is
**~10,185 docs/sec** (2.2M records in 3.6 min on 4 vCPU) and **~5,983 docs/sec** (28M in 78 min),
per [benchmarks](https://typesense.org/docs/overview/benchmarks.html). GS is getting 16.

**7. Python client.** `typesense` **2.0.0**, uploaded 2026-02-16, Apache-2.0, 40 releases, requires
Python ≥3.9 ([PyPI](https://pypi.org/project/typesense/)). Officially maintained, fully typed as of
2.x. **Synchronous only** — there is no official async client; the community has asked for one
([community thread](https://threads.typesense.org/t/32592578/are-there-any-plans-for-an-async-python-client-we-are-runnin))
and only third-party `pyst-typesense-async` exists. **[INFERENCE] This matters a great deal for
GS's import path** — a synchronous client with no connection pooling across a public network is
exactly the shape that produces 16 docs/sec.

**8. Verdict: KEEP — but the indexer is the defect, not the engine.**
- *Strongest argument for:* it is the only engine on this list that combines best-in-class typo
  tolerance (essential for "Lpr Charitable Tr" / "Smith Family Fdn" IRS abbreviations), per-field
  `num_typos=0` for EIN, single-query hybrid with externally-supplied 384-dim vectors, and
  `flat_search_cutoff` — which would let AG **collapse the two-engine drift problem into one engine**
  and simultaneously fix the filtered-KNN latency. That is two of the three named open problems
  solved by a Phase-2 that is already scoped.
- *Strongest argument against:* five months without a release, collapsing commit velocity, 878 open
  issues, single-company governance, and no async Python client. If Typesense stalls, AG is on a
  GPL fork nobody maintains. Meilisearch shipped `v1.53.2` **today** by comparison.

---

### 2.2 Meilisearch — *the strongest switch candidate*

**1. License / governance.** The repo `LICENSE` now reads
`SPDX-License-Identifier: MIT AND BUSL-1.1`
([LICENSE](https://github.com/meilisearch/meilisearch/blob/main/LICENSE)). The
[`LICENSE-EE`](https://github.com/meilisearch/meilisearch/blob/main/LICENSE-EE) is BUSL-1.1 adapted
by Meili SAS: files marked "Enterprise Edition (EE)" living in `enterprise_editions` modules are
non-production-use-only without a commercial agreement, with a **4-year change date to MIT**.
Per Meilisearch's own docs, **"the only feature exclusive to the Enterprise Edition is sharding"**
([enterprise edition docs](https://www.meilisearch.com/docs/resources/self_hosting/enterprise_edition),
[announcement](https://www.meilisearch.com/blog/enterprise-license)). Everything GS/AG would use —
full-text, hybrid/AI search, filtering, faceting, snapshots — is MIT.
**Honest framing:** this is a genuine narrowing versus pure MIT, and the machinery to move more
features behind BUSL now exists. But at 300k docs on one node, sharding will never be wanted, so
the practical exposure today is nil.

**2. Activity — excellent.** 59,206 stars, **only 319 open issues** (the healthiest issue-to-star
ratio on this list by a wide margin), 2,700 forks. Releases `v1.53.2` (2026-09-07), `v1.53.1`
(2026-08-13), `v1.53.0` (2026-08-10), `v1.52.3`, `v1.52.2` — a genuine ~monthly minor cadence with
prompt patches ([releases](https://github.com/meilisearch/meilisearch/releases)).

**3. Architecture.** Rust; **LMDB memory-mapped key-value store** as the index substrate, so the
engine is disk-backed and leans on the OS page cache rather than requiring the whole index resident.
An experimental `MDB_WRITEMAP` option reduces RAM further at some write-speed cost
([discussion #652](https://github.com/orgs/meilisearch/discussions/652)). Writes go through an
**asynchronous task queue** — you enqueue an update and poll the task, which is a materially different
(and for a batch pipeline, friendlier) contract than Typesense's synchronous writes. Durability via
**snapshots** (version-bound, fast restart) and **dumps** (version-portable, requires full reindex on
import) ([snapshots vs dumps](https://www.meilisearch.com/docs/learn/data_backup/snapshots_vs_dumps)).
No Raft; self-hosted HA is not really a thing below the EE sharding tier. Zero-downtime full reindex
is done with **index swap** (`/swap-indexes`), the direct analogue of Typesense aliases.

**4. Hybrid search.** Single query via `hybrid: { semanticRatio, embedder }`, where `semanticRatio`
0.0 = keyword-only and 1.0 = semantic-only, default 0.5
([search API](https://www.meilisearch.com/docs/reference/api/search)). Supports a `userProvided`
embedder — **AG's existing 384-dim vectors go in directly, no embedding calls, no metered LLM on the
query path**, which is a hard requirement in the brief. Vector store was Arroy (Spotify Annoy-derived
trees) and has moved to **Hannoy (graph-based), reported ~10× faster vector search**
([Hannoy post](https://blog.kerollmops.com/from-trees-to-graphs-speeding-up-vector-search-10x-with-hannoy));
binary quantization cuts embedding disk ~6.5× and indexing 5–7×
([BQ post](https://blog.kerollmops.com/meilisearch-indexes-embeddings-7x-faster-with-binary-quantization),
[BQ docs](https://www.meilisearch.com/docs/capabilities/hybrid_search/advanced/binary_quantization)).
Arroy/Hannoy do **filtered disk-ANN with RoaringBitmap filters**
([filtered disk ANN post](https://blog.kerollmops.com/meilisearch-expands-search-power-with-arroy-s-filtered-disk-ann))
— i.e. filters are applied *inside* the ANN traversal, which is the correct answer to the #2025
filtered-recall problem rather than post-filtering. Typo tolerance: up to 2 typos, configurable
per-attribute and disableable on specific attributes (so EIN can be exact)
([typo tolerance spec](https://specs.meilisearch.dev/specifications/text/0117-typo-tolerance-setting-api.html)).
Ranking rules are an *ordered, user-editable list* (words, typo, proximity, attribute, sort,
exactness) — **this is the single best fit for AG's "name tier promoted above RRF" requirement**,
because the name-exactness tier can be expressed declaratively in the ranking rules instead of being
bolted on in Python. Synonyms, filterable attributes, sortable numerics, faceting with configurable
max facet values — all present
([settings API](https://www.meilisearch.com/docs/reference/api/settings)).

**5. Footprint.** Indexing is memory- and CPU-hungry (and cores help more than RAM); search is not
([RAM & multithreading](https://www.meilisearch.com/docs/resources/self_hosting/performance/ram_multithreading)).
Public search benchmarks run 1.2M docs on a 4 vCPU / 8 GB t3.xlarge. **[INFERENCE]** 300k small docs
+ 293k×384-dim BQ-compressed vectors should sit well inside 2–4 GB, and being LMDB-backed it
degrades to disk under pressure rather than OOM-ing the way an in-memory engine does.

**6. Import throughput.** Meilisearch does not publish a docs/sec figure. The 2024 indexer rewrite
claims **~2× faster inserts and ~4× faster incremental updates on large indexes**
([new indexer](https://www.meilisearch.com/blog/introducing-indexer-2024)). Its asynchronous task
model means a bulk load is one HTTP call per batch that returns immediately — **structurally immune
to the synchronous-round-trip failure mode that is plausibly costing GS 3.5 hours.**

**7. Python client.** `meilisearch` **0.43.0**, 2026-07-22, MIT, 68 releases
([PyPI](https://pypi.org/project/meilisearch/)). Official and actively released. There is also an
official `meilisearch-python-sdk` third-party-turned-recommended async client. Sub-1.0 versioning is
cosmetic; the API has been stable for years.

**8. Verdict: the strongest switch candidate — but not urgent.**
- *For:* healthiest project on the list (319 open issues at 59k stars, release today); MIT for
  everything GS needs; disk-backed so it fits a small box gracefully; async task queue removes the
  import-throughput class of bug entirely; **ordered ranking rules can express AG's name tier
  natively**; filtered disk-ANN is the right architecture for the #2025 problem.
- *Against:* a migration costs real weeks for a system that already works, the BUSL carve-out is a
  live (if presently harmless) precedent, and Typesense's typo tolerance and per-field `num_typos`
  are still marginally better for IRS-abbreviated names. **Switching engines does not fix a broken
  indexer — and the indexer is the actual problem.** Do not migrate to solve a bug you have not
  diagnosed.

---

### 2.3 OpenSearch

**1. License / governance.** **Apache-2.0**, and since September 2024 governed by the **OpenSearch
Software Foundation, a Linux Foundation project** — AWS donated it; steering members include AWS,
SAP and Uber. **This is the only genuinely foundation-governed general-purpose option here besides
Solr**, and that is its single biggest structural advantage.

**2. Activity.** 13,675 stars, 2,951 forks, **3,177 open issues**. Releases `3.8.0` (2026-08-05),
`3.7.0` (2026-06-09), `3.6.0` (2026-04-07), plus a maintained `2.19.x` line — roughly an 8-week
minor cadence ([releases](https://github.com/opensearch-project/OpenSearch/releases)).

**3. Architecture.** Lucene segments, JVM, translog for durability, primary/replica shards with
quorum-based cluster state. Segment-merge write model — near-real-time (default 1s refresh), not
truly real-time. Zero-downtime reindex via **index aliases** (the pattern Typesense copied).

**4. Hybrid search.** Two search-pipeline processors: the older `normalization-processor` (min-max or
L2 normalization then weighted combination) and, since 2.19, `score-ranker-processor` implementing
**RRF** ([RRF announcement](https://opensearch.org/blog/introducing-reciprocal-rank-fusion-hybrid-search/),
[score ranker docs](https://docs.opensearch.org/latest/search-plugins/search-pipelines/score-ranker-processor/)).
OpenSearch's own benchmarks put RRF ~3.86% below tuned score normalization on NDCG@10 across six
datasets, with 1–2% better latency. Filtered kNN is well developed (efficient filtering / ACORN-style
pre-filtering in recent Lucene). **Typo tolerance is the weak point** — `fuzziness` is a per-term
edit-distance hack, not the integrated typo-then-rank pipeline that Typesense and Meilisearch have.
For a corpus of IRS-abbreviated names this matters.

**5. Footprint.** JVM. Standard guidance: heap = 50% of container RAM, and the *other* half must be
left for Lucene's `MMapDirectory` page cache. On a 2 GB Railway container that means ~1 GB heap and
~1 GB page cache, which is tight but workable at 300k small docs
([heap sizing](https://opster.com/guides/opensearch/opensearch-basics/opensearch-heap-size-usage-and-jvm-garbage-collection/)).
Container gotchas are the classic JVM ones: `discovery.type=single-node` required, container memory
limits are not automatically respected by older JVM flags, thread pools sized off host CPU count
rather than the cgroup quota. **[INFERENCE] The realistic operating point is 4 GB, not 2.**

**6. Import throughput.** `_bulk` API; well-understood, easily thousands of docs/sec at this size.

**7. Python client.** `opensearch-py` **3.2.0**, 2026-04-27, Apache-2.0, official
([PyPI](https://pypi.org/project/opensearch-py/)). Mature, sync + async, `helpers.bulk` /
`async_bulk` are excellent for exactly GS's job.

**8. Verdict: add only if you need Lucene depth. Not now.**
- *For:* the only foundation-governed engine with modern hybrid search; native S3 snapshots; the best
  bulk-indexing ergonomics in Python; a genuine escape from single-company risk.
- *Against:* a JVM on a 2–4 GB shoestring box is the wrong shape; 3,177 open issues; and its typo
  tolerance is materially worse than the incumbent's for precisely the hardest part of this corpus
  (abbreviated, near-duplicate entity names). You would trade the system's best feature for
  governance you do not yet need.

---

### 2.4 Elasticsearch — license status

Since **August 2024 (landing around 8.16)**, Elasticsearch and Kibana are **triple-licensed: AGPLv3,
ELv2 and SSPL**, with the user choosing
([Elastic announcement](https://www.businesswire.com/news/home/20240829537786/en/Elastic-Announces-Open-Source-License-for-Elasticsearch-and-Kibana-Source-Code),
[licensing FAQ](https://www.elastic.co/pricing/faq/licensing)). AGPLv3 is OSI-approved, so
Elasticsearch is "open source" again. **Free self-hosting is genuinely allowed** under the Basic
tier.

But two things disqualify it here:
1. **AGPLv3 is a network-copyleft licence.** GPL (Typesense) imposes nothing on AG as a network
   service; AGPL does. Even accepting that merely *running* unmodified AGPL software and talking to
   it over HTTP does not taint AG's own code, it is a live question that a small shop should simply
   not have to think about. Typesense's plain GPL-3.0 is strictly safer for this use.
2. **The subscription tiering survives the licence change.** Free/Basic, Gold, Platinum, Enterprise —
   advanced features remain gated regardless of which of the three licences you take
   ([tier comparison](https://pulse.support/kb/elastic-subscriptions-for-elasticsearch)). This is the
   feature-gating risk the brief explicitly wants to avoid.

Activity is enormous (77,904 stars, `v9.5.3` on 2026-09-03) and irrelevant to the decision.
Python client `elasticsearch` 9.5.0 (2026-08-04), 173 releases — best-in-class.

**Verdict: No.** OpenSearch dominates it on every axis this system cares about.

---

### 2.5 Apache Solr

**1. License / governance.** Apache-2.0, **Apache Software Foundation** — the strongest governance
story on the list. No company can relicense it.

**2. Activity.** 1,673 stars on `apache/solr` (the GitHub mirror understates it badly; Solr predates
the split-out repo). **176 open issues** — genuinely well-tended. **Solr 10.0.0 released
2026-03-03**; 9.10.1 maintained ([downloads](https://solr.apache.org/downloads.html)). Solr does not
cut GitHub Releases; it releases through ASF channels, which is why the API returned none.

**3–4. Architecture / hybrid.** Lucene, same segment model as OpenSearch. Solr 10 is a real vector
release: **scalar and binary quantized dense vectors**, `PatienceKnnVectorQuery` (early exit when the
HNSW queue saturates), `SeededKnnVectorQuery`, **ACORN pre-filtering for mixed keyword+kNN queries**,
and cuVS/GPU integration
([Solr 10 vector search](https://sease.io/2026/03/apache-solr-10-what-is-new-for-vector-search.html),
[dense vector search guide](https://solr.apache.org/guide/solr/latest/query-guide/dense-vector-search.html)).
Hybrid fusion is manual (you compose queries and combine) or via LTR — no turnkey RRF processor.

**5. Footprint.** JVM plus a heavy reliance on OS page cache for `MMapDirectory`; docs advise keeping
the heap "as small as possible" and leaving the rest to the OS
([JVM settings](https://solr.apache.org/guide/solr/latest/deployment-guide/jvm-settings.html)). The
Docker image's default heap is too small for production; set `SOLR_HEAP`.

**7. Python client.** `pysolr` 3.11.0, **2025-11-18**, BSD — community-maintained (django-haystack),
noticeably less active than the others.

**8. Verdict: No.** Governance is unimpeachable and Solr 10's vector work is genuinely good, but the
XML/config ergonomics, the JVM footprint, weak typo tolerance, no turnkey hybrid fusion, and a
lukewarm Python client make it the wrong tool for a two-person shoestring shop. It would be a
step backwards in developer velocity for a governance benefit OpenSearch also provides.

---

### 2.6 Vespa

**1–2.** Apache-2.0, Vespa.ai (spun out of Yahoo). 7,077 stars, 253 open issues, and an extraordinary
release cadence — `v8.751.13` on 2026-09-07, multiple releases *per week*
([releases](https://github.com/vespa-engine/vespa/releases)).

**3–4.** The most capable engine here by a distance: true real-time writes, tensor-based ranking,
**phased ranking** (cheap first phase over many candidates, expensive second/global phase over few),
and a native `reciprocal_rank_fusion()` pseudo-function usable directly in a rank profile's global
phase ([phased ranking](https://docs.vespa.ai/en/ranking/phased-ranking.html),
[hybrid tutorial](https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html)). Filtered ANN is
first-class. If AG's ranking problem were the hard part, Vespa is the correct answer.

**5. Footprint — the disqualifier.** Vespa's own docs state a single-node application needs a
**minimum of 4 GB for the Docker container**, 5 GB under Kubernetes, and warn that "too little memory
is a very common problem" and that the getting-started numbers are *minimums to run the guide, not
recommended production settings*
([docker containers](https://docs.vespa.ai/en/operations/self-managed/docker-containers.html),
[node setup](https://docs.vespa.ai/en/operations/self-managed/node-setup.html)). It also runs a
multi-process cluster (config server, container, content node) inside that box.

**7.** `pyvespa` 1.2.5, 2026-09-01 — well maintained.

**8. Verdict: No.** *For:* unmatched ranking expressiveness and the best hybrid model on the list.
*Against:* it wants more RAM to boot than the entire budget for the search tier, and its
application-package/schema/rank-profile deployment model is a genuine multi-week learning
investment. **[INFERENCE]** For a two-person shop this is the classic case of buying capability you
cannot afford to operate.

---

### 2.7 Quickwit / Tantivy

**Quickwit:** Apache-2.0, 11,575 stars, **acquired by Datadog (January 2025)**
([Datadog announcement](https://www.datadoghq.com/blog/datadog-acquires-quickwit/),
[Quickwit's post](https://quickwit.io/blog/quickwit-joins-datadog)). `v0.9.0` on 2026-07-25 — a
single release in the last year, 807 open issues. Post-acquisition the team's stated direction is
relicensing to Apache-2.0 and continued Tantivy work, but the standalone product's cadence has
clearly slowed.

**Disqualifying fact:** **Quickwit does not do document updates.** It targets immutable, append-only
data stored as immutable "splits" on object storage; deletes exist but are long-running background
tasks applied only to *mature* splits and "could last several hours"
([deletes](https://quickwit.io/docs/overview/concepts/deletes),
[replace-documents discussion](https://github.com/quickwit-oss/quickwit/discussions/3886)). A
corpus with rolling enrichment drains, `display_name` backfills and daily gov-opportunity close-date
changes is the exact anti-pattern.

**Tantivy** (MIT, 16,048 stars, 0.26.1 on 2026-05-10) is a *library*, not a server. It matters here
only because **it is the engine underneath ParadeDB `pg_search`** — so Tantivy's health is
ParadeDB's health, and it is healthy.

**Verdict: Quickwit is disqualified. Tantivy is not a candidate but is a good sign for ParadeDB.**

---

### 2.8 Manticore Search — *the dark horse*

**1. License / governance.** **GPL-3.0** for the server, Manticore Buddy and Manticore Backup;
**Apache-2.0** for the Manticore Columnar Library. Single company (Manticore Software), descended
from Sphinx. GPL not AGPL — same clean self-hosting story as Typesense.

**2. Activity.** 11,992 stars, 659 open issues, and a **fast release cadence**: `29.0.2`
(2026-08-14), `28.6.6` (2026-07-31), `28.4.4` (2026-07-10), `27.1.5` (2026-06-19), `25.0.0`
(2026-03-30) ([releases](https://github.com/manticoresoftware/manticoresearch/releases)). Materially
more alive than Typesense right now.

**3. Architecture.** C++. **Both row-wise and columnar storage** — row-wise for hot small data in
RAM, columnar (Apache-2.0 lib) when data exceeds RAM. Real-time indexes support genuine
`REPLACE`/`DELETE`. Speaks the **MySQL wire protocol** plus HTTP/JSON — you can literally query it
with `mysql` or SQLAlchemy-adjacent tooling, which is an unusual operational advantage for a
Python/Postgres shop. Replication via Galera.

**4. Hybrid search.** Since **25.0.0**: full-text (BM25) and KNN run **in parallel** and are merged
with **Reciprocal Rank Fusion**, in a single query
([hybrid search](https://manticoresearch.com/blog/hybrid-search/),
[KNN manual](https://manual.manticoresearch.com/Searching/KNN)). `float_vector` fields with
`knn_type='hnsw'`, `knn_dims`, `hnsw_similarity`. **KNN pre-filtering** shipped in 25.0.0 — again the
correct architecture for the #2025 problem. Fuzzy search and CJK support present.

**5. Footprint.** Low — the columnar path is explicitly designed for data larger than RAM, and the
row-wise path for small data that fits.

**6. Import.** Real-time indexes plus bulk `/bulk` endpoint; also has native indexers that pull
straight from a **SQL source**, i.e. it can be pointed at Postgres directly.

**7. Python client.** `manticoresearch` **11.2.0**, 2026-08-05, MIT, 23 releases
([PyPI](https://pypi.org/project/manticoresearch/)) — official, actively released, but OpenAPI-generated
and less idiomatic than Typesense's or Meilisearch's.

**8. Verdict: genuinely interesting, worth a spike, not a recommendation today.**
- *For:* **native S3 backups** (25.0.0), RRF hybrid in one query with KNN pre-filtering, columnar
  storage that would handle the future multi-million-row `grants` surface where Typesense's
  in-memory model would not, MySQL-protocol access, and a much healthier release cadence than the
  incumbent — all under GPL.
- *Against:* far smaller community than Typesense/Meilisearch for a Python shop; the generated Python
  client is the weakest of the three; typo tolerance is good but not Typesense-grade; and migrating
  to it is the same multi-week cost as migrating to Meilisearch with less community insurance.
  **[INFERENCE]** Its real claim is on the *`grants`* surface (millions of rows, columnar) rather
  than on `foundations`.

---

### 2.9 Sonic

MPL-2.0, 21,335 stars, 64 open issues, `v1.8.1` on 2026-08-16 — alive and tiny. But it is an
**identifier index, not a document index**: it stores only primary keys and returns IDs you then
resolve against your own database, and it has **no relevance scoring, no facets, no aggregations, no
filtering** ([README](https://github.com/valeriansaliou/sonic/blob/master/README.md),
[inner workings](https://github.com/valeriansaliou/sonic/blob/master/INNER_WORKINGS.md)). It runs in
tens of MB and excels at "suggest objects matching this typed prefix".

Python client `sonic-client` 1.0.0 — **last uploaded 2023-06-01**, third-party.

**Verdict: No.** AG needs `filter_by state/min_assets/foundation_code<=4/country=US` and facets on
day one. Sonic cannot do any of it. It would be a plausible *autocomplete* sidecar and nothing more,
and Typesense already does autocomplete better.

---

### 2.10 ZincSearch / OpenObserve

**ZincSearch is dead.** The GitHub API reports `"archived": true` — the repository is read-only. Last
release **v0.4.10, 2024-01-14**; last commit 2026-06-09 and that was a Chinese locale file. The
README still claims active maintenance and "hundreds of production installations", which is now
**contradicted by the repository's own archived flag** — a good example of why the README is not the
source of truth. 17,885 stars, all historical.

**OpenObserve** (AGPL-3.0 + commercial EE, 21,672 stars, `v1.0.0-rc2` on 2026-09-03) is ZincSearch's
successor *for observability*, and the ZincSearch README itself redirects log-search users to it. It
is a logs/metrics/traces/RUM platform storing Parquet on object storage
([repo](https://github.com/openobserve/openobserve)). Its own project history is the argument
against it here: the founders concluded **"index based log search engine is not a good technology for
log search"** and pivoted — the reverse direction is equally true. It is not an application search
engine, has no typo tolerance, no faceted entity search, and is AGPL.

**Verdict: No, twice.** ZincSearch is archived; OpenObserve is the wrong category.

---

### 2.11 Weaviate

BSD-3-Clause (the most permissive licence on this list), single company (Weaviate B.V.), 16,788 stars,
719 open issues, `v1.39.3` released **2026-09-07** with three concurrent maintained lines (1.37/1.38/1.39)
— a strong cadence. Hybrid search combines BM25 and dense vectors in one query with an `alpha`
parameter, offering both RRF and relative-score fusion. HNSW must be resident; roughly **3 GB RAM per
1M 384-dim vectors**, i.e. **~0.9 GB for GS's 300k** — comfortably within budget. **Native
`backup-s3` / `backup-gcs` / `backup-azure` modules with incremental backup support**
([backups](https://docs.weaviate.io/deploy/configuration/backups)). Python client `weaviate-client`
4.23.1 uploaded **2026-09-07**, 296 releases — outstanding.

**Verdict: add-only, and probably not.** *For:* BSD licence, real hybrid, first-class S3 backup,
excellent Python client, fits the RAM budget. *Against:* it is a vector database that grew BM25, not
a text engine — its keyword side has no typo tolerance worth the name, which is the single hardest
requirement in this corpus. Adopting it would replace pgvector, leaving the two-engine drift problem
exactly where it is while adding a third system.

---

### 2.12 Qdrant

Apache-2.0, single company, **34,420 stars** (the most-starred dedicated vector DB), 707 open issues,
`v1.19.1` on 2026-09-04 — very healthy. Since **1.15.2 BM25 sparse-vector conversion happens
server-side** rather than in the client, and the Query API does native hybrid with **RRF or DBSF**
fusion ([hybrid search](https://qdrant.tech/articles/hybrid-search/)). Memmap storage lets the index
exceed RAM using the page cache ([storage](https://qdrant.tech/documentation/concepts/storage/)).
Capacity planning: ~6.11 GB RAM per 1M vectors with HNSW cached at high dimensionality
([capacity planning](https://qdrant.tech/documentation/capacity-planning/)); **[INFERENCE]** at 384
dims and 300k points that scales to roughly **0.6–1 GB**. **Snapshots upload to S3**
([backup discussion](https://github.com/orgs/qdrant/discussions/8649)). `qdrant-client` 1.19.0
(2026-08-04), 125 releases, sync + async — excellent.

**Disqualifier:** Qdrant's text handling is a *filter*, not a search engine. Payload text matching
**requires exact token match**; fuzzy/typo matching is an open feature request
([issue #8278](https://github.com/qdrant/qdrant/issues/8278)), and the docs warn a text index is a
poor fit for identifier-like values because tokenisation breaks them apart
([indexing](https://qdrant.tech/documentation/concepts/indexing/)) — which is exactly what an EIN is.

**Verdict: No.** Best-engineered vector store here, wrong half of the problem. "Lpr Charitable Tr"
searched as "LPR Charitable Trust" would miss.

---

### 2.13 ParadeDB `pg_search` (brief — Lane 4 owns the depth)

AGPL-3.0 (Community; Enterprise is commercial), single company, 9,238 stars, 201 open issues,
`v0.25.6` on **2026-08-27** — a fast, healthy cadence. It is **Tantivy embedded in Postgres via
pgrx**: real BM25 scoring, faceting, `fuzzy_term`, and hybrid search by joining BM25 against pgvector
in plain SQL ([hybrid search in Postgres](https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual)).
Architecturally it is the most attractive answer to *both* named problems at once: **one engine, one
source of truth, no index-to-database consistency problem at all**, because the BM25 index is a
Postgres index maintained by MVCC.

**The blocker, and it is decisive for this system:**
**Neon has deprecated `pg_search`.** Per Neon's own docs, it has been **unavailable for new Neon
projects since 2026-03-19, and existing projects retain access only until 2026-09-21**
([Neon pg_search docs](https://neon.com/docs/extensions/pg_search)). Neon's recommended replacements
are stock `tsvector/tsquery`, `pg_trgm`, `pgvector`, and a new `lakebase_text`.

**[INFERENCE] This is the most time-sensitive item in this report.** GS's corpus lives on Neon. If
any part of the system already uses `pg_search`, it breaks in two weeks. If the plan was to adopt it,
that plan is dead unless GS leaves Neon. Either way it deserves Nathan's attention today, and Lane 4
should verify against the live Neon project rather than trusting this page.

---

## 3. Answer (a): which engines can hold BOTH the keyword index and the 384-dim vectors and do hybrid in one call at ~300k docs on a 2–4 GB box?

**Yes, comfortably, with externally-supplied vectors (no embedding on the query path):**

| Engine | One-call hybrid | Accepts pre-computed 384-dim vectors | Est. RAM @300k | Evidence |
|---|---|---|---|---|
| **Typesense** | `q` + `vector_query`, rank fusion with `alpha` | Yes — `vector_query: "embedding:([0.1,...], k:100)"`, `num_dim: 384` | **~1.1 GB** (0.8 GB vectors by the documented `7 × dims × records` formula + ~0.3 GB keyword) | [vector search](https://typesense.org/docs/30.2/api/vector-search.html), [system requirements](https://typesense.org/docs/guide/system-requirements.html) |
| **Meilisearch** | `hybrid: {semanticRatio, embedder}` | Yes — `userProvided` embedder with `dimensions: 384` | Low; LMDB is disk-backed, BQ shrinks vectors ~6.5× | [search API](https://www.meilisearch.com/docs/reference/api/search), [BQ](https://www.meilisearch.com/docs/capabilities/hybrid_search/advanced/binary_quantization) |
| **Manticore** | BM25 + KNN in parallel, merged by RRF | Yes — `float_vector` with `knn_dims=384` | Low (row + columnar) | [hybrid search](https://manticoresearch.com/blog/hybrid-search/) |
| **Weaviate** | `hybrid(query, vector, alpha)` | Yes — `vectorizer: none` | **~0.9 GB** (~3 GB/1M @384d) | [platform](https://weaviate.io/platform) |
| **Qdrant** | Query API, RRF/DBSF | Yes | **~0.6–1 GB** [INFERENCE] | [hybrid search](https://qdrant.tech/articles/hybrid-search/) |

**Yes, but the box needs to be 4 GB:**
- **OpenSearch** — hybrid query + `score-ranker-processor` (RRF). JVM heap 50% + page cache 50% means
  2 GB is uncomfortably tight. **[INFERENCE]** Plan for 4 GB.
- **Solr 10** — capable but hybrid fusion is hand-rolled.

**No:**
- **Vespa** — needs ≥4–5 GB *before* your data. Blows the budget on arrival.
- **Quickwit, Sonic, ZincSearch, OpenObserve** — no hybrid keyword+dense-vector query at all.

**The practical shortlist for (a): Typesense (already there), Meilisearch, Manticore.** All three
take AG's existing 384-dim vectors directly, so the "no metered LLM on the query path" rule is
preserved, and all three would let AG retire the pgvector arm and **collapse the two-engine ranking
drift into one engine with one ranking function.**

---

## 4. Answer (b): which support incremental upsert + delete well enough to replace nightly full rebuilds?

**Ranked by how well they fit GS's specific pattern — slow-moving foundations, continuous enrichment
drains, bulk `display_name` backfills, daily gov close-date churn.**

1. **Meilisearch — best fit.** Asynchronous task queue: enqueue a batch, get a task ID, poll. Partial
   document updates, delete-by-filter, and `/swap-indexes` for the occasional full rebuild. Crucially
   the 2024 indexer rewrite made **incremental updates on a large index ~4× faster**
   ([new indexer](https://www.meilisearch.com/blog/introducing-indexer-2024)) — incremental is the
   optimised path, not the afterthought. A crashed job is resumable because the task queue is durable.
2. **Typesense — good, and already sufficient.** `action=upsert` (full doc) and `action=emplace`
   (partial, create-or-update); **`PATCH /collections/:c/documents?filter_by=`** for update-by-query
   and **`DELETE /collections/:c/documents?filter_by=&batch_size=`** for delete-by-query
   ([documents API](https://typesense.org/docs/30.2/api/documents.html)). **GS does not need the
   nightly full rebuild at all** — everything required to switch to watermark-driven incremental
   upserts plus tombstone deletes is already in the API GS is calling. *Caveat:* writes are
   synchronous, so the client must own retry/backpressure handling against HTTP 503 `Not Ready or
   Lagging`.
3. **Manticore** — real-time indexes with genuine `REPLACE`/`DELETE`; can also pull directly from a
   SQL source.
4. **OpenSearch / Elasticsearch / Solr** — `_bulk` upserts, `_delete_by_query`, `_update_by_query`;
   entirely adequate, with the standard Lucene caveat that deletes are tombstones reclaimed at merge
   time.
5. **Weaviate / Qdrant** — fine for object upsert/delete, but they only solve the vector half.
6. **Sonic** — push/pop by ID; adequate but the engine is unusable for other reasons.
7. **Quickwit — NO.** No document updates; deletes are hours-long background jobs on mature splits
   only ([deletes](https://quickwit.io/docs/overview/concepts/deletes)). Disqualified.

**[INFERENCE] The most important sentence in this section:** GS's nightly full rebuild is not
required by Typesense. It is a design choice that the engine has offered a documented alternative to
for years. Moving to watermark-driven incremental upserts + tombstone deletes, keeping alias-swap
rebuilds as a *weekly or on-schema-change* operation, would eliminate the 3.5-hour window, the
45-minute Dagster zombie-reaper kill, the orphaned half-built collections, and the two-nights-stale
corpus — **without changing engines at all.**

---

## 5. Answer (c): which have first-class snapshot/backup to object storage?

**First-class, built into the engine — you configure a bucket and call an API:**

| Engine | Mechanism | Evidence |
|---|---|---|
| **OpenSearch / Elasticsearch** | `repository-s3` plugin; register an S3 repo, then snapshot/restore APIs, plus a Snapshot Management policy for scheduling | [snapshot restore](https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/snapshot-restore/) |
| **Weaviate** | `backup-s3` / `backup-gcs` / `backup-azure` modules; credentials verified at init; **incremental** backups; per-class include/exclude | [backups](https://docs.weaviate.io/deploy/configuration/backups) |
| **Qdrant** | Snapshot API with direct upload to S3-compatible object storage | [backup discussion](https://github.com/orgs/qdrant/discussions/8649) |
| **Manticore** | Native S3 backups since **25.0.0** | [25.0.0 release](https://abit.ee/en/soft/manticore-search-2500-hybrid-search-knn-vector-search-open-source-elasticsearch-alternative-en) |
| **Quickwit / OpenObserve** | Object storage *is* the primary store — backup is intrinsic | [Quickwit docs](https://quickwit.io/docs) |
| **Solr** | Backup API supports S3/HDFS repositories | [Solr ref guide](https://solr.apache.org/guide/solr/latest/) |
| **Vespa** | Supported via content-node backup procedures | [Vespa docs](https://docs.vespa.ai/) |

**NOT first-class — local filesystem only, you write the shipping step yourself:**

- **Typesense.** `POST /operations/snapshot` writes to a **directory on the server**; the docs then
  tell you to `tar -czvf` it and move it somewhere yourself. **No S3/B2 target exists.** The docs are
  emphatic that archiving the data directory directly is *unsafe* because Typesense holds open files
  ([backups](https://typesense.org/docs/guide/backups.html)). **[INFERENCE] On Railway this is a real
  gap:** a snapshot written to the same persistent volume you are protecting against is not a backup.
  Someone has to write a sidecar that calls the snapshot endpoint and pushes the tarball to B2. If
  nothing does this today, **a Typesense volume loss means a 3.5-hour rebuild** — which, given the
  nightly job already fails some nights, is not a hypothetical.
- **Meilisearch.** Snapshots and dumps are local files. S3 export has been a long-standing community
  request ([discussion #447](https://github.com/meilisearch/product/discussions/447),
  [discussion #869](https://github.com/orgs/meilisearch/discussions/869)) with third-party sidecars
  filling the gap. Same shape of gap as Typesense.
- **Sonic** — none.

**[INFERENCE] For GS/AG this criterion is close to irrelevant to the engine choice**, because the
index is 100% derived from Neon. The correct disaster-recovery story is "rebuild from Postgres", and
the correct thing to optimise is therefore **rebuild speed** — which loops straight back to §6. A
20-minute rebuild makes backups unnecessary; a 3.5-hour rebuild makes them mandatory.

---

## 6. The 203k-docs-in-3.5-hours question

### 6.1 The arithmetic

| Source | Throughput | Ratio vs GS |
|---|---|---|
| **GS actual** | 203,000 docs ÷ 12,600 s = **~16 docs/sec** | 1× |
| Typesense benchmark — 2.2M recipes, 3.6 min, 4 vCPU | **~10,185 docs/sec** | **637× faster** |
| Typesense benchmark — 28M books, 78 min, 4 vCPU | **~5,983 docs/sec** | **374× faster** |
| Worst case in Typesense's own bug tracker (issue #2312, 20M docs of 2.5 KB each, user complaining bitterly) | 65k–100k docs/min = **1,083–1,667 docs/sec** | **68–104× faster** |
| Community report: 600k docs over ~60 h on 2 vCPU / 16 GB | **~2.8 docs/sec** | 0.17× (worse) |

Sources: [Typesense benchmarks](https://typesense.org/docs/overview/benchmarks.html),
[issue #2312](https://github.com/typesense/typesense/issues/2312),
[community thread](https://threads.typesense.org/t/29394442/hey-i-ve-been-trying-to-optimize-sync-performance-for-one-of).

### 6.2 Is 16 docs/sec plausible *for Typesense*?

**No — not as an engine characteristic.** GS's documents are *smaller* than every benchmark corpus
(a name, an EIN, a city, a state, three codes, an int64 and a slug — call it 200–400 bytes against
2.5 KB in the worst-case bug report). By document size GS should be at the *fast* end. Being 374–637×
below the vendor benchmark and 68–104× below the worst documented complaint means **this is a
client-side or transport defect, not Typesense being slow.**

The one comparable data point — 2.8 docs/sec, 600k docs over 60 hours — was on **2 vCPU**, and
Typesense's docs say plainly that **"a minimum of 4 CPU cores is recommended for high volume writes"**
([syncing data](https://typesense.org/docs/guide/syncing-data-into-typesense.html)). So a
CPU-starved container is a live hypothesis too.

### 6.3 Candidate causes, ranked

**1. Cross-Railway-project HTTP over a public TLS domain — the strongest candidate. [INFERENCE]**
The brief says the Typesense container lives in the **AG** Railway project, and the reindex is run by
**GS**. Railway's private network is explicitly **project-scoped**: *"services in different projects
cannot communicate over the private network"*, and cross-project traffic must go over a public domain
and incurs $0.10/GB egress
([private networking](https://docs.railway.com/networking/private-networking),
[how it works](https://docs.railway.com/networking/private-networking/how-it-works)).

So every import batch is: public DNS → Railway edge → **full TLS handshake if the connection is not
being reused** → proxy → container. If the Python client is opening a new connection per batch (or
per document), the per-request cost is tens to hundreds of milliseconds of pure round-trip before a
single byte is indexed. At 16 docs/sec, GS is spending ~62 ms per document. **That number is the
right order of magnitude for one un-pooled TLS round trip per document, or per very small batch.**

*How to test in five minutes:* time a single `/import` call with 10,000 documents from the GS box and
compute docs/sec for that one call. If one 10k call takes ~2 seconds (5,000 docs/sec) but the full
job runs at 16 docs/sec, the engine is innocent and the loop is the bug.

**2. Batch size far too small, or single-document writes.** Typesense's docs are blunt: *"sending
10,000 documents over 10,000 different single API calls is going to be an order of magnitude more CPU
intensive and slower than sending those 10K documents in a single bulk import API call"*
([syncing data](https://typesense.org/docs/guide/syncing-data-into-typesense.html)). The guidance is
**client-side batching** — many documents per `/import` call, several calls in parallel — and to
**leave the server-side `batch_size` at its default of 40**, which only controls how often the server
pauses importing to service the search queue and is *not* a client batching knob. **[INFERENCE] A
common misreading is to set the client's batch to 40 because 40 is the documented default.** Worth
checking GS's indexer for exactly that.

**3. No parallelism.** Documented guidance: run up to **N−2 concurrent bulk imports** where N is the
number of CPU cores available to Typesense. A single-threaded importer leaves most of the box idle —
consistent with [issue #2312](https://github.com/typesense/typesense/issues/2312), where the reporter
found indexing concurrency hardcoded to 4 and only 2–3 cores active. The **official Python client is
synchronous with no async support**, so a naive `for batch in batches: client.import_(batch)` loop is
the default outcome unless someone deliberately added a thread pool.

**4. `return_doc` / `return_id` echoing the corpus back.** `return_doc=true` makes the response carry
**the entire document object for every imported document**
([documents API](https://typesense.org/docs/30.2/api/documents.html)). Over a public Railway domain
that doubles the bytes on the wire *and* adds egress cost. **[INFERENCE]** If GS sets `return_doc`
(or logs full responses), that is free money and free time being burned.

**5. A CPU-starved container hitting 503 backpressure, then retrying.** Under write pressure Typesense
returns HTTP 503 `Not Ready or Lagging` by design. The official remedies are: **add CPU cores
(minimum 4 for heavy writes)**, raise the client timeout to as much as **60 minutes** so writes are
never aborted mid-flight, and add **jittered retries of 10–60 seconds** — because short client
timeouts cause retries that "lead to a thundering herd issue"
([syncing data](https://typesense.org/docs/guide/syncing-data-into-typesense.html)). **[INFERENCE] A
retry storm is the one mechanism that can produce a number as extreme as 16 docs/sec while every
individual component looks healthy** — most of the wall clock is spent re-sending batches that were
already accepted. It would also explain why the job time varies enough that a 45-minute reaper
sometimes catches it and sometimes does not.

**6. Remote/network volume.** Railway volumes are network-attached. RocksDB write amplification
during a full reimport is documented ([issue #2005](https://github.com/typesense/typesense/issues/2005)
— disk grew to ~12× RAM from repeated daily bulk imports; [issue #2312] measured 10–20 MB/s of
network input producing 500–800 MB/s of disk writes from undersized RocksDB write buffers). **[INFERENCE]**
Contributory, not primary — this would cost a factor of 2–5, not a factor of 600.

### 6.4 The recommended diagnostic order

1. **Time one `/import` call of 10,000 docs** from the GS box and compute its docs/sec in isolation.
   This single measurement separates "engine/transport" from "loop".
2. **Read GS's indexer for the client-side batch size.** If it is 40, 100 or 500, raise it to
   5,000–10,000 documents per call.
3. **Check whether `return_doc` / `return_id` is set.** Turn it off.
4. **Check connection reuse** — one `requests.Session` (or the Typesense client instance) for the
   whole job, not one per batch.
5. **Check the Typesense container's vCPU allocation.** Below 4, raise it; then run `N−2` import
   workers in parallel.
6. **Check for 503s in the Typesense logs during the window.** If they are there, the fix is CPU plus
   jittered retries plus a 60-minute client timeout — not a bigger batch.
7. **Only then** consider whether the nightly full rebuild is needed at all (see §4).

**[INFERENCE] Expected outcome: a correctly batched, connection-pooled, parallel importer against a
4-vCPU Typesense should put 203k small documents in well under ten minutes.** That single change
retires the 45-minute-reaper failure, the orphaned collections and the stale-corpus problem without
touching the engine, the schema, or AG.

---

## 7. Recommendation from this lane

**Headline: the engine is not the problem. Keep Typesense for now; fix the indexer; and put
Meilisearch on the table as a deliberate, unhurried decision rather than a panic response.**

**Do now (days, and none of it requires changing engines):**

1. **Diagnose the 16 docs/sec** with the seven-step order in §6.4, starting with a single timed 10k
   `/import` call. Everything else in this report is subordinate to that measurement. My strongest
   hypothesis is **cross-Railway-project public-domain HTTP without connection reuse, small batches,
   and no parallelism**, possibly compounded by a 503 retry storm on an under-provisioned container.
2. **Raise `pg_search` on Neon with Nathan today.** It is unavailable to new Neon projects since
   2026-03-19 and existing projects lose it **2026-09-21**
   ([Neon docs](https://neon.com/docs/extensions/pg_search)). Verify against the live project. This
   is the only item in this report with a deadline.
3. **Establish whether the Typesense snapshot is being shipped off the Railway volume.** Typesense has
   no object-storage backup target; a snapshot on the volume it protects is not a backup
   ([backups](https://typesense.org/docs/guide/backups.html)).
4. **Check the Typesense volume's growth curve** against issue #2005 — nightly full reimports are the
   exact pattern that produced 12× disk bloat for another user.

**Do next (weeks, still no engine change):**

5. **Replace the nightly full rebuild with watermark-driven incremental upserts + tombstone deletes**,
   keeping alias-swap rebuilds for schema changes and a weekly reconciliation. Typesense already
   exposes everything needed: `emplace`, `PATCH ?filter_by`, `DELETE ?filter_by`. This kills the
   fragility class outright.
6. **Execute the Phase-2 vector push into Typesense** and retire the pgvector search arm. This is the
   highest-leverage architectural move available, because it resolves **two** of the brief's three
   named problems in one step: two-engine ranking drift disappears (one engine, one fusion function,
   one ranking path — no more fail-open to a differently-ranked Postgres path), and the filtered-KNN
   latency problem (#2025, 1.7–2.8 s) gets `flat_search_cutoff`, which degrades to exact search
   exactly when the filter is selective — the case where post-filtered HNSW currently wanders. Cost:
   `7 × 384 × 300,000 ≈ 806 MB` of additional RAM, which fits the box.

**Watch, and revisit in ~6 months:**

7. **Typesense's release cadence.** If there is no stable release after `v30.2` (2026-04-19) by, say,
   the end of 2026, treat that as the trigger to migrate rather than as background noise. The commit
   trend over the last quarter is a genuine 4× slowdown and 878 issues are open.
8. **Meilisearch is the migration target if that trigger fires.** MIT for everything relevant,
   released today, 319 open issues against 59k stars, disk-backed LMDB that suits a small box, an
   async task queue that structurally cannot produce the import bug GS has, filtered disk-ANN, and —
   the underrated part — **ordered ranking rules that could express AG's "name tier above RRF"
   declaratively instead of in Python**. The BUSL-1.1 carve-out (sharding only) should be re-checked
   at that point, not assumed static.
9. **Manticore for the future `grants` surface.** When `grants` becomes a search surface at millions
   of rows, Typesense's in-memory model gets expensive fast. Manticore's Apache-2.0 columnar storage
   is explicitly built for data larger than RAM, does BM25+KNN RRF hybrid in one query, and has native
   S3 backups. Worth a spike then, not now.

**Explicitly rejected, with reasons:** Elasticsearch (AGPL + surviving feature tiers), Vespa (needs
more RAM to boot than the whole budget), Solr (JVM + poor ergonomics + weak Python client), Quickwit
(no document updates — disqualified), Sonic (ID index, no filters or facets), ZincSearch (**archived
repository**), OpenObserve (observability, not app search), Qdrant (no typo tolerance; exact token
match only — fatal for IRS-abbreviated names), Weaviate (vector DB with bolt-on BM25; would add a
third system without removing the drift). OpenSearch is the only rejected candidate worth
reconsidering, and only if foundation governance becomes a requirement — at which point budget 4 GB,
not 2, and accept materially worse typo tolerance on the hardest part of this corpus.

---

## 8. Sources

Live GitHub API queries (2026-09-07) for stars, open issues, licences, archive status, release tags
and commit participation on: typesense/typesense, meilisearch/meilisearch,
opensearch-project/OpenSearch, elastic/elasticsearch, apache/solr, vespa-engine/vespa,
quickwit-oss/quickwit, quickwit-oss/tantivy, manticoresoftware/manticoresearch, valeriansaliou/sonic,
zincsearch/zincsearch, openobserve/openobserve, weaviate/weaviate, qdrant/qdrant, paradedb/paradedb.
Live PyPI JSON API queries for: typesense, meilisearch, opensearch-py, elasticsearch, pysolr,
qdrant-client, weaviate-client, manticoresearch, pyvespa, sonic-client.

- Typesense: [benchmarks](https://typesense.org/docs/overview/benchmarks.html) · [system requirements](https://typesense.org/docs/guide/system-requirements.html) · [syncing data](https://typesense.org/docs/guide/syncing-data-into-typesense.html) · [documents API](https://typesense.org/docs/30.2/api/documents.html) · [vector search](https://typesense.org/docs/30.2/api/vector-search.html) · [collection aliases](https://typesense.org/docs/30.2/api/collection-alias.html) · [backups](https://typesense.org/docs/guide/backups.html) · [high availability](https://typesense.org/docs/guide/high-availability.html) · [cluster operations](https://typesense.org/docs/30.2/api/cluster-operations.html) · [ranking and relevance](https://typesense.org/docs/guide/ranking-and-relevance.html) · [issue #2312](https://github.com/typesense/typesense/issues/2312) · [issue #2005](https://github.com/typesense/typesense/issues/2005) · [issue #774](https://github.com/typesense/typesense/issues/774)
- Meilisearch: [LICENSE](https://github.com/meilisearch/meilisearch/blob/main/LICENSE) · [LICENSE-EE](https://github.com/meilisearch/meilisearch/blob/main/LICENSE-EE) · [enterprise edition docs](https://www.meilisearch.com/docs/resources/self_hosting/enterprise_edition) · [EE announcement](https://www.meilisearch.com/blog/enterprise-license) · [search API](https://www.meilisearch.com/docs/reference/api/search) · [settings API](https://www.meilisearch.com/docs/reference/api/settings) · [snapshots vs dumps](https://www.meilisearch.com/docs/learn/data_backup/snapshots_vs_dumps) · [new indexer](https://www.meilisearch.com/blog/introducing-indexer-2024) · [RAM & multithreading](https://www.meilisearch.com/docs/resources/self_hosting/performance/ram_multithreading) · [binary quantization](https://www.meilisearch.com/docs/capabilities/hybrid_search/advanced/binary_quantization) · [Hannoy](https://blog.kerollmops.com/from-trees-to-graphs-speeding-up-vector-search-10x-with-hannoy) · [filtered disk ANN](https://blog.kerollmops.com/meilisearch-expands-search-power-with-arroy-s-filtered-disk-ann) · [typo tolerance spec](https://specs.meilisearch.dev/specifications/text/0117-typo-tolerance-setting-api.html)
- OpenSearch: [RRF announcement](https://opensearch.org/blog/introducing-reciprocal-rank-fusion-hybrid-search/) · [score ranker processor](https://docs.opensearch.org/latest/search-plugins/search-pipelines/score-ranker-processor/) · [snapshot restore](https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/snapshot-restore/) · [heap sizing](https://opster.com/guides/opensearch/opensearch-basics/opensearch-heap-size-usage-and-jvm-garbage-collection/)
- Elasticsearch: [licence announcement](https://www.businesswire.com/news/home/20240829537786/en/Elastic-Announces-Open-Source-License-for-Elasticsearch-and-Kibana-Source-Code) · [licensing FAQ](https://www.elastic.co/pricing/faq/licensing)
- Solr: [downloads](https://solr.apache.org/downloads.html) · [dense vector search](https://solr.apache.org/guide/solr/latest/query-guide/dense-vector-search.html) · [JVM settings](https://solr.apache.org/guide/solr/latest/deployment-guide/jvm-settings.html) · [Solr 10 vector search](https://sease.io/2026/03/apache-solr-10-what-is-new-for-vector-search.html)
- Vespa: [docker containers](https://docs.vespa.ai/en/operations/self-managed/docker-containers.html) · [node setup](https://docs.vespa.ai/en/operations/self-managed/node-setup.html) · [phased ranking](https://docs.vespa.ai/en/ranking/phased-ranking.html) · [hybrid tutorial](https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html)
- Quickwit: [Datadog acquisition](https://www.datadoghq.com/blog/datadog-acquires-quickwit/) · [Quickwit joins Datadog](https://quickwit.io/blog/quickwit-joins-datadog) · [deletes](https://quickwit.io/docs/overview/concepts/deletes) · [replace documents discussion](https://github.com/quickwit-oss/quickwit/discussions/3886)
- Manticore: [hybrid search](https://manticoresearch.com/blog/hybrid-search/) · [KNN manual](https://manual.manticoresearch.com/Searching/KNN) · [repo](https://github.com/manticoresoftware/manticoresearch)
- Sonic: [README](https://github.com/valeriansaliou/sonic/blob/master/README.md) · [inner workings](https://github.com/valeriansaliou/sonic/blob/master/INNER_WORKINGS.md)
- ZincSearch / OpenObserve: [ZincSearch repo (archived)](https://github.com/zincsearch/zincsearch) · [ZincSearch future issue #782](https://github.com/zincsearch/zincsearch/issues/782) · [OpenObserve repo](https://github.com/openobserve/openobserve)
- Weaviate: [backups](https://docs.weaviate.io/deploy/configuration/backups) · [platform](https://weaviate.io/platform)
- Qdrant: [hybrid search](https://qdrant.tech/articles/hybrid-search/) · [capacity planning](https://qdrant.tech/documentation/capacity-planning/) · [storage](https://qdrant.tech/documentation/concepts/storage/) · [indexing](https://qdrant.tech/documentation/concepts/indexing/) · [fuzzy match request #8278](https://github.com/qdrant/qdrant/issues/8278) · [backup discussion](https://github.com/orgs/qdrant/discussions/8649)
- ParadeDB: [repo](https://github.com/paradedb/paradedb) · [hybrid search in Postgres](https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual) · [Neon pg_search deprecation](https://neon.com/docs/extensions/pg_search)
- Railway: [private networking](https://docs.railway.com/networking/private-networking) · [how private networking works](https://docs.railway.com/networking/private-networking/how-it-works)

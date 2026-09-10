# Lane 3 — Hybrid retrieval, ranking, entity-name matching, and search-quality evaluation

Research for GrantSpider (GS) / AI Grant Helper (AG). Every factual claim carries a URL.
Statements marked **[INFERENCE]** are my reasoning, not documented fact.

---

## 1. Hybrid fusion implementations

### 1.1 What each engine actually does

| Engine | Fusion mechanism | Parameter | Documented default |
|---|---|---|---|
| Elasticsearch | `rrf` retriever (rank-based) **and** `linear` retriever (score-based, weighted sum with per-retriever normalizer) | `rank_constant`, `rank_window_size`; `weight` + `normalizer` | `rank_constant: 60`, `rank_window_size: 10` |
| OpenSearch | `normalization-processor` (score-based) **and** `score-ranker-processor` (RRF, rank-based) | `normalization.technique` ∈ {`min_max`, `l2`, `z_score`}; `combination.technique` ∈ {`arithmetic_mean`, `geometric_mean`, `harmonic_mean`}; `weights[]` must sum to 1.0 | `min_max` + `arithmetic_mean`, equal weights |
| Weaviate | `rankedFusion` (rank) vs `relativeScoreFusion` (min-max score) | `alpha` (0 = pure BM25, 1 = pure vector), `fusionType` | `relativeScoreFusion` since v1.24 |
| Vespa | Rank profiles with `first-phase` / `second-phase` / `global-phase`; `reciprocal_rank_fusion()`, `normalize_linear()`, arbitrary expressions | `rerank-count` | none — you write the expression |
| Typesense | Rank fusion of the keyword arm and the vector arm | `vector_query: "embedding:([], alpha: 0.8)"`; `rerank_hybrid_matches` | keyword 0.7 / vector 0.3 |
| Meilisearch | `hybrid` search, "smart scoring system" merge | `semanticRatio` | **0.5** |
| Qdrant | `prefetch` + `query: {fusion: ...}` | `rrf` (with `k`, default 2, and `weights[]`) or `dbsf` (distribution-based score fusion, 3-sigma normalization) | — |
| Postgres-only | Hand-written RRF CTE over two `ROW_NUMBER()` rankings | `k` (conventionally 60), per-arm weight multiplier | — |

Sources:
- Elasticsearch RRF retriever, `rank_constant` = 60 and `rank_window_size` = 10: <https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrievers/rrf-retriever>
- Elasticsearch linear retriever (weighted sum, per-retriever normalizer, minmax): <https://www.elastic.co/docs/reference/elasticsearch/rest-apis/retrievers/linear-retriever> and the introducing post <https://www.elastic.co/search-labs/blog/linear-retriever-hybrid-search> (implementation PR: <https://github.com/elastic/elasticsearch/pull/120222>)
- Elasticsearch weighted RRF (`weight × 1/(rank + rank_constant)`): <https://www.elastic.co/search-labs/blog/weighted-reciprocal-rank-fusion-rrf>
- OpenSearch normalization-processor full parameter table (min_max default, arithmetic_mean default, weights must sum to 1.0, `z_score` only supports arithmetic_mean, and the newer `lower_bounds`/`upper_bounds` clipping modes): <https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/>
- OpenSearch hybrid search overview and score-ranker (RRF) processor: <https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/>
- Weaviate hybrid search + alpha + fusion types: <https://docs.weaviate.io/weaviate/search/hybrid> and concepts <https://docs.weaviate.io/weaviate/concepts/search/hybrid-search>
- Weaviate fusion-algorithm deep dive with the `1/(RANK + 60)` formula: <https://weaviate.io/blog/hybrid-search-fusion-algorithms>
- Vespa phased ranking: <https://docs.vespa.ai/en/ranking/phased-ranking.html>; hybrid tutorial with rank profiles: <https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html>
- Typesense vector/hybrid search (alpha, `rerank_hybrid_matches`, `distance_threshold`): <https://typesense.org/docs/30.2/api/vector-search.html>
- Meilisearch `hybrid.semanticRatio` default 0.5 and `rankingScoreThreshold`: <https://www.meilisearch.com/docs/reference/api/search>
- Qdrant hybrid queries (prefetch, `rrf` with `k` default 2 and `weights`, `dbsf`, formula queries since v1.14): <https://qdrant.tech/documentation/concepts/hybrid-queries/>
- ParadeDB Postgres RRF CTE and weighted variant: <https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual>

### 1.2 Which fusion wins in published comparisons

The literature and the vendors converge on the same answer, and it is **not** RRF:

- **Bruch et al., "An Analysis of Fusion Functions for Hybrid Retrieval"** (TOIS 2023, arXiv 2210.11934): convex combination (CC) of normalized lexical and semantic scores **outperforms RRF in-domain and out-of-domain**; RRF is sensitive to its parameters and a tuned RRF "generalizes poorly to out-of-domain datasets"; CC needs only a small labelled set to tune its single parameter. <https://arxiv.org/abs/2210.11934> · <https://dl.acm.org/doi/10.1145/3596512> · summary <https://www.pinecone.io/research/an-analysis-of-fusion-functions-for-hybrid-retrieval/>
- **Vespa's own hybrid tutorial** publishes nDCG@10 per rank profile on its dataset: BM25 0.3210, semantic 0.3077, hybrid (multiplicative) 0.3330, **hybrid RRF 0.3233**, hybrid atan-normalized 0.3410, **hybrid linear-normalized 0.3423**. RRF barely beat BM25 alone; both score-normalizing profiles beat it by ~2 nDCG points. <https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html>
- **Weaviate** measured **~6% recall improvement** for `relativeScoreFusion` over `rankedFusion` on FIQA, and made it the default in v1.24. <https://weaviate.io/blog/hybrid-search-fusion-algorithms>
- **OpenSearch** measured `z_score` normalization at **+2.08% NDCG@10 on average over min_max across four datasets**, at <1% latency cost. <https://opensearch.org/blog/introducing-the-z-score-normalization-technique-for-hybrid-search/>
- The consensus operational advice (Eliatra, BigDataBoutique, OpenSearch docs): RRF is the plug-and-play baseline that needs no labelled data; a normalized weighted sum slightly beats it *once you have an evaluation set*. <https://eliatra.com/blog/an-overview-of-rank-normalization-in-hybrid-search/> · <https://bigdataboutique.com/blog/hybrid-search-explained>

**The evidence is consistent: RRF is the right thing to ship before you have judgments, and the wrong thing to keep after you have them.**

### 1.3 The failure mode we hit — dual-arm generic beats single-arm exact

This is a structural property of RRF, not a bug. RRF discards score magnitude: a document at rank 5 in both arms scores `2/(60+5) = 0.0308`, while a document at rank 1 in one arm and absent from the other scores `1/(60+1) = 0.0164`. **A mediocre document present in both lists mathematically outranks a perfect single-arm match.** Weaviate names exactly this failure: rankedFusion "only retains the rankings" and loses the information that "a significantly better keyword match" beat the runner-up by a mile rather than a hair (<https://weaviate.io/blog/hybrid-search-fusion-algorithms>).

Typesense has an additional, *documented-as-open* wrinkle that matters directly to us. The published formula is `rank_fusion_score = 0.7 * K + 0.3 * S` where K and S are **ranks** (<https://typesense.org/docs/30.2/api/vector-search.html>). Issue #2162 points out that as written this promotes documents with *higher* rank numbers, and that ties in `_text_match` are broken arbitrarily by document id, which then dominates the fused order. The issue is **open, unassigned, no milestone**. Companion reports: #2163 (same), #1966 (asking for rank-fusion internals to be exposed), #1811 (how to threshold on the fused score), #1964 ("hybrid search gives bad results").
- <https://github.com/typesense/typesense/issues/2162>
- <https://github.com/typesense/typesense/issues/2163>
- <https://github.com/typesense/typesense/issues/1966>
- <https://github.com/typesense/typesense/issues/1811>
- <https://github.com/typesense/typesense/issues/1964>

**[INFERENCE]** If GS/AG ever push vectors into Typesense (the stated Phase 2), we would be adopting a fusion implementation with an open correctness complaint and no way to inspect the per-arm ranks. That is a reason to keep fusion in our own code, where we control it.

### 1.4 How the field does exact-match / "name tier"

Nobody relies on fusion alone for exact matches. Every mature engine provides an out-of-band tier:

- **Elasticsearch**: a `bool` with a high-`boost` `should` clause on a `keyword` (or `.exact`) subfield, so an exact term match adds a large constant to the score; `constant_score` to contribute a fixed amount irrespective of TF/IDF; `rank_feature` / `rank_feature` decay functions for static signals like asset size. Boost is *not* linear — boost 2 does not double the score. <https://www.elastic.co/blog/how-to-improve-elasticsearch-search-relevance-with-boolean-queries> · <https://forloop.co.uk/blog/favouring-exact-matches-in-elasticsearch> · <https://opster.com/guides/elasticsearch/search-apis/boosting-query/>
- **Vespa**: the phased model *is* the tiering. Cheap `first-phase` over everything, expensive `second-phase` over the top-N per node, `global-phase` over the merged top-N in the container. You can put a hard exact-name term in the first phase and let fusion only reorder within a tier. <https://docs.vespa.ai/en/ranking/phased-ranking.html>
- **Typesense** gives you four distinct levers, which is more than we currently use:
  - `prioritize_exact_match` — **default `true`**: "Typesense prioritizes documents whose field value matches exactly with the query."
  - `text_match_type` ∈ {`max_score` (default), `max_weight`, `sum_score`} — changes whether one field's strong match or many fields' weak matches wins.
  - `query_by_weights` — per-field weights 0–127.
  - `sort_by` with `_eval(<filter expression>):desc` — **an arbitrary boolean predicate as a sort tier, evaluated before `_text_match`**. This is the sanctioned way to express "exact name first, then everything else."
  - `pinned_hits` / `hidden_hits` and the curation/override rules (`rule.match: exact|contains`, `includes` with positions, `stop_processing`), migrated in v30 from `/collections/{c}/overrides` to `/curation_sets`.
  - <https://typesense.org/docs/30.2/api/search.html> · <https://typesense.org/docs/30.2/api/curation.html>
- **Meilisearch** solves it with an ordered ranking-rule pipeline rather than a score: `words → typo → proximity → attributeRank → sort → wordPosition → exactness`. `exactness` ranks documents by "the similarity of the matched words with the query words." Because the rules are lexicographic, an earlier rule cannot be outvoted by a later one — the tiering is the whole design. <https://www.meilisearch.com/docs/learn/relevancy/ranking_rules>
- **Qdrant** since v1.14 lets you write a `formula` over `$score` plus payload fields with decay helpers — i.e. a post-fusion boost expression. <https://qdrant.tech/documentation/concepts/hybrid-queries/>

**What this implies for GS/AG.** Our current shape — RRF with a name tier bolted on above it — is the *correct instinct* and matches how Typesense (`_eval` sort tier), Meilisearch (`exactness` rule) and Vespa (phased ranking) all do it. The defect is not the tier; it is that RRF underneath the tier is the weakest documented fusion function, and we run it without any evaluation set that would let us tune something better. Two concrete moves fall out. (a) Replace weighted RRF with a **min-max-normalized convex combination** in `ag_research` — this is one SQL change (normalize each arm's score inside its CTE instead of taking `ROW_NUMBER()`), it is what Weaviate/Elastic/OpenSearch all default to now, and Bruch et al. say a single weight tuned on a handful of queries beats a tuned RRF out-of-domain. (b) On the Typesense arm, we are leaving `sort_by: _eval(...):desc` on the table: an exact/prefix name predicate expressed as an `_eval` tier runs *inside* Typesense, which means the two paths (Typesense and Postgres) can be made to agree on tiering rather than only on the fallback. **[INFERENCE]** the two-path ranking drift the brief names is mostly a *tiering* drift, not a fusion drift, because the name tier currently exists only in AG's Python.

---

## 2. Re-ranking on CPU

### 2.1 Measured CPU throughput (this is the number that matters)

The Ettin reranker release publishes a **CPU** throughput table on an Intel Core i7-13700K, bfloat16 + SDPA, Natural Questions, `max_length=512`:

| Model | Params | pairs/sec (CPU) |
|---|---|---|
| `cross-encoder/ettin-reranker-17m-v1` | 17M | 267.4 |
| `cross-encoder/ms-marco-MiniLM-L4-v2` | 19M | 206.2 |
| `cross-encoder/ms-marco-MiniLM-L6-v2` | 22M | 143.9 |
| `cross-encoder/ettin-reranker-32m-v1` | 32M | 92.5 |
| `cross-encoder/ms-marco-MiniLM-L12-v2` | 33M | 75.9 |

All Apache 2.0. <https://huggingface.co/blog/ettin-reranker>

Quality on the same family (V100 GPU, so the Docs/Sec column there is *not* comparable to the table above): `ms-marco-MiniLM-L6-v2` nDCG@10 74.30 on TREC DL 19, MRR@10 39.01 on MS MARCO dev; `L12-v2` 74.31 / 39.02 — i.e. **L12 buys essentially nothing over L6** and costs half the throughput. `TinyBERT-L2-v2` drops to 69.84 / 32.56. <https://www.sbert.net/docs/pretrained-models/ce-msmarco.html>

**Arithmetic for our case:** top-50 rerank with `L6-v2` at 143.9 pairs/s ≈ **347 ms at 512 tokens**. **[INFERENCE]** our reranked units are foundation *names plus a short prose snippet*, well under 128 tokens, so real latency should be several times lower — but this is an inference from the quadratic-ish attention cost, not a published measurement, and must be benchmarked on the actual Railway CPU before it is believed. Also note the documented trap: batch the pairs — "looping over single pairs reduces throughput by 10-50x."

### 2.2 The runtimes

- **FlashRank** (Apache 2.0, ~1.0k stars): ONNX-based, runs "without Torch or Transformers needed", CPU-targeted. Models: `ms-marco-TinyBERT-L-2-v2` ~4 MB (default), `ms-marco-MiniLM-L-12-v2` ~34 MB (best cross-encoder), `rank-T5-flan` ~110 MB (best zero-shot), `ms-marco-MultiBERT-L-12` ~150 MB (100+ languages), `rank_zephyr_7b_v1_full` ~4 GB (listwise LLM, 4-bit GGUF). <https://github.com/PrithivirajDamodaran/FlashRank>
- **rerankers** (Answer.AI) — one API over cross-encoders, FlashRank/ONNX, ColBERT, RankLLM/RankZephyr, API rerankers. Low-dependency; the sane way to A/B two rerankers without rewriting glue. <https://github.com/AnswerDotAI/rerankers> · <https://www.answer.ai/posts/2024-09-16-rerankers.html>
- **bge-reranker-v2-m3** — 568M params, Apache 2.0, multilingual, distilled from BGE-M3. <https://huggingface.co/BAAI/bge-reranker-v2-m3> · <https://bge-model.com/bge/bge_reranker_v2.html>
- **mxbai-rerank-xsmall-v1** — ~70–100M params, Apache 2.0. Reported 0.11 s/query vs 0.14 s/query for bge-reranker-v2-m3 on Scholar QA; the mxbai family is DeBERTa-v2-based, which **does not support Flash Attention 2 or SDPA**, so it is slower than its parameter count suggests. <https://huggingface.co/mixedbread-ai/mxbai-rerank-xsmall-v1> · <https://www.mixedbread.com/docs/models/reranking/mxbai-rerank-xsmall-v1> · <https://github.com/mixedbread-ai/mxbai-rerank>

**[INFERENCE, load-bearing]** For 300k foundation *names*, a cross-encoder reranker is close to the wrong tool. Cross-encoders are trained on passage relevance (MS MARCO); the discriminating signal in "Lpr Charitable Tr" vs "LPR Foundation" is orthographic and abbreviational, not semantic. A 22M cross-encoder will happily rank "Smith Family Foundation" above "Smith Fdn" for the query "Smith Fdn" because it has no notion that "Fdn" abbreviates "Foundation". A **rapidfuzz `token_set_ratio` / Jaro-Winkler rescore over the top-50, after abbreviation expansion**, is likely both faster (microseconds) and more accurate for the name arm — and it is exactly what the entity-matching world does (§3). Reserve the cross-encoder for the *prose* arm (enrichment text, gov opportunity descriptions), where it is in-domain.

### 2.3 Learned sparse

- **SPLADE** official weights and training code from Naver are **Creative Commons NonCommercial** — disqualifying for a commercial SaaS. Independent SPLADE++ reimplementations exist under permissive licenses. <https://github.com/naver/splade> · <https://qdrant.tech/articles/modern-sparse-neural-retrieval/>
- **BGE-M3** produces dense + sparse + multi-vector jointly and is MIT-licensed; the `bge-reranker-v2-m3` sibling is Apache 2.0. <https://huggingface.co/BAAI/bge-reranker-v2-m3>
- **Engine support:** OpenSearch ships its own Apache-2.0 `opensearch-neural-sparse-encoding` models and a neural-sparse query type; Elasticsearch ships ELSER (Elastic-licensed, not OSI open source); Qdrant and Vespa support sparse vectors natively. **Typesense and Meilisearch do not support learned sparse retrieval at all.** <https://docs.opensearch.org/latest/vector-search/ai-search/hybrid-search/index/> · <https://qdrant.tech/articles/modern-sparse-neural-retrieval/>

**What this implies for GS/AG.** Reranking is affordable on our box — a 22M cross-encoder over 50 candidates is a few hundred milliseconds worst-case and likely under 100 ms on short text — but it is the *second* thing to do, not the first, and it should be applied to the prose/matchmaker surface rather than the name surface. Learned sparse is a dead end for us on licensing (SPLADE) and engine support (Typesense/Meilisearch host none of it); if we ever wanted it, it would be an argument for OpenSearch, and that is a much larger ops bill than the brief's budget allows. The cheap win in this section is not a model at all: it is **rapidfuzz** (MIT, C++ with SIMD, `token_set_ratio`, `jaro_winkler`, batched `cdist`) as a top-50 name rescorer. <https://github.com/rapidfuzz/RapidFuzz>

---

## 3. Entity / organization-name search

### 3.1 The reference architecture: OpenSanctions yente + nomenklatura + followthemoney

This is the closest published analogue to our problem — millions of messy, abbreviated, aliased, renamed organization names, screened at interactive latency, all open source.

**Two-stage design, explicitly documented:** "First, a search index is used to locate possible candidate results" (tuned for **recall**), "in a second stage, these candidates are evaluated against the query" by a scoring algorithm. <https://www.opensanctions.org/docs/api/tuning/>

The scoring algorithms are named and versioned:
- `logic-v2` — current best; deterministic rules covering fuzzy matching, culturally-aware name comparison, identifier validation (IMO/ISIN/LEI/OGRN/INN); **penalises divergence** in supporting attributes (country, date of birth, gender, address). Calibrated for a **default threshold of 0.7**, raised to 0.8–0.85 when false positives are costly.
- `ofac` — name-only, reverse-engineered from OFAC's tool: "takes the best score across every combination of query and candidate name (**including aliases**), comparing both the whole name and its individual tokens using the Jaro-Winkler technique."
- `logic-v1`, and deprecated `name-based`, `name-qualified`, `regression-v1`, `regression-v2`.
Feature weights (`name_literal_match`, `name_soundex_match`, …) are tunable 0.0–1.0 per request. <https://www.opensanctions.org/docs/api/tuning/>

**Aliases and former names are first-class schema properties, not a text blob.** FollowTheMoney's `LegalEntity`/`Organization` schema types five distinct name properties, all of type `name` and all multi-valued:
`name`, `alias`, `abbreviation`, `previousName`, and `weakAlias` — where `weakAlias` is documented as "a relatively broad or generic alias that **should not be used for matching** in screening systems… may still be useful for identification." <https://followthemoney.tech/explorer/schemata/Organization/>

That `weakAlias` distinction is the single most transferable idea in this section: the model separates *names you may match on* from *names you may only display*.

Supporting libraries:
- **nomenklatura** — MIT, ~265 stars, ~2,065 commits; the scoring engine behind yente, plus a blocking index, a resolver graph of identity judgements/connected components, and an enrichment framework. <https://github.com/opensanctions/nomenklatura>
- **rigour** — MIT, ~67 stars, ~1,462 commits; data cleaning for "human and company names, language codes, territory identifiers, and corporate/tax identifiers", including **name normalization and fingerprinting**, transliteration, and address formatting from OpenCageData's database. It **consolidates and replaces the older `fingerprints`, `languagecodes` and `pantomime` libraries**. <https://github.com/opensanctions/rigour> · docs <https://rigour.followthemoney.tech/>
- **yente** — the deployable service; Python, backed by Elasticsearch/OpenSearch. <https://github.com/opensanctions/yente> · <https://www.opensanctions.org/docs/opensource/>
- Training data for matchers is published: <https://www.opensanctions.org/docs/opensource/pairs/>

### 3.2 The record-linkage libraries

- **Splink** (Ministry of Justice, UK) — probabilistic linkage on the Fellegi-Sunter model with EM parameter estimation, running as SQL against **DuckDB, Spark, Athena, SQLite and PostgreSQL**; "a million records on a laptop in approximately one minute", 100M+ on Spark; "full support for term frequency adjustments and user-defined fuzzy matching logic"; documentation stresses that it "performs best when input data is pre-standardized". Free and open source. <https://moj-analytical-services.github.io/splink/index.html> · <https://github.com/moj-analytical-services/splink> · Fellegi-Sunter theory page <https://moj-analytical-services.github.io/splink/topic_guides/theory/fellegi_sunter.html>
- **dedupe** — MIT, active-learning record linkage/deduplication in Python. <https://github.com/dedupeio/dedupe> · license <https://github.com/dedupeio/dedupe/blob/main/LICENSE>
- **rapidfuzz** — MIT, C++ core with SIMD, Python/Rust bindings; `ratio`, `partial_ratio`, `token_sort_ratio`, `token_set_ratio`, `WRatio`, `jaro_winkler`, `hamming`; explicitly notes that batching through processors like `cdist` is far faster than per-pair calls. Chosen over fuzzywuzzy for both speed and the MIT (vs GPL) license. <https://github.com/rapidfuzz/RapidFuzz> · <https://rapidfuzz.com/>
- **cleanco** — Python, strips legal-form terms ("Ltd.", "Corp.") to a basename, and infers organization type and likely country from the suffix ("Oy" ⇒ Finland). <https://github.com/psolin/cleanco>

**Important scoping note.** Splink and dedupe solve *record linkage over two known datasets*, not *interactive query-to-corpus search*. They are the right tools for GS's near-duplicate-foundation problem and for reconciling `filer_name` against `name`; they are the wrong tools for AG's search box. **[INFERENCE]** The transferable part is the *feature set* — Jaro-Winkler on tokens, term-frequency adjustment (a rare token like "Lpr" should count for far more than "Foundation"), and explicit comparison levels — which we can implement directly in the name-tier scorer without adopting either library.

### 3.3 IRS / nonprofit-specific name handling

This is the thinnest part of the open-source landscape — there is **no** canonical published IRS abbreviation dictionary I could find. What exists:

- The **Nonprofit Open Data Collective** publishes `irsx` ("turns the IRS' versioned XML 990 nonprofit annual tax returns into standardized python objects, json, or human readable text") and the Master Concordance File. <https://github.com/Nonprofit-Open-Data-Collective> · <https://lecy.github.io/Open-Data-for-Nonprofit-Research/>
- Their **Name and Title Ontology** for the compensation database is the closest published precedent for what we need: "routines have been applied to clean up raw text, fix spelling errors, **convert abbreviations to a standardized set**"; punctuation removed, capitalization normalized, abbreviations standardized — e.g. CEO / Chief Executive Officer / Executive Director / ED all collapse to one code. <https://nonprofit-open-data-collective.github.io/irs-990-compensation-data/taxonomies/>
- **NCCS (Urban Institute)** publishes a Unified BMF with a documented cleaning pipeline; field definitions follow IRM 25.7.1. <https://urbaninstitute.github.io/nccs/datasets/bmf/> · processing guide <https://urbaninstitute.github.io/nccs-data-bmf/index.html> · IRS EO BMF field doc <https://www.irs.gov/pub/irs-soi/eo-info.pdf>
- ProPublica Nonprofit Explorer has a public API with third-party wrappers. <https://github.com/Punderthings/propublica990> · <https://github.com/billfitzgerald/get_the_990>

**[INFERENCE, and it is the actionable finding of this section]** No one has published the "Tr / Fdn / Char / Assn / Memorial / Chrtbl / Fnd / Endt" dictionary we need. It is maybe 150–300 entries, derivable *from our own corpus* by frequency-ranking the tokens in `foundations.name` that are absent from an English dictionary, and it is a one-afternoon asset that would be genuinely novel open-source output. The precedent for shape is the NODC title ontology; the precedent for mechanism is `rigour`'s name normalization.

### 3.4 Synonyms — dictionary vs index-time expansion

The mechanics matter here because the naive choice is wrong.

- **Elasticsearch/Lucene**: multi-word synonyms **cannot** be applied at index time correctly. "A Lucene index cannot store a token graph" — Lucene ignores `PositionLengthAttribute` on write, flattening the graph, which makes phrase queries both miss documents they should match and match documents they should not. The `synonym_graph` filter handles multi-word synonyms correctly but **is a search-analyzer-only filter**. Query-time synonyms cost more CPU/IO but keep the index smaller and hot-reloadable. <https://www.elastic.co/blog/multitoken-synonyms-and-graph-queries-in-elasticsearch> · <https://github.com/elastic/elasticsearch/issues/10394> · <https://bigdataboutique.com/blog/search-synonyms-elasticsearch-opensearch>
- **Typesense v30**: synonyms became first-class **synonym sets** (`/synonym_sets`, migrated from `/collections/{c}/synonyms`), reusable across collections, supporting multi-way and one-way sets, with per-locale application. Crucially: "**Synonyms are only applied to the tokens in the `q` search parameter, and not to any tokens in `filter_by`.**" <https://typesense.org/docs/30.2/api/synonyms.html>
- **Meilisearch** has hard limits that would bite us: synonyms are **one-way only** (declare both directions manually); synonyms are fetched only for search terms of **1–3 words** (4+ words get no synonym match); **max 50 synonyms per term**, and if any synonym is multi-word the total word count across a term's synonyms cannot exceed 100 — **silently ignored beyond the limit**; and a typo in the query does not typo-tolerantly reach a synonym. <https://www.meilisearch.com/docs/learn/relevancy/synonyms> · <https://github.com/meilisearch/documentation/issues/2445>

**Dictionary vs `display_name` expansion — the verdict.** A synonym dictionary is a *query-side* tool: it rewrites what the user typed. Our problem is the opposite direction — the *corpus* is abbreviated, not the query. A user types "Smith Foundation"; the document says "Smith Fdn". A query-time synonym set mapping `fdn → foundation` fixes this only if the index also contains "foundation", which it does not. **[INFERENCE, high confidence]** Therefore: expand at **index time into a separate field** (`display_name` already exists and is already in `query_by`), and use a synonym set only for genuine query-side equivalences (a donor's colloquial name, "NSF" ⇄ "National Science Foundation"). Both, not either.

### 3.5 Aliases / former names — the "renamed foundations unsearchable" problem

The documented answer is uniform across engines and matches FollowTheMoney's schema: **index alternate names as a multi-valued string field, and query it as a lower-weighted arm of the same query.**

- FTM types `alias`, `previousName`, `abbreviation`, `weakAlias` as separate multi-valued `name` properties, and the `ofac` matcher takes "the best score across every combination of query and candidate name (including aliases)". <https://followthemoney.tech/explorer/schemata/Organization/> · <https://www.opensanctions.org/docs/api/tuning/>
- Typesense supports `string[]` fields directly in `query_by`, and `query_by_weights` (0–127) lets the alias field carry less weight than `name`; `text_match_type: max_score` (the default) means *the best single field wins*, which is precisely the "best score across every combination of names" semantics OFAC uses. <https://typesense.org/docs/30.2/api/search.html>
- Postgres side: a `tsvector` weight class already exists for exactly this — our `search_tsv` is weighted A/B/C/D, so aliases go in a class below `name`, and `pg_trgm`'s `word_similarity` / `strict_word_similarity` (thresholds 0.6 and 0.5 by default, GIN or GiST indexable, no left-anchoring required) runs over an unnested alias array. <https://www.postgresql.org/docs/current/pgtrgm.html>

**What this implies for GS/AG.** The renamed-foundations problem is a *schema* gap, not a ranking gap, and it is the highest-leverage fix in this whole document. We have `name` and `display_name` and `filer_name` floating around as competing single-valued columns; FollowTheMoney's answer — one multi-valued `aliases` array carrying every historical `filer_name`, every IRS-abbreviated variant, and every expanded form, with a `weakAlias`-style flag for generic ones we may display but not match — collapses three problems (renames, abbreviations, near-duplicates) into one field that both engines already know how to index. The OpenSanctions two-stage shape (recall-oriented index retrieval, then a rules scorer over ≤ 50 candidates with a calibrated 0.7 threshold) is also directly copyable and is *cheaper* than a cross-encoder. And their thresholding discipline is worth stealing wholesale: publish a score cutoff so that "nothing matched" is an honest answer rather than a page of noise.

---

## 4. Evaluation and observability

### 4.1 The libraries

- **ranx** (AmenRa) — "blazing-fast" Numba-accelerated ranking evaluation, comparison **and fusion**; MAP/MRR/nDCG and friends; statistical significance tests; LaTeX table export; **several fusion algorithms and normalization strategies with automatic fusion optimization**; metrics "tested against TREC Eval for correctness". Published at ECIR 2022, CIKM 2022, SIGIR 2023. <https://github.com/AmenRa/ranx> · <https://amenra.github.io/ranx/> · <https://dl.acm.org/doi/10.1007/978-3-030-99739-7_30>
- **ir_measures** — one interface over 30+ measures across trec_eval, gdeval, MS MARCO's own scripts, etc. <https://arxiv.org/pdf/2111.13466>
- **pytrec_eval** — the Python binding to the official TREC tool; what BEIR itself uses. <https://github.com/beir-cellar/beir/wiki/Metrics-available>
- **BEIR** — `pip install beir`, nDCG@10 as the headline metric, wrappers for Sentence-Transformers, Elasticsearch, ColBERT and others. <https://github.com/beir-cellar/beir> · <https://arxiv.org/pdf/2104.08663>

**ranx is the right pick for us**: it is the only one that both scores *and* optimises fusion weights, which is exactly the convex-combination-tuning step §1.2 says we need.

### 4.2 The workbenches

- **Elasticsearch `_rank_eval` API** — `requests` (templated queries) + `ratings` (docid → grade) + a `metric` ∈ {precision, recall, mean_reciprocal_rank, dcg (with `normalize: true` for nDCG), expected_reciprocal_rank}. Runs inside the cluster, no external harness. <https://www.elastic.co/docs/reference/elasticsearch/rest-apis/search-rank-eval>
- **OpenSearch Search Relevance Workbench** (3.1+) — three experiment types: search-result comparison, search-quality evaluation, and **hybrid search optimization** (a parameter sweep over the normalization/combination grid, currently limited to **exactly two query clauses**). Built on **User Behavior Insights (UBI)**, a schema and plugin for capturing queries, presented results, and user actions, and deriving implicit judgments from them. <https://docs.opensearch.org/latest/search-plugins/search-relevance/using-search-relevance-workbench/> · <https://docs.opensearch.org/latest/search-plugins/search-relevance/optimize-hybrid-search/> · <https://docs.opensearch.org/latest/search-plugins/ubi/index/> · <https://github.com/opensearch-project/user-behavior-insights> · <https://www.ubisearch.dev/>
- **Quepid** (OpenSource Connections) — open-source relevance workbench: side-by-side result comparison, manual rating, nDCG/ERR scorers; since 8.1 the nDCG implementation is aligned with `trec_eval`. <https://opensourceconnections.com/blog/2019/07/25/2019-07-22-quepid-is-now-open-source/> · <https://opensourceconnections.com/blog/2025/03/09/what-do-ndcg-and-err-model-in-quepid/>
- **RRE (Rated Ranking Evaluator)** — Maven-based, runs relevance metrics **as part of the build**, against a Solr or Elasticsearch config; Quepid ratings feed into it. <https://github.com/o19s/awesome-search-relevance>
- **Typesense analytics** — `popular_queries` and **`nohits_queries`** rule types aggregating into a destination collection, plus click/conversion `counter` events. Requires the server flags `--enable-search-analytics` and `--analytics-dir`; aggregation cadence is `--analytics-flush-interval`. Known issue: no-hit queries not recording on some self-hosted setups (#2419). <https://typesense.org/docs/30.2/api/analytics-query-suggestions.html> · <https://typesense.org/docs/guide/search-analytics.html> · <https://github.com/typesense/typesense/issues/2419>

### 4.3 Building the golden set

Elastic's own guidance is refreshingly small-scale, which suits us:
- Start with "the **5–10 most critical queries** for your business case", plus the queries returning no results.
- Prefer **binary judgments** — "graded scales introduce consistency problems across reviewers and amplify noise".
- Use **explicit** (SME) judgments unless you have enough traffic for implicit; if using clicks, debias with result shuffling or a click model (DBN, UBM).
- Start with **precision**, graduate to recall/DCG/MRR.
- "Make it part of the flow. Integrate judgment lists into your development pipelines" so every synonym or analyzer change is validated against a baseline.
<https://www.elastic.co/search-labs/blog/judgment-lists-search-query-relevance-elasticsearch>

Sampling guidance from Qdrant and practitioners: prioritise zero-result and <3-result queries, **segment by frequency** (a zero-result query searched hundreds of times is a bigger opportunity than one searched twice), and hold a separate "golden tail" sample from the low-traffic tertile so head-query tuning does not silently wreck the tail. <https://qdrant.tech/documentation/improve-search/retrieval-relevance/> · <https://wizzy.ai/blog/zero-result-searches-solution/>

### 4.4 Click models and interleaving on a low-traffic site

This is the section that matters most for AG, which has beta-cohort traffic, not e-commerce traffic.

- Interleaving is **one to two orders of magnitude more sensitive than A/B testing**; Amazon Search reports debiased balanced interleaving as "on average **60 times more powerful** than A/B tests". <https://assets.amazon.science/a9/c8/c9016a1c47caac6a634768e7491d/debiased-balanced-interleaving-at-amazon-search.pdf> · <https://www.cs.cornell.edu/people/tj/publications/chapelle_etal_12a.pdf>
- **Team Draft Interleaving** (the simplest to implement — alternate "picks" from ranking A and ranking B into one list, record which team's document was clicked) is the *weakest* interleaving method in sensitivity, but still far ahead of A/B, and every arm is seen by every user, which is exactly what you want with few users. <https://opensourceconnections.com/blog/2025/08/06/a-b-testing-with-team-draft-interleaving/> · <https://eprints.gla.ac.uk/108076/1/108076.pdf>
- Airbnb's writeup on combining interleaving with counterfactual evaluation is a good end-to-end template. <https://arxiv.org/html/2508.00751v1>

**What this implies for GS/AG.** We can have a defensible offline gate this month for roughly a day of work, and it does not require adopting any workbench. The shape: (1) turn on Typesense's `nohits_queries` and `popular_queries` rules — the config already exists and costs nothing; (2) sample ~100 queries (head from the popular set, tail from zero-result, plus a hand-written set of the pathological name cases: abbreviation, rename, near-duplicate, EIN, "The X Foundation"); (3) binary-judge them once by hand against the current top-10; (4) score with **ranx** in a pytest that fails the build if nDCG@10 regresses more than a stated epsilon. That is `ir_measures`/`pytrec_eval`-equivalent rigour with none of the Java. Quepid and RRE are better tools than a pytest, but both assume Solr/Elasticsearch and neither speaks Typesense, so adopting them would cost us more than it buys. Interleaving is the right *second* step once the beta cohort is live: Team Draft is ~50 lines, and at 60x the power of an A/B test it is the only online method that can conclude anything at our traffic. **[INFERENCE]** with AG's current traffic, an A/B test on ranking would never reach significance — interleaving is not an optimisation here, it is the difference between measuring and guessing.

---

## 5. Query understanding — cheap tricks

**EIN detection.** A 9-digit token (optionally `NN-NNNNNNN`) is unambiguous in this corpus: short-circuit to an exact lookup and skip search entirely. We already do this; the documented pattern that makes it robust is Typesense's `num_typos: 0` per-field override (`num_typos` defaults to **2**, which on a numeric field is actively harmful) — already set on our `ein` field. <https://typesense.org/docs/30.2/api/search.html>

**State / NTEE extraction.** Typesense's curation rules do this natively: a rule whose `rule.query` matches can convert the matched tokens into a `filter_by` clause, with `remove_matched_tokens` (default `true`) stripping them from the residual query. So "california family foundations" becomes `q=family foundations, filter_by=state:CA` without any Python. <https://typesense.org/docs/30.2/api/curation.html>. Caution from §3.4: **synonyms are not applied to `filter_by` tokens**, so the state dictionary must be exhaustive on its own (CA / Calif / California). <https://typesense.org/docs/30.2/api/synonyms.html>

**Stopwords in names ("The X Foundation").** This is where generic stopword removal goes wrong: "Foundation" is a stopword *statistically* (it is in a large fraction of documents) but load-bearing *semantically* (it distinguishes "Smith Foundation" from "Smith Family Trust"). BM25 handles this correctly via IDF; **Postgres `ts_rank` does not** — ParadeDB's writeup states it plainly: "ranking functions like `ts_rank` only consider individual documents in isolation: they don't understand global corpus statistics", so it cannot distinguish a rare discriminating term from a common one. <https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual>. **[INFERENCE, important]** this is a concrete, previously-unnamed reason the Postgres fallback path ranks names worse than Typesense does, independent of fusion — and a reason not to "simplify" by retiring Typesense in favour of pure Postgres FTS. Splink's "term frequency adjustments" are the record-linkage world's name for the same correction. <https://moj-analytical-services.github.io/splink/index.html>

**Prefix / autocomplete.** Elasticsearch's `search_as_you_type` field generates `._2gram`, `._3gram` and `._index_prefix` subfields (`max_shingle_size` 2–4, default 3) and is queried with `multi_match` of type `bool_prefix` — terms may match in any order but in-order matches score higher; larger shingle sizes cost index size. <https://www.elastic.co/docs/reference/elasticsearch/mapping-reference/search-as-you-type>. Typesense does prefix matching by default on the last token and supports `infix` search (`off` / `always` / `fallback`, with `max_extra_prefix` / `max_extra_suffix`) when a field opts in at schema level. <https://typesense.org/docs/30.2/api/search.html>

**Unaccent and case folding.** Postgres `unaccent` as a dictionary in the FTS configuration (which we already do), plus `pg_trgm` with GIN/GiST for the fuzzy arm: `similarity` (threshold default 0.3), `word_similarity` / `<%` (0.6), `strict_word_similarity` / `<<%` (0.5), the `<->` / `<<->` distance operators, and the note that **GiST is more efficient for `ORDER BY distance LIMIT n` while GIN is better for threshold queries**, and that trigram indexes are *not* as efficient as B-tree for equality. <https://www.postgresql.org/docs/current/pgtrgm.html> · <https://www.postgresql.org/docs/current/unaccent.html>

**What this implies for GS/AG.** Most of the query-understanding wins here are configuration we already own and are not using: curation rules for state/NTEE extraction (moves logic out of Python and into the engine, so both paths agree), `infix` on `name` for the mid-string abbreviation case, and `prioritize_token_position` for "The X Foundation" so the leading "The" does not cost the document its position advantage. The one thing that is *not* configuration is the `ts_rank` IDF gap — it is a real ranking defect in the fallback path, and the honest options are to accept the fallback is worse (and say so in the UI when it is engaged), or to move the keyword arm to a BM25 implementation. Note ParadeDB is the obvious BM25-in-Postgres candidate but its docs URLs are unstable right now (`docs.paradedb.com` 308s to a 404), which is a small maintenance smell worth checking before adoption.

---

## The 5 highest-leverage changes for name-search quality

**1. One multi-valued `aliases` field, populated from every name variant we hold, indexed in both engines.**
Every historical `filer_name`, every IRS-abbreviated form, every expanded form, and a `weakAlias`-style flag separating match-worthy from display-only. This is FollowTheMoney's exact schema (<https://followthemoney.tech/explorer/schemata/Organization/>) and it collapses renames, abbreviations and near-duplicates into one field both Typesense (`string[]` + `query_by_weights`, `text_match_type: max_score` = "best single field wins") and Postgres (a lower `tsvector` weight class + `pg_trgm` over the unnested array) already index natively. It directly kills the "renamed foundations unsearchable" bug. Highest value, lowest risk, no ranking maths involved.

**2. An IRS abbreviation dictionary, applied at index time to build `display_name`, not as a query-time synonym set.**
The corpus is abbreviated, not the query, so query-side synonyms cannot fix it (§3.4) — and Meilisearch's limits (one-way, ≤3-word terms, ≤50 per term, silently truncated) show how badly synonym dictionaries scale for this. Derive the ~150–300 entries by frequency-ranking non-dictionary tokens in `foundations.name`; the precedent for shape is the Nonprofit Open Data Collective's title ontology (<https://nonprofit-open-data-collective.github.io/irs-990-compensation-data/taxonomies/>) and `rigour`'s name normalization (<https://github.com/opensanctions/rigour>). Reserve an actual synonym set for genuine query-side equivalences only.

**3. Replace weighted RRF with a min-max-normalized convex combination, and move the name tier into the engine.**
Bruch et al. (<https://arxiv.org/abs/2210.11934>) show CC beats RRF in-domain and out-of-domain with one weight tuned on a small sample; Vespa's own numbers show linear-normalized fusion at nDCG@10 0.3423 vs RRF 0.3233 (<https://docs.vespa.ai/en/learn/tutorials/hybrid-search.html>); Weaviate measured +6% recall (<https://weaviate.io/blog/hybrid-search-fusion-algorithms>). This is one CTE change in `ag_research`. In the same change, express the name tier as Typesense `sort_by: _eval(<exact/prefix predicate>):desc,_text_match:desc` so the Typesense and Postgres paths tier identically instead of only the Python path tiering. Do this **after** step 5 exists, so the change is measured.

**4. A rapidfuzz rescore over the top-50 name candidates, replacing any thought of a cross-encoder on the name arm.**
MIT, C++/SIMD, batched via `cdist`, microsecond-scale (<https://github.com/rapidfuzz/RapidFuzz>). Copy OpenSanctions' `ofac` semantics: best score across every (query name × candidate name-or-alias) pair, comparing both the whole string and its tokens with Jaro-Winkler, with term-frequency weighting so a rare token outvotes "Foundation" (<https://www.opensanctions.org/docs/api/tuning/>). Publish a calibrated cutoff the way they publish 0.7, so "no confident match" is a supported answer. A 22M cross-encoder at 143.9 pairs/s on CPU (<https://huggingface.co/blog/ettin-reranker>) is affordable but out-of-domain for abbreviated names — save it for the prose/matchmaker surface.

**5. Move state/NTEE extraction and stopword handling into engine configuration.**
Typesense curation rules with dynamic filtering + `remove_matched_tokens` for "california family foundations" (<https://typesense.org/docs/30.2/api/curation.html>); `prioritize_token_position` and `infix` on `name`; `num_typos: 0` kept on `ein`; `prioritize_exact_match` confirmed still `true` (<https://typesense.org/docs/30.2/api/search.html>). Cheap, and it removes a class of two-path drift by making the engine, not AG's Python, the place query understanding lives. Note separately that Postgres `ts_rank` has no corpus-level IDF (<https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual>), so the fallback path will remain measurably worse on names — that is a fact to document, not to paper over.

---

## The 3 cheapest evaluation steps

**1. Turn on Typesense analytics — today, one flag and two rules.**
`--enable-search-analytics` + `--analytics-dir`, then a `nohits_queries` rule and a `popular_queries` rule writing into destination collections (<https://typesense.org/docs/30.2/api/analytics-query-suggestions.html>). Zero-result queries are simultaneously the highest-signal bug report and the highest-value golden-set seed (<https://wizzy.ai/blog/zero-result-searches-solution/>). Watch for issue #2419 — verify no-hit recording actually fires on our self-hosted container rather than assuming it (<https://github.com/typesense/typesense/issues/2419>); a silent analytics collection is a false green.

**2. 100 binary-judged queries + `ranx` in a pytest that gates the build.**
Elastic's guidance is to start at 5–10 critical queries and prefer binary over graded judgments because grades amplify reviewer noise (<https://www.elastic.co/search-labs/blog/judgment-lists-search-query-relevance-elasticsearch>). Sample head queries from `popular_queries`, tail from `nohits_queries`, and hand-write the pathological name cases (abbreviation, rename, near-duplicate, EIN, leading "The", state-qualified). Score with `ranx` — Numba-fast, verified against TREC Eval, and it also *optimises fusion weights*, which is precisely the tuning step change #3 needs (<https://github.com/AmenRa/ranx>). Fail the build on an nDCG@10 regression beyond a stated epsilon. Per estate doctrine this needs a **negative fixture**: a deliberately broken ranking that makes the gate go red for the stated reason, proving the check can fail.

**3. Team Draft Interleaving behind a flag, once the beta cohort is live.**
~50 lines: alternate picks from ranking A and ranking B into one served list, log which team owned each clicked result, sign-test the difference. Interleaving is 1–2 orders of magnitude more sensitive than A/B (<https://www.cs.cornell.edu/people/tj/publications/chapelle_etal_12a.pdf>), Amazon measures debiased interleaving at ~60x the power of an A/B test (<https://assets.amazon.science/a9/c8/c9016a1c47caac6a634768e7491d/debiased-balanced-interleaving-at-amazon-search.pdf>), and Team Draft — the weakest but simplest variant — still shows every arm to every user, which is the only property that makes online measurement possible at AG's traffic (<https://opensourceconnections.com/blog/2025/08/06/a-b-testing-with-team-draft-interleaving/>). **[INFERENCE]** at current AG traffic an A/B test on ranking would never reach significance; this is the difference between measuring and guessing.

---

## Things I would flag as a bad fit

- **OpenSearch / Elasticsearch as the single engine.** They have the best fusion tooling (normalization processor with bounds clipping, Search Relevance Workbench, UBI, `_rank_eval`) and the only Apache-2.0 learned-sparse story. They also carry a JVM ops bill that the brief's single-node Railway budget does not support. The tooling is worth *copying*, not adopting.
- **Meilisearch** for our synonym needs — the one-way-only rule, 3-word term ceiling, 50-synonym cap and **silent** truncation past the limits make it a poor fit for an abbreviation-heavy corpus (<https://www.meilisearch.com/docs/learn/relevancy/synonyms>).
- **SPLADE** — official Naver weights are Creative-Commons NonCommercial; a commercial SaaS cannot ship them (<https://github.com/naver/splade>).
- **Pushing vectors into Typesense (Phase 2)** — its rank fusion has an open, unassigned correctness issue and does not expose per-arm ranks (<https://github.com/typesense/typesense/issues/2162>, <https://github.com/typesense/typesense/issues/1966>). Keeping fusion in our own SQL/Python is currently the more controllable position.
- **Splink / dedupe for the search box** — both are batch record-linkage tools over known datasets, not query-to-corpus retrieval. Right tools for GS's near-duplicate reconciliation; wrong tools for AG's search.
- **ParadeDB** — technically the best BM25-in-Postgres answer and the direct fix for the `ts_rank` IDF gap, but its documentation host is currently unstable (`docs.paradedb.com` 308-redirects to a 404 on `www.paradedb.com/docs/...`), which is worth probing before betting a search path on it.

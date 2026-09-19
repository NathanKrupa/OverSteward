# Lane 5 — Open-source reference implementations in our domain
### Nonprofit / foundation / grant / government-opportunity search, and adjacent entity-search systems

Research date: 2026-09-07. Every factual claim carries a URL. Statements marked
**[inference]** are my reading, not documented fact. Statements marked
**[measured]** are live probes I ran against public APIs during this research.

---

## 0. Executive orientation

The single most useful finding is that **nobody in our exact domain has solved the
problem GS/AG has**, and the two closest analogues each solved a *different* half:

- **Simpler.Grants.gov** (HHS, open source) solved *government opportunity search*
  with OpenSearch, ~10k-scale corpus, no vectors at all, and an **hourly full
  refresh** — and they explicitly *deleted* their incremental-indexing code as
  unnecessary. Their corpus is small enough that full rebuild is cheap.
- **OpenSanctions yente** solved *entity name search at scale* — aliases, previous
  names, abbreviations, phonetics, org-class demotion, trigram fuzzy — with an
  index design that is almost line-for-line what GS needs, and which also uses a
  timestamped-index + alias-swap full rebuild.
- **Grantmakers.io** — the closest product analogue to AG's public foundation
  directory (~100k 990-PF foundations, static site, SEO play) — punted entirely
  and rides the **Algolia free tier**. It is the honest proof that a 300k-entity
  public foundation directory is *not* a static/edge-search problem.

And the abbreviation problem is genuinely unsolved in the public market: I probed
ProPublica's Nonprofit Explorer live and it returns **140 results for "Smith Family
Foundation" and 1 result for "Smith Family Fdn"** (§2.1). That is a differentiator
sitting on the table for AG.

---

## 1. Systems table

| System | Engine | Corpus | Name handling | Freshness / index sync | License · URL |
|---|---|---|---|---|---|
| **Simpler.Grants.gov** (HHS) | **OpenSearch** (AWS managed), BM25 only, no vectors | Federal opportunities; grants.gov currently shows 1,024 posted + 8,701 closed **[measured]** | `simple_query_string` over boosted fields; `agency_code^16`, `opportunity_number^12`, `opportunity_title^2`; `.keyword` twin fields so hyphenated IDs aren't tokenized; snowball English stemmer; **no fuzzy, no synonyms, no aliases** | **Hourly full refresh** into `opportunity-index-<ts>`, atomic alias swap, delete old. Trigger-based change queue exists in the schema but the incremental *loader* was deleted (PR #7748) | CC0-ish/"NOASSERTION", 200★ · [repo](https://github.com/HHS/simpler-grants-gov) · [ADR](https://github.com/HHS/simpler-grants-gov/blob/main/documentation/wiki/product/decisions/adr/2024-10-02-search-engine.md) |
| **grants.gov search2** (legacy, closed source) | undisclosed **[inference: Solr/Lucene — it returns a `suggestion` field and faceted bucket counts in-band]** | 1,585 forecasted+posted **[measured]** | keyword free-text; no documented alias handling | daily-ish (agency-driven) | closed API, free · [api-guide](https://grants.gov/api/api-guide) |
| **USAspending.gov** | **Elasticsearch/OpenSearch**, Django+Postgres source of truth | ~100M docs (their own dup-check help text cites "8hrs for 100M docs") | `recipient_name` as `text` + `.keyword` + a `contains` sub-field using an **ngram tokenizer**; same triple treatment for `uei` and `duns`; `recipient_hash` as the stable key; separate `edge_ngram` (2–10) analyzer for typeahead | **Watermark incremental** (`--start-datetime` from `get_last_load_date`) + **separate delete pass** (`--process-deletes`, S3 delete manifests) + periodic **full rebuild** (`--create-new-index` → alias swap). Parallel partitioned load (10 procs × 10k partitions), `refresh_interval` off during load | **CC0-1.0**, 463★ · [repo](https://github.com/fedspendingtransparency/usaspending-api) |
| **OpenSanctions yente** | Elasticsearch **or** OpenSearch (pluggable provider) | OpenSanctions full corpus (millions of FtM entities) | The reference design — see §3.1. `names` multi-field + `names.ngrams` trigram + `name_parts` + `name_symbols` + `name_phonetic`; custom BM25 `weak_length_norm` (b=0.25); symbol-category boosts demoting ORG_CLASS to 0.7 and generic SYMBOL to 0.3 | Hourly check against a published version manifest → new timestamped index → atomic alias swap → delete old snapshots. `YENTE_CRONTAB`, `YENTE_AUTO_REINDEX` | **MIT**, 176★, pushed 2026-09-07 · [repo](https://github.com/opensanctions/yente) |
| **rigour** (OpenSanctions) | library, not engine | `org_types.yml` = 3,559 lines of legal-form aliases | alias → `display` / `compare` / `generic` three-tier normalization | n/a | **MIT**, 67★ · [repo](https://github.com/opensanctions/rigour) · [org_types.yml](https://github.com/opensanctions/rigour/blob/main/resources/names/org_types.yml) |
| **followthemoney** (FtM) | schema, not engine | n/a | `name` / `alias` / `previousName` / `weakAlias` (matchable:false) / `abbreviation` (matchable:false) — the vocabulary GS is missing | n/a | MIT · [LegalEntity.yaml](https://github.com/opensanctions/followthemoney/blob/main/followthemoney/schema/LegalEntity.yaml) |
| **ProPublica Nonprofit Explorer** | undisclosed **[inference: Elasticsearch — `q` supports quoted phrases, `+` required, `-` excluded, i.e. `simple_query_string` syntax, and it is fuzzy]** | full IRS BMF (~1.8M orgs) | `q` searches "organization name, organization alternate name, city" **in that order**; EIN in `q` resolves exactly **[measured]**; fuzzy is on **[measured]**; **no abbreviation expansion [measured]** | "each spring, when the Annual Extract … is released"; BMF more often | closed source, free API · [API docs](https://projects.propublica.org/nonprofits/api) · [announcement](https://www.propublica.org/nerds/announcing-the-nonprofit-explorer-api) |
| **Grantmakers.io / NEXT** | **Algolia InstantSearch** (hosted, free tier) | "~100k foundation profiles" + "millions of grant descriptions" | Algolia default typo tolerance; **no custom alias/abbrev work documented** | IRS publishes "roughly monthly"; automated scripts fetch/parse/publish "within a week" | repo has **no license file**, 6★ · [repo](https://github.com/grantmakers/grantmakers-next) · [dataset page](https://www.grantmakers.io/about/the-dataset/) · [Algolia case study](https://stories.algolia.com/why-hosted-search-made-sense-for-grantmakers-io-8974f5ed6bd6) |
| **Candid Essentials API** | undisclosed | Candid's US nonprofit universe | name or EIN search; filters incl. location+radius, revenue/asset/expense ranges, Pub78 status, audit history, form types | "surface organizations with recently updated data" | commercial · [docs](https://developer.candid.org/reference/get-started-with-essentials) |
| **Charity Navigator `irs990` / `990_long`, IRSx, Open990** | ETL only — no search layer | 2.5M e-filed returns | n/a (parsing/concordance tooling) | IRS publication cadence | various OSS · [CharityNavigator/irs990](https://github.com/CharityNavigator/irs990) · [990-xml-reader](https://github.com/Nonprofit-Open-Data-Collective/990-xml-reader) · [open990](https://github.com/opendatalove/open990) |
| **OpenCorporates** | undisclosed | ~200M companies | Documented normalization: strips punctuation + stopwords, **bidirectional suffix synonyms (Corp↔Corporation, Ltd↔Limited, Inc.↔Incorporated)**, word-order-independent, matches **previous names**, score *demoted* for inactive/foreign-branch | continuous per-jurisdiction | closed source · [company search KB](https://knowledge.opencorporates.com/knowledge-base/api-walk-through-company-search/) |
| **Wikidata / WikibaseCirrusSearch** | Elasticsearch | ~100M items | labels + **aliases** + descriptions indexed as **separate fields per language**, with `near_match` / `near_match_folded` analyzers alongside the tokenized field | continuous (job queue) | GPL · [Extension:CirrusSearch](https://www.mediawiki.org/wiki/Extension:CirrusSearch) · [T117520](https://phabricator.wikimedia.org/T117520) |
| **GLEIF LEI search** | undisclosed | ~2.7M LEIs | fuzzy at **Levenshtein distance 1** across all reference fields; "other names"/transliterations folded into one array; legal name only — trade/brand names do not match | daily | free API · [GLEIF API](https://www.gleif.org/en/lei-data/gleif-api) |
| **Pagefind** | static, WASM, chunked index | designed for "tens of thousands"; "scales to 100,000 pages" | prefix + stemming; no facet-heavy entity semantics | rebuilt at site build | **MIT**, 5,446★, active · [pagefind.app](https://pagefind.app/) |
| **Orama** | in-memory JS (BM25 + vectors + facets) | in-browser; RAM-bound | typo tolerance, facets, vectors | rebuilt/loaded per session | "NOASSERTION" license, 10,547★ · [repo](https://github.com/oramasearch/orama) |
| **Stork** | static, Rust-built index | small sites | — | build-time | Apache-2.0, 2,759★, **last push 2023-07-01 — effectively unmaintained** · [repo](https://github.com/jameslittle230/stork) |
| **Lunr / Elasticlunr / Fuse.js / FlexSearch** | in-browser | Fuse: "<10K items" comfort zone; FlexSearch "excellent for 100K+" | Fuse = fuzzy scoring only, no inverted index | build-time | MIT · [comparison](https://www.pkgpulse.com/guides/fusejs-vs-flexsearch-vs-orama-client-side-search-2026) |

---

## 2. Per-system findings

### 2.1 ProPublica Nonprofit Explorer — the market's revealed baseline

**Documented.** The v2 search endpoint is
`GET https://projects.propublica.org/nonprofits/api/v2/search.json` with `q`,
`page`, `state[id]`, `ntee[id]` (major group 1–10), `c_code[id]`. `q` "will search
(in order) organization name, organization alternate name, city" and supports
quoted phrases, `+` required and `-` excluded terms. EIN lookup is a *separate*
endpoint, `/organizations/:ein.json`. Page size dropped from 100 to 25 in
September 2023. Freshness: "We expect to update the Nonprofit Explorer database
each spring, when the Annual Extract of Tax-Exempt Organization Financial Data is
released by the IRS."
([API docs](https://projects.propublica.org/nonprofits/api),
[announcement](https://www.propublica.org/nerds/announcing-the-nonprofit-explorer-api))

**The backend is not publicly documented.** No ProPublica engineering post names
the engine. **[inference]** The `q` grammar (`"phrase"`, `+must`, `-exclude`) is
exactly Elasticsearch's `simple_query_string`, and the behaviour below is
consistent with ES with fuzziness enabled.

**[measured] Live probes, 2026-09-07:**

| Query | `total_results` | Reading |
|---|---|---|
| `Smith Family Foundation` | **140** | baseline |
| `Smith Family Fdn` | **1** (only `Charles E Smith Family Fdn`) | **no abbreviation expansion at all** — the abbreviated form matches only literally |
| `131624114` (an EIN) | **1** — `Near East Foundation` | EIN *is* reachable through `q` despite the docs listing only name/alt-name/city |
| `Rockefellr Foundation` | **8**, incl. `Rockefeller Foundation` | fuzzy matching **is** on, and the query is AND-ish (bare "Foundation" would return tens of thousands) |

**Transfers to GS/AG:**
1. **The abbreviation gap is real and unclaimed.** The single most-used free
   nonprofit search in the US cannot get from "Fdn" to "Foundation" or back. GS's
   corpus is *stored* in the abbreviated form, which means a bidirectional
   synonym dictionary is both the fix for our own recall *and* a visible product
   advantage over the reference implementation.
2. **Alternate name as a first-class ranked field, ordered below primary name.**
   ProPublica states the search order explicitly — name, then alternate name,
   then city. That is exactly AG's "name tier above RRF", and it is worth
   splitting into *three* tiers rather than one, with `display_name` and
   `filer_name` occupying the alternate slot.
3. **EIN reachable from the free-text box, not only a separate lookup.** AG's
   EIN short-circuit is right, but the ProPublica behaviour shows users type EINs
   into the plain search box and expect it to work — keep the short-circuit *and*
   index the EIN.

### 2.2 Simpler.Grants.gov — the most directly comparable open-source rewrite

**The ADR.** [`2024-10-02-search-engine.md`](https://github.com/HHS/simpler-grants-gov/blob/main/documentation/wiki/product/decisions/adr/2024-10-02-search-engine.md)
chose **OpenSearch**. Alternatives and their recorded cons:

- *PostgreSQL*: "Search functionality not core to product operations"; "Difficult
  to scale independently from database load"; "Challenging to support advanced
  features"; "Performance limitations with complex queries."
- *Elasticsearch*: rejected because "Licensing controversies damaged community
  confidence" — an explicitly political, not technical, rejection.
- *OpenSearch*: chosen for "Project mandate to lean in to Open Source" and managed
  AWS availability. Recorded cons: "Additional infrastructure costs", "Data
  synchronization maintenance required."

Note what is **absent**: Typesense, Meilisearch, Vespa and Solr were never
evaluated, and cost was treated as a rounding error. **[inference]** This ADR is
of limited value as a *technology* comparison for a shoestring budget; its value
is entirely in the implementation that followed.

**Index lifecycle** ([`load_opportunities_to_index.py`](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/search/backend/load_opportunities_to_index.py)):
create `opportunity-index-<YYYY-MM-DD_HH-MM-SS>` → batch `bulk_upsert` with
`yield_per=1000` SQLAlchemy partitions and `selectinload` eager loading → atomic
`swap_alias_index` → `cleanup_old_indices`. The alias swap is a single
`indices.update_aliases` call carrying both the add and the removes, so it is
atomic server-side ([`opensearch_client.py`](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/adapters/search/opensearch_client.py)).

**They built a CDC queue and then abandoned it.** Migration
[`2024_10_28_add_opportunity_search_index_queue_table.py`](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/db/migrations/versions/2024_10_28_add_opportunity_search_index_queue_table.py)
adds `opportunity_search_index_queue`; a later trigger function fans **eight**
child tables (`opportunity_summary`, the three `link_*` tables, attachments…)
back to the parent `opportunity_id` and upserts into `opportunity_change_audit`
with `is_loaded_to_search = FALSE`. Migration
[`2026_08_31_fire_opportunity_search_queue_trigger_on_delete.py`](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/db/migrations/versions/2026_08_31_fire_opportunity_search_queue_trigger_on_delete.py)
extends the triggers to `AFTER DELETE` and — a detail worth stealing — has to add
`ON DELETE CASCADE` to the audit table's FK, because "the child-row deletes in the
same cascade re-queue the opportunity and dangle a row that violates this foreign
key."

Then [PR #7748](https://github.com/HHS/simpler-grants-gov/pull/7748) removed the
incremental loader outright. The code now carries a tombstone comment:

> `# NOTE: Incremental (changed-only) opportunity loading logic previously lived here.`
> `# It was removed as part of PR .../7748 during code cleanup.`

PR rationale: "A previous effort introduced incremental opportunity loading to only
index changed records, but that work was never completed or rolled out," and
attachment indexing is "**not viable for the current hourly full-refresh job due
to performance constraints**."

**[inference] The lesson is a scale threshold, not a doctrine.** They run a full
refresh *hourly* because their corpus is ~10k documents with no expensive
per-document computation. GS's foundations corpus is 203k documents and takes
3.5–4h. Simpler.Grants.gov's own experience says the incremental machinery is
worth building only when the full refresh stops fitting in the freshness budget —
and GS is 200× past that point. The trigger + change-audit table is nonetheless
the exact schema to copy; they built it correctly and simply didn't need it.

**Ranking design** ([`experimental_constant.py`](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/services/opportunities_v1/experimental_constant.py)):

```
"agency_code^16", "agency_code.keyword^16",
"top_level_agency_code^16", "top_level_agency_code.keyword^16",
"opportunity_number^12", "opportunity_number.keyword^12",
"opportunity_assistance_listings.assistance_listing_number^10",
"opportunity_assistance_listings.program_title^4",
"opportunity_title^2",
"summary.summary_description",   # ^1
```

with the in-file comment: "we do keyword & non-keyword for agency & opportunity
number as we don't want to compare to a tokenized value which may have split on
the dashes, but also still support prefixing (eg. USAID-*)". Identifiers outrank
free text 16:1.

Three named scoring profiles — `DEFAULT`, `EXPANDED`, `AGENCY` — are selectable
**per request** via an `experimental.scoring_rule` parameter
([issue #2289](https://github.com/HHS/simpler-grants-gov/issues/2289)). That is a
production A/B harness for relevancy that costs one enum.

**Analyzer** ([`opensearch_client.py`](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/adapters/search/opensearch_client.py)):
standard tokenizer + lowercase + **snowball English** stemmer, with a candid
warning in the source: "Snowball is really basic and naive … which might be fine
generally, but **we work with a lot of acronyms** and should verify that doesn't
cause any issues."

**Observability.** Every search logs `search.took_ms`, `search.timed_out`,
`search.shards_failed`, `search.total_records`, **`search.is_zero_result`**,
`search.max_score`, `search.total_relation` and per-aggregation overflow flags.
That `is_zero_result` boolean is the cheapest possible zero-result canary and GS/AG
have no equivalent.

**No semantic search.** A GitHub issue search across the repo for
semantic/embedding/vector in issue titles returns **zero** relevant results
**[measured]**; the only two relevancy issues are #2289 (scoring profiles) and
#2540 (relevancy sort option). The flagship federal grant-search rewrite is
deliberately BM25-only.

### 2.3 USAspending.gov — the only mature *incremental* pattern in the domain

**License CC0-1.0**, 463★, actively pushed (2026-09-04) —
[repo](https://github.com/fedspendingtransparency/usaspending-api). Their
[`elasticsearch_indexer`](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/etl/management/commands/elasticsearch_indexer.py)
management command is the most instructive artifact in this whole lane:

- `--start-datetime` sourced from `get_last_load_date` → **watermark incremental**.
- `--process-deletes` / `--deletes-only` → deletes are a **separate pass** with
  their own timestamp, because a watermark on `updated_at` structurally cannot see
  a deleted row.
- `--skip-date-check` guards that "the `es_deletes` timestamp occurs after the
  earliest timestamp associated with the Transaction loader" — i.e. they assert
  the *ordering of watermarks* before trusting a load.
- `--create-new-index` → full rebuild into a new index then alias swap; the same
  command does both modes.
- `--processes` (default 10) × `--partition-size` (default 10,000) over an id
  range, with the wry help text "psycopg kicked the bucket with 100".
- `toggle_refresh_off` for the duration of an incremental load, restored at the end.
- Extraction goes through a **SQL view** (`ensure_view_exists`, `--drop-db-view`),
  so the index's contract with the database is a named, versioned object rather
  than an ORM query buried in Python.
- An **`extra_null_partition`** for rows whose partition key is null — the classic
  silent data-loss bug in id-range partitioning.

**Reconciliation.** They ship a dedicated
[`check_es_doc_duplication`](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/etl/management/commands/check_es_doc_duplication.py)
command that detects duplicate `_id` across shards via terms aggregations, with an
honest help string: "There is no fast way to perform this check … (e.g. 8hrs for
100M docs)."

**Recipient name mapping**
([`es_recipient_profile_template.json`](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/etl/es_recipient_profile_template.json)):

```json
"recipient_name": { "type": "text", "fields": {
    "contains": { "type": "text", "analyzer": "contains_analyzer" },
    "keyword":  { "type": "keyword" } } }
```
with `contains_analyzer` = **ngram tokenizer + uppercase filter**, plus an
`edge_ngram_tokenizer` (min 2, max 10) analyzer for typeahead. `uei` and `duns` get
**the same three-way treatment** — text, ngram-contains, and keyword. A
`recipient_hash` keyword is the stable identity. Index settings during load:
`"index.refresh_interval": -1`, `number_of_replicas: 0`, 5 shards.

**Transfers:** the ngram "contains" sub-field on an identifier is precisely what
lets a user paste a partial EIN or partial name and still land; GS's Typesense
`ein` field with `num_typos:0` handles exact but not substring.

### 2.4 yente / nomenklatura / rigour / followthemoney — the name-search reference

This is the highest-leverage material in the lane. yente is **MIT**, 176★, pushed
the day of this research.

**Index mapping** ([`yente/search/mapping.py`](https://github.com/opensanctions/yente/blob/main/yente/search/mapping.py)) —
five derived name representations, all indexed, most **excluded from `_source`**
so they cost index size but not storage/transfer:

| Field | Type | Purpose |
|---|---|---|
| `names` | text, custom similarity | all name-typed props (`name`, `alias`, `previousName`…) `copy_to`-merged into one field |
| `names.ngrams` | text, 3-gram analyzer | "Trigram sub-field for **fuzzy candidate retrieval without query-time Levenshtein expansion**" |
| `name_parts` | keyword | tokenized name components |
| `name_symbols` | keyword | classified tokens (org-class, location, numeric, nickname, domain) |
| `name_phonetic` | keyword | phonetic keys |

Analyzers: `osa-analyzer` = standard tokenizer + lowercase + **asciifolding**;
`osa-normalizer` (for keywords) = lowercase + asciifolding; `osa-ngram-analyzer`
adds a 3–3 ngram filter.

**The custom similarity is the subtlest idea here**, and the source comment is
worth quoting entire:

> `"weak_length_norm": { "type": "BM25", "b": 0.25 }`
> "We use this for names, to avoid over-penalizing entities with many names. For
> example, for the query 'Hamas', we don't want to penalize our canonical Hamas
> entity for having many other names … Otherwise, a non-deduped Hamas entity that
> just has a single name always ranks higher up."

BM25's length normalization actively punishes a well-enriched record. Any GS
design that concatenates `name` + `display_name` + `filer_name` + enrichment prose
into one weighted tsvector or one Typesense field is walking into exactly this:
**the foundations we know most about will rank lowest.**

**Query-side symbol demotion** ([`yente/search/queries.py`](https://github.com/opensanctions/yente/blob/main/yente/search/queries.py)):

```python
TYPE_BOOSTS = { identifier: 8.0, date: 3.0, phone: 3.0, email: 3.0, country: 1.5 }
SYMBOL_BOOSTS = { NUMERIC: 1.3, LOCATION: 0.8, ORG_CLASS: 0.7,
                  SYMBOL: 0.3, NICK: 0.8, DOMAIN: 0.7 }
```

`ORG_CLASS` at 0.7 and generic `SYMBOL` at 0.3 is the direct answer to "Charitable
Tr", "Fdn", "Foundation", "Trust" — these tokens are **demoted, not removed**, so
they still discriminate weakly without dominating. Names are matched with
`operator: AND, boost 3.0` against `names`, and the ngram field is queried with
`minimum_should_match: "70%"` at boost 1.5, but *only* when fuzzy is enabled or the
name is a single token ("Single-word names are hard to match, so we use fuzzy
matching more aggressively").

**Reindex model** ([`docs/reindex.md`](https://github.com/opensanctions/yente/blob/main/docs/reindex.md)):
hourly (`YENTE_CRONTAB=0 * * * *`) metadata check against a published version
file; if fresh, build `yente-entities-default-<version>` from a 2GB+ JSON stream in
small batches, then alias-swap and delete old snapshots. Explicit operational
warning: with more than one instance you **must** set `YENTE_AUTO_REINDEX=false`
and drive `yente reindex` externally, "otherwise the workers will clash, as they
will all attempt to re-index in parallel." GS has exactly this hazard (Dagster
zombie reaper vs. a 4h rebuild) and no lock.

**Two-stage retrieve-then-score** ([`docs/deploy/scaling.md`](https://github.com/opensanctions/yente/blob/main/docs/deploy/scaling.md)):
fetch `limit × YENTE_MATCH_CANDIDATES` (default 5×10=50) candidates from ES
optimized for **recall**, then score them in Python. Throughput on a single GCE N4
vCPU: `logic-v2` ~4 req/s, `logic-v1` ~15 req/s, `logic-v1` with candidates=3 ~30
req/s. "Elasticsearch … in practice scales well and is not the bottleneck …
`/match` is CPU-bound — scoring candidates is the expensive part."

**followthemoney's name vocabulary**
([`LegalEntity.yaml`](https://github.com/opensanctions/followthemoney/blob/main/followthemoney/schema/LegalEntity.yaml),
[`Thing.yaml`](https://github.com/opensanctions/followthemoney/blob/main/followthemoney/schema/Thing.yaml)):

- `name` — "The primary name of the entity"
- `alias` — "An alternative or secondary name" (matchable)
- `previousName` — "A former name of the entity" (matchable)
- `weakAlias` — "A relatively broad or generic alias that **should not be used for
  matching** in screening systems. It may still be useful for identification
  purposes, particularly in confirming a possible match triggered by other
  identifier information." (`matchable: false`)
- `abbreviation` — "Abbreviated name or acronym", `matchable: false`, with a
  source `TODO` conceding the call is uncertain: "is un-matchable wise? The idea is
  to handle it like `weakAlias` rather than `alias`."

`Organization` (which explicitly covers "charities, foundations") sets
`caption: [name, alias, abbreviation, weakAlias, previousName, registrationNumber]`
— a documented *display* precedence separate from the match precedence.

**rigour's `org_types.yml` — with an important caveat.** 3,559 lines mapping legal
forms to `display` / `compare` / `generic` tiers. **[measured]** I grepped it: it
contains **zero** occurrences of `Fdn`, `Charitable Trust`, or a bare `Tr`
abbreviation, and only 2 lines matching "Foundation" at all (both Russian/Ukrainian
transliterations). It is a *corporate* legal-form dictionary — PLC, GmbH, Sh.p.k.,
ООО — with essentially no coverage of the US charitable forms GS deals in. **The
schema and the loading mechanism transfer; the dictionary content does not.** GS
would need to author its own `us_charitable_types.yml` in rigour's three-tier
shape (`display: Foundation`, `compare: Fdn`, `generic: FOUNDATION`, aliases:
`Fdn`, `Fdtn`, `Found`, `Foundtn`, …).

### 2.5 Grantmakers.io — the closest product analogue, and it bought its way out

~100k foundation profiles plus "millions of grant descriptions" from IRS 990-PF,
served as a static SvelteKit site on Cloudflare Pages/Workers/R2 with MongoDB
Atlas Serverless for detail records, and **Algolia InstantSearch** for search
([repo README](https://github.com/grantmakers/grantmakers-next)).

The framing in the Algolia case study is the one that matters for AG: Chad Kruse's
"core expertise in product strategy and development experience mostly front-end",
the site "built at zero cost and has zero ongoing costs, with the search
functionality fully hosted by Algolia" on "an incredibly generous free-tier that
effectively negates the need for a backend"
([case study](https://stories.algolia.com/why-hosted-search-made-sense-for-grantmakers-io-8974f5ed6bd6),
[Medium build post](https://medium.com/@chadkruser/building-grantmakers-io-d1f78326a0b5) — 403s to
automated fetch, cited from search summary).

**Their facet set** ([`search-profiles.svelte.js`](https://github.com/grantmakers/grantmakers-next/blob/main/apps/web/src/lib/assets/legacy/js/search-profiles.svelte.js)):

```js
const facets = [
  { facet: 'city',   label: 'City' },
  { facet: 'state',  label: 'State' },
  { facet: 'assets', label: 'Assets' },
  { facet: 'grants_to_preselected_only', label: 'Part XV Line 2 is Not Checked' },
];
```

That fourth facet is a **domain insight AG is missing**: 990-PF Part XV Line 2
records whether the foundation makes grants only to preselected charities. A grant
writer's single most valuable filter is "hide the foundations that will never read
my letter", and it is a checkbox on the form GS already parses. The hits template
also carries a `has_recent_grants` flag rendered as an icon — a data-freshness
signal surfaced *in the result row* rather than hidden.

There is also a commented-out `restrictSearchableAttributes` router state — they
had (or planned) a "search in: name only / everything" scope control and shelved
it. **[inference]** Worth having: AG's fused keyword+semantic path has no way for a
user to say "I mean the name, literally."

**Freshness** ([dataset page](https://www.grantmakers.io/about/the-dataset/)):
"The IRS publishes updates on a roughly monthly cadence. Grantmakers.io, in turn,
uses automated scripts to fetch, parse, and publish these updates," typically
within a week. They also state plainly the lag "between when grants are actually
made and when they appear in search results — typically 9-18+ months."

**And the grantee-name warning, which GS will hit the moment `grants` becomes a
search surface:**

> "Grantee names can be whatever the foundation wants to list. There is **no IRS
> requirement to use the actual legal name** for the grantees, and no requirement
> to distinguish between national HQ recipients and their local/regional
> organizations."

**Caveats.** The `grantmakers-next` repo has **no license file** (GitHub reports
`license: None`) and 6 stars — treat it as reference reading, not a dependency.

### 2.6 Government portals — grants.gov, SAM.gov, state

**[measured]** A live POST to `https://api.grants.gov/v1/api/search2` returns, in a
single response alongside `oppHits`: `hitCount`, `startRecord`, **`suggestion`**
(a did-you-mean slot), and four fully-counted facet blocks — `agencies` (28
buckets, with **nested `subAgencyOptions`** giving a two-level hierarchy, e.g.
USDA → USDA-NIFA), `eligibilities` (17), `fundingCategories` (27),
`oppStatusOptions` (4: posted 1,024 / closed 8,701 / forecasted / archived), plus
`dateRangeOptions`. No authentication required
([API guide](https://grants.gov/api/api-guide)).

Two things GS/AG should copy verbatim:
1. **Facet counts return with the results, computed over the full filtered set.**
   Users need to see "790 city-government-eligible" before clicking. AG's Typesense
   `filter_by` supports this; the Postgres fallback path does not, which is another
   axis of the two-engine drift.
2. **A hierarchical agency facet.** GS's `gov_opportunities.agency` is flat.

`Simpler.Grants.gov`'s own public API requires a key (**[measured]** an unkeyed POST
to `/v1/opportunities/search` returns 401), so their corpus size could not be read
directly; grants.gov's 1,585 open / 8,701 closed is the right order of magnitude
against GS's ~9,000.

### 2.7 Entity-search neighbours worth borrowing from

**OpenCorporates** documents its normalization publicly
([KB](https://knowledge.opencorporates.com/knowledge-base/api-walk-through-company-search/)):
case-insensitive; strips "non-text characters (e.g. dashes, parentheses, commas)"
and "common 'stop words' (e.g. 'the', 'of')"; **normalizes corporate suffixes
bidirectionally — Corp ↔ Corporation, Ltd ↔ Limited, Inc. ↔ Incorporated**;
word-order-independent ("Barclays Bank" matches "Bank Barclays"); tolerates extra
words; and **includes matches in previous company names**. Their reconciliation
scoring then "adjusts the score downward if the company is inactive or if it's a
foreign branch, ensuring that home companies and current companies score more
highly."

That last clause is a direct prescription for the GS #2025 filtered-KNN problem:
`is_active_grantmaker AND foundation_code<=4 AND country='US'` is currently a
**hard filter** that the vector index must post-filter around, at a ~60% pass
rate. OpenCorporates makes the equivalent distinction a **scoring demotion**
instead. A demotion needs no filtered-ANN machinery at all.

**Wikidata/CirrusSearch** indexes labels, aliases and descriptions as **separate
fields per language**, with `near_match` and `near_match_folded` analyzers
alongside the tokenized field, and notes candidly that "having a subfield per
language is costly in terms of Elasticsearch resources but allows a great level of
customization" ([T117520](https://phabricator.wikimedia.org/T117520),
[T323628](https://phabricator.wikimedia.org/T323628),
[Extension:CirrusSearch](https://www.mediawiki.org/wiki/Extension:CirrusSearch)).
The `near_match` idea — a *separate*, minimally-analyzed field whose only job is
"is this basically the exact string?" — is a cleaner implementation of AG's
promoted name tier than a post-hoc reorder of RRF output.

**GLEIF** fuzzy-matches at **Levenshtein distance 1** across all reference fields
and folds alternate/transliterated names into a single array; it also documents a
sharp limitation — "trade names, brand names, and informal names may not match"
([GLEIF API](https://www.gleif.org/en/lei-data/gleif-api),
[how to use LEI Search](https://www.gleif.org/en/lei-data/lei-search/about-lei-search/how-to-use-lei-search)).
Distance-1 is notably *tighter* than Typesense's default `num_typos:2`, and is the
right posture for a corpus with hundreds of near-duplicate names.

### 2.8 The 990 ETL ecosystem (context, not search)

- [CharityNavigator/irs990](https://github.com/CharityNavigator/irs990) — "ETL
  toolkit for 2.5 million electronic nonprofit tax returns"; the 990 Decoder led by
  Dr. David Borenstein.
- [CharityNavigator/990_long](https://github.com/CharityNavigator/990_long) —
  long-form of every field, keyed to the NOPDC "Datathon" **concordance**.
- [Nonprofit-Open-Data-Collective/990-xml-reader](https://github.com/Nonprofit-Open-Data-Collective/990-xml-reader)
  (IRSx) — versioned XML → standardized Python objects with original line numbers.
- [open990](https://github.com/opendatalove/open990) — consolidates individual XML
  filings into a single Parquet file merged with the NOPDC concordance.
- [irs990efile](https://github.com/Nonprofit-Open-Data-Collective/irs990efile) — R.

None of these ships a search layer. The transferable artifact is the **eFile Master
Concordance** — a community-maintained mapping across the many XML schema versions
([overview](https://nonprofit-open-data-collective.github.io/overview/)). GS's own
field-derivation logic is the same class of object and would be more defensible if
it cited the concordance rather than re-deriving it.

### 2.9 Static / edge search for the SEO play — verdict: not viable at 300k

- **Pagefind** (MIT, 5,446★, active): "our goal is that websites with tens of
  thousands of pages should be searchable"; "a full-text search on the entirety of
  MDN in under 300KB total, including the Pagefind library"; "for most sites this
  will be closer to 100KB". The index is **chunked and ordered** so a query for
  "CloudCannon" never downloads the chunk containing "Jamstack"
  ([CloudCannon announcement](https://cloudcannon.com/blog/introducing-pagefind/),
  [pagefind.app](https://pagefind.app/)). Real report in
  [issue #49](https://github.com/Pagefind/pagefind/issues/49): 29,977 pages →
  99,142 words → **225 index chunks in 41.7s**, but with the browser "freez[ing]
  for a couple of seconds" on short/common queries. [Issue #842](https://github.com/Pagefind/pagefind/issues/842)
  asks about 100k–1M pages and, as of this reading, has no maintainer answer.
  Community report of a crash at ~300,000 pages with Hugo.
- **Stork** (Apache-2.0, 2,759★): **last push 2023-07-01** — do not adopt.
- **Fuse.js**: fuzzy scoring with no inverted index; the comparison literature puts
  its comfort zone "under 10K items". **FlexSearch** is described as "excellent for
  100K+ documents". **Orama** (10,547★) has BM25 + vectors + facets in-browser but
  its license reads `NOASSERTION` on GitHub, which is a procurement problem, and
  one benchmark reports "roughly 3× the per-query latency" of a competitor for BM25
  ([comparison](https://www.pkgpulse.com/guides/fusejs-vs-flexsearch-vs-orama-client-side-search-2026),
  [ZBSearch vs Orama](https://www.zbsearch.dev/docs/zbsearch/vs-orama)).

**Verdict on the chunked-per-state idea from the brief.** A 50-shard split of 300k
foundations averages 6,000 per state, which *is* inside Pagefind's comfort zone —
but California and New York would be 30k–40k each, the user's first action is
almost always a **name** query rather than a state one, and cross-state search
(which is what a grant writer actually wants: "who funds food banks anywhere")
would require loading many shards. Grantmakers.io — the one project that actually
built this product, static, on Cloudflare, at exactly this corpus size — did **not**
use static search; it used hosted Algolia. **[inference]** That is the strongest
available evidence and I would treat static/edge search as ruled out for the
foundation directory's *search*, while remaining ideal for on-page search *within*
a single foundation's grant list.

### 2.10 Commercial comparators (documented behaviour only)

- **Candid Essentials** — search by name or EIN; filters for location + radius,
  revenue/assets/expenses ranges, Pub78 verification status, audit history, IRS
  form types filed, and "recently updated data"
  ([docs](https://developer.candid.org/reference/get-started-with-essentials);
  note their `llms.txt` at `developer.candid.org/llms.txt` and the `.md` suffix
  trick on any docs page).
- **Instrumentl** — publicly describes "a hybrid approach that combines automated
  sourcing technology with a dedicated human review team, rather than relying
  solely on scraping," 22,000+ active RFPs, 250+ added weekly
  ([Instrumentl](https://www.instrumentl.com/), secondary summaries at
  [grantsights](https://grantsights.com/blog/instrumentl-alternatives-2026)).
  **[inference]** Their moat is editorial, not algorithmic.
- **Grantable** is a writing tool, not a discovery tool. **CitizenAudit** publishes
  nothing about its stack that I could locate.

---

## 3. Transferable lessons, ranked by leverage for GS/AG

**L1 — Model names with FtM's vocabulary, not one column.** Adopt
`name` / `alias` / `previousName` / `weakAlias` / `abbreviation` explicitly. GS's
`name` vs `display_name` vs `filer_name` maps onto this cleanly: the IRS-abbreviated
string is an `abbreviation`+`weakAlias`, the enriched form is `name`, superseded
filer names are `previousName`. This is the prerequisite for every other name fix,
and it is a schema change, not a search change.
*Source:* [LegalEntity.yaml](https://github.com/opensanctions/followthemoney/blob/main/followthemoney/schema/LegalEntity.yaml),
[Thing.yaml](https://github.com/opensanctions/followthemoney/blob/main/followthemoney/schema/Thing.yaml).

**L2 — Build the US charitable abbreviation dictionary; nobody has.** ProPublica
returns 140 vs 1 for Foundation vs Fdn **[measured]**; rigour's org-type dictionary
has **zero** US charitable coverage **[measured]**. Author `us_charitable_types.yml`
in rigour's `display`/`compare`/`generic`+aliases shape, apply it **bidirectionally
at both index and query time** the way OpenCorporates does for Corp↔Corporation, and
you have both a recall fix and a marketing claim.
*Sources:* §2.1 probes, [org_types.yml](https://github.com/opensanctions/rigour/blob/main/resources/names/org_types.yml),
[OpenCorporates KB](https://knowledge.opencorporates.com/knowledge-base/api-walk-through-company-search/).

**L3 — Turn the eligibility predicate from a hard filter into a score demotion.**
The 1.7–2.8s filtered-KNN (`ef_search=200`, `iterative_scan=relaxed_order`, ~60%
pass rate) is a symptom of asking the ANN index to post-filter. OpenCorporates
ranks inactive and foreign-branch companies *down* rather than out; yente's
`SYMBOL_BOOSTS`/`TYPE_BOOSTS` do the same for weak tokens. Demotion needs no
filtered-ANN machinery and degrades gracefully instead of wandering.
*Sources:* [OpenCorporates KB](https://knowledge.opencorporates.com/knowledge-base/api-walk-through-company-search/),
[yente queries.py](https://github.com/opensanctions/yente/blob/main/yente/search/queries.py).

**L4 — Fix BM25 length normalization before it punishes enrichment.** yente sets a
custom `weak_length_norm` BM25 with `b: 0.25` on the names field specifically so
that entities with many aliases are not out-ranked by sparse duplicates. GS's
weighted A/B/C/D tsvector concatenates name + application_info + restrictions +
enrichment prose into one document; **[inference]** every well-enriched foundation
is currently being length-penalized relative to a bare stub with the same name.
This is cheap to test and would explain ranking complaints that look like
"relevance is random."
*Source:* [yente mapping.py](https://github.com/opensanctions/yente/blob/main/yente/search/mapping.py).

**L5 — Prefer indexed n-grams to query-time fuzzy.** yente's comment is explicit:
a `names.ngrams` trigram sub-field gives "fuzzy candidate retrieval **without
query-time Levenshtein expansion**", queried at `minimum_should_match: 70%`, and
aggressive fuzzy is reserved for single-token names. USAspending does the same with
a `contains` ngram sub-field on `recipient_name`, `uei` **and** `duns`. GLEIF caps
fuzzy at edit distance **1**. GS's Typesense currently leans on default `num_typos`
— tighter typos plus an ngram field is faster and more precise on a corpus with
hundreds of near-duplicate names.
*Sources:* [mapping.py](https://github.com/opensanctions/yente/blob/main/yente/search/mapping.py),
[es_recipient_profile_template.json](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/etl/es_recipient_profile_template.json),
[GLEIF](https://www.gleif.org/en/lei-data/lei-search/about-lei-search/how-to-use-lei-search).

**L6 — Copy USAspending's incremental contract wholesale.** It is CC0 and it is the
only mature pattern in the domain: a watermark from a `last_load_date` table, a
**separate delete pass** with its own watermark, a **watermark-ordering assertion**
before the load is trusted, extraction through a **named SQL view**, id-range
partitioning **with an explicit null partition**, `refresh_interval` disabled during
load, and the *same command* able to do a full rebuild + alias swap. GS's 3.5–4h
rebuild being killed at 45 minutes is precisely the failure this shape removes.
*Source:* [elasticsearch_indexer.py](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/etl/management/commands/elasticsearch_indexer.py).

**L7 — Copy Simpler.Grants.gov's trigger/change-audit schema, but read their
retreat correctly.** Their trigger fans eight child tables back to the parent id
and upserts `is_loaded_to_search = FALSE`; the delete-trigger migration also shows
the `ON DELETE CASCADE` FK trap you must fix at the same time. They then removed
the incremental *loader* because at ~10k docs an **hourly full refresh** is simply
cheaper. **[inference]** That is a scale verdict, not a doctrine: GS is 200× past
the threshold at which they'd have kept it.
*Sources:* [queue migration](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/db/migrations/versions/2024_10_28_add_opportunity_search_index_queue_table.py),
[delete-trigger migration](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/db/migrations/versions/2026_08_31_fire_opportunity_search_queue_trigger_on_delete.py),
[PR #7748](https://github.com/HHS/simpler-grants-gov/pull/7748).

**L8 — Take a reindex lock.** yente's docs state flatly that with multiple
instances you must disable auto-reindex "otherwise the workers will clash, as they
will all attempt to re-index in parallel," and yente ships `yente/search/lock.py`
for it. GS's zombie-reaper-killed rebuild leaving an orphan collection is the same
class of bug. Pair the lock with **alias-swap-only-on-verified-completion** — yente
notes "any future updates to the data will be indexed first, and the switch-over
… will be instantaneous," which is only safe because the swap is the last step.
*Source:* [docs/reindex.md](https://github.com/opensanctions/yente/blob/main/docs/reindex.md).

**L9 — Boost identifiers an order of magnitude above prose, and index them twice.**
Simpler.Grants.gov: `agency_code^16`, `opportunity_number^12`,
`assistance_listing_number^10`, `opportunity_title^2`, description `^1` — and every
identifier appears as **both** the tokenized and the `.keyword` field, with the
in-code reason: don't compare against a value the tokenizer split on dashes, but
still support prefixing. yente: `TYPE_BOOSTS[identifier] = 8.0`. GS's EIN
short-circuit is the right instinct; the boost table is how you make it degrade
gracefully when the EIN is partial or embedded in a longer query.
*Source:* [experimental_constant.py](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/services/opportunities_v1/experimental_constant.py).

**L10 — Ship a named, request-switchable scoring profile.** Simpler.Grants.gov's
`experimental.scoring_rule` enum (`DEFAULT` / `EXPANDED` / `AGENCY`) is a
production relevancy-experiment harness for the cost of one parameter, and it lets
a ranking change be *demonstrated* rather than argued. This is the cheapest
possible on-ramp to the golden-query-set evaluation the brief wants.
*Source:* [issue #2289](https://github.com/HHS/simpler-grants-gov/issues/2289).

**L11 — Log `is_zero_result` on every query, today.** Simpler.Grants.gov enriches
every search log with `search.took_ms`, `search.timed_out`, `search.shards_failed`,
`search.total_records`, `search.is_zero_result`, `search.max_score`,
`search.total_relation`. A zero-result rate is the one relevancy metric that needs
no golden set and no labeller, and it is the fastest way to *discover* the golden
set. GS/AG have two ranking paths that can disagree and no instrument that would
notice.
*Source:* [opensearch_client.py](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/adapters/search/opensearch_client.py).

**L12 — Add the "accepts unsolicited applications" facet.** Grantmakers.io facets
on `grants_to_preselected_only` (990-PF Part XV Line 2) and flags
`has_recent_grants` in the result row. For a grant writer at a shoestring
nonprofit, "will this foundation ever read my letter" and "is this data stale"
outrank every other refinement. GS already parses the form.
*Source:* [search-profiles.svelte.js](https://github.com/grantmakers/grantmakers-next/blob/main/apps/web/src/lib/assets/legacy/js/search-profiles.svelte.js).

**L13 — Return facet counts with results, on both paths.** grants.gov's search2
returns `agencies` (28 buckets, **nested sub-agencies**), `eligibilities` (17),
`fundingCategories` (27), `oppStatusOptions` and `dateRangeOptions` inline with
every response **[measured]**, plus a `suggestion` did-you-mean slot. AG's Typesense
path can do this; the Postgres fallback cannot — which makes the fallback not a
fallback but a **different product**, and is an argument for collapsing to one
engine.
*Source:* live probe of [api.grants.gov/v1/api/search2](https://grants.gov/api/api-guide).

**L14 — Two-stage retrieve-then-rank, with recall-optimized stage one.** yente
fetches `limit × 10` candidates optimized for recall and scores them in a second
CPU-bound pass, documenting exactly where the cost sits ("Elasticsearch … is not
the bottleneck"). That is a cleaner architecture than AG's current RRF-fusion of
two independently-ranked lists, because there is one ranking function and it is
testable in isolation.
*Source:* [docs/deploy/scaling.md](https://github.com/opensanctions/yente/blob/main/docs/deploy/scaling.md).

**L15 — A separate `near_match` field beats re-sorting fused output.** Wikidata
gives labels/aliases dedicated `near_match` and `near_match_folded` analyzers
alongside the tokenized field, and accepts the index-size cost knowingly. AG's
"name tier promoted above RRF" is the same intent implemented after the fact;
moving it into the index makes it a scoring input rather than a post-processing
special case.
*Source:* [T117520](https://phabricator.wikimedia.org/T117520), [T323628](https://phabricator.wikimedia.org/T323628).

**L16 — Do not build static/edge search for the 300k foundation directory.**
Pagefind targets "tens of thousands" and reports browser freezes on common queries
at 30k pages; Stork is unmaintained since 2023; Orama's license is `NOASSERTION`.
Grantmakers.io — the same product, the same corpus size, the same static-Cloudflare
SEO posture — chose hosted Algolia. Reserve static search for within-page grant
lists.
*Sources:* [issue #49](https://github.com/Pagefind/pagefind/issues/49),
[issue #842](https://github.com/Pagefind/pagefind/issues/842),
[Stork repo](https://github.com/jameslittle230/stork),
[grantmakers-next](https://github.com/grantmakers/grantmakers-next).

**L17 — Grantee names in Schedule I / 990-PF are free text and must not be treated
as entity names.** Grantmakers.io warns explicitly that there is "no IRS requirement
to use the actual legal name for the grantees, and no requirement to distinguish
between national HQ recipients and their local/regional organizations." When GS
makes `grants` a search surface ("Search 206,400 grants"), grantee strings need
resolution to foundations/nonprofits as a *separate, scored* step — the peer-similarity
matchmaker depends on it.
*Source:* [the dataset](https://www.grantmakers.io/about/the-dataset/).

---

## 4. What each system got publicly wrong

| System | Public misstep | Evidence |
|---|---|---|
| Simpler.Grants.gov | Built a full trigger-based CDC queue, never rolled out the loader, deleted it 22 months later as dead code | [PR #7748](https://github.com/HHS/simpler-grants-gov/pull/7748) |
| Simpler.Grants.gov | Snowball stemmer shipped with a known-unverified risk to acronym-heavy content, by the authors' own comment | [opensearch_client.py](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/adapters/search/opensearch_client.py) |
| Simpler.Grants.gov | Delete triggers required a follow-up FK `ON DELETE CASCADE` fix; the cascade re-queued the very row being deleted | [2026-08-31 migration](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/db/migrations/versions/2026_08_31_fire_opportunity_search_queue_trigger_on_delete.py) |
| Simpler.Grants.gov | ADR rejected Elasticsearch on licensing politics and never evaluated Typesense/Meilisearch/Vespa/Solr or cost at all | [ADR](https://github.com/HHS/simpler-grants-gov/blob/main/documentation/wiki/product/decisions/adr/2024-10-02-search-engine.md) |
| USAspending | Index-delete races with hourly snapshots forced a retry-and-skip path in `delete_index` (also present in SGG's client) | [opensearch_client.py](https://github.com/HHS/simpler-grants-gov/blob/main/api/src/adapters/search/opensearch_client.py) |
| USAspending | Custom shard routing made duplicate `_id`s possible; the dup-check they had to write takes ~8h per 100M docs | [check_es_doc_duplication.py](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/etl/management/commands/check_es_doc_duplication.py) |
| USAspending | Shipped `search/spending_by_award` with DUNS but not UEI long after UEI became the identifier of record | [issue #3847](https://github.com/fedspendingtransparency/usaspending-api/issues/3847) |
| ProPublica | No abbreviation handling; "Smith Family Fdn" returns 1 of 140 **[measured]**. Docs' claimed search fields omit EIN, which in fact works | §2.1 |
| yente | Had to add a custom BM25 and index weak aliases *after* discovering well-deduplicated entities were losing to sparse ones | [mapping.py](https://github.com/opensanctions/yente/blob/main/yente/search/mapping.py), [Yente 5.2 notes](https://discuss.opensanctions.org/t/yente-5-2-improvements-to-logic-v2-and-amazon-opensearch-serverless-support/245) |
| Pagefind | Common short queries freeze the browser for seconds at ~30k pages; the 100k–1M question sits unanswered | [#49](https://github.com/Pagefind/pagefind/issues/49), [#842](https://github.com/Pagefind/pagefind/issues/842) |
| Stork | Abandoned mid-life with 47 open issues and 2.7k stars | [repo](https://github.com/jameslittle230/stork) |
| Grantmakers.io | Zero-cost architecture is a dependency on one vendor's free tier for the product's core function; NEXT repo ships with no license | [case study](https://stories.algolia.com/why-hosted-search-made-sense-for-grantmakers-io-8974f5ed6bd6), [repo](https://github.com/grantmakers/grantmakers-next) |

---

## 5. Explicit inference ledger

Documented fact unless listed here.

1. ProPublica's engine is Elasticsearch — **inference** from `simple_query_string`
   grammar plus observed fuzzy behaviour. Never stated publicly.
2. grants.gov search2 is Solr/Lucene — **inference** from the in-band `suggestion`
   field and faceted bucket structure. Closed source.
3. "Simpler.Grants.gov's retreat from incremental indexing is a scale verdict, not
   a doctrine" — **inference**. Their PR says only that the work was never
   completed and full refresh suffices; they do not discuss corpus-size thresholds.
4. GS's weighted-tsvector concatenation is currently length-penalizing enriched
   foundations — **inference** from yente's documented experience with the same
   BM25 property. Untested against GS data; testable cheaply.
5. Static/edge search is ruled out for AG's 300k directory — **inference** from
   Pagefind's stated target range, the 30k-page freeze report, and Grantmakers.io's
   revealed preference at the same corpus size. No benchmark at 300k exists.
6. Instrumentl's moat is editorial rather than algorithmic — **inference** from
   their own "hybrid … dedicated human review team" framing.
7. Live probe figures marked **[measured]** are single observations on 2026-09-07
   and are not stable ground truth; the ProPublica abbreviation gap in particular
   should be re-probed with several name pairs before being used in marketing copy.


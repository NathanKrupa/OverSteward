ABOUTME: Design for replacing AG's slow cross-DB hybrid foundation search with a
ABOUTME: dedicated Typesense engine fed by a scheduled GrantSpider indexer.

# Foundation Search via Typesense

**Status:** Approved (Nathan, 2026-06-29) — architecture delegated to Chestertron.
**Repos:** aigranthelper (consumer + service infra), grantspider (producer/indexer).

## Problem

AG foundation search takes **4.6–7.4s** (measured 2026-06-29) versus a 0.92s
homepage. Even an empty-result query takes 4.6s, so it is the query machinery,
not result volume. Causes:

- AG queries `ag_research.foundations_v` **live, cross-DB** over the network on
  GrantSpider's Neon (remote round-trips, Neon autosuspend).
- The view is a non-indexable projection (`SELECT … COALESCE(…) FROM foundations
  WHERE is_active_grantmaker`).
- The pgvector semantic arm runs cosine distance over ~200k embeddings with **no
  ANN index** → full scan + sort every search.
- Hybrid fusion runs multiple arms (keyword FTS + semantic + name-tier).

It also can't find a foundation by EIN, and brittle name matching misses the
IRS-abbreviated stored names (e.g. "Lpr Charitable Tr" vs "LPR Charitable Trust").

## Decision: Typesense

A dedicated, self-hosted search engine (free; honors the no-paid-API rule). Over
Meilisearch for this job: mature keyword+vector hybrid (≥ v0.25), first-class
faceting, higher performance ceiling for a growing corpus (gov opps, grants).
Typo tolerance natively fixes the "Trust"/"Tr" mismatch; an EIN field natively
solves EIN lookup. Pinned version: **`typesense/typesense:30.2`** (latest GA).

## Architecture

```
GS (producer, owns data + Dagster)        Typesense (AG Railway project)     AG (consumer)
─────────────────────────────────        ──────────────────────────────    ──────────────
foundations / foundations_v               collection alias: foundations      FoundationSearchService
   │  nightly Dagster schedule              fields: id, ein, name,            .search(q):
   ▼                                         display_name, city, state,        → Typesense query
connectors/typesense_client.py ─public domain─▶ ntee_code, foundation_code,    (search-only key,
services/foundation_search_index.py        asset_amount, slug                  internal address)
   alias-swap full reindex (idempotent)   facets: state, ntee_code,          → ranked ids/slugs
                                            foundation_code, asset_amount      → render detail from
                                           sort: asset_amount desc             foundations_v (as today)
```

### Service placement — AG Railway project

The latency-critical path is **AG → Typesense on every search**; GS → Typesense
is a once-nightly batch. Railway's private network is per-project, so co-locating
Typesense in the **AG project** lets AG query it over the internal address
(`typesense.railway.internal:8108` — fast, free, no egress). GS reaches it
cross-project via a **public domain** (TLS + admin key) for the latency-tolerant
nightly reindex.

### Repo layout & deploy cadence

The Typesense **service definition lives in `aigranthelper/infra/typesense/`** —
a low-churn subdirectory decoupled from the frequently-changing app:

```
aigranthelper/infra/typesense/
  Dockerfile         # FROM typesense/typesense:30.2  (pins version in code)
  railway.json       # volume /data, healthcheck /health, restart policy, port 8108
  README.md          # env contract, deploy notes, rollback
  schema/foundations.collection.json   # reference copy of the collection schema (GS owns creation)
```

The Railway Typesense service is **repo-connected to this subdir** with watch
paths scoped to `infra/typesense/**`, so:

- App-code changes (the bulk of AG) redeploy only the **app** service — they ride
  the normal **Tuesday staging→prod promotion**.
- `infra/typesense/**` changes redeploy only the **Typesense** service — a rare
  event (version bump, resource change), independent of the Tuesday app train.

This is the "subdirectory that doesn't get regularly touched" — infra-as-code,
reproducible, reviewable, on its own deploy cadence.

### Tuesday promotion integration

- The AG **app's** Typesense integration (the `FoundationSearchService` query
  swap + `TYPESENSE_URL`/`TYPESENSE_SEARCH_API_KEY` env) promotes on the normal
  Tuesday schedule with the rest of the app.
- The **service** is provisioned once and only redeploys on `infra/typesense/`
  changes — not gated on the Tuesday train.
- **Ordering for safety:** the service must be up and the index populated (GS)
  **before** the AG query-swap promotes. The AG search keeps the existing
  Postgres path as a **fail-open fallback**, so even an early promote degrades
  gracefully rather than breaking search.

## Collection schema (GS owns creation)

GrantSpider (the producer) creates/updates the collection idempotently in its
indexer — it produces the documents and knows the field set (mirrors
`foundations_v`). AG owns the *service box*; GS owns *what's in it*.

| field | type | role |
|---|---|---|
| `id` | string | foundation id (Typesense doc id) |
| `ein` | string | exact match, `num_typos: 0` (EIN lookup) |
| `name` | string | searchable, typo-tolerant (raw IRS name) |
| `display_name` | string | searchable, typo-tolerant (Phase 2, from #1560) |
| `city`, `state` | string | `state` facet/filter |
| `ntee_code` | string | facet/filter |
| `foundation_code` | int32 | filter (AG applies `≤ 4`) |
| `country` | string | filter (AG applies `US`) |
| `asset_amount` | int64 | filter + default sort desc |
| `slug` | string | for building the detail URL |

Index the full `foundations_v` set (~204k). AG applies `foundation_code ≤ 4` /
`country = US` as `filter_by` for keyword/browse; **EIN lookup matches across the
full set** (mirrors the detail page's lack of a grantmaker gate).

## Reindex strategy — alias-swap (zero downtime)

GS reindexes nightly into a fresh collection (`foundations_<ts>`), then repoints
the `foundations` alias. AG always queries the stable alias. A failed reindex
leaves the prior collection serving. Incremental upserts can be added later;
full reindex of ~204k small docs is a few minutes and is the simplest correct
start.

## Secret / key management (hygiene)

- One **admin API key** generated at provision time (`openssl rand -hex 32`),
  set on the Typesense service as `TYPESENSE_API_KEY`. Never echoed to a
  transcript; stored once in a local `chmod 600` file for distribution.
- **GS** gets the admin key (writes) in its Railway env.
- **AG** gets a **scoped search-only key** (generated post-deploy via Typesense's
  `/keys` API, `actions: ["documents:search"]`, `collections: ["foundations"]`),
  set as `TYPESENSE_SEARCH_API_KEY`. AG never holds the admin key.
- Do not read keys back with `railway variables` (prints raw values). Verify
  presence with a boolean probe.

## AG query integration

`FoundationSearchService.search()` short-circuits to a Typesense query
(search-only key, internal URL): map facet params → `filter_by`, take ranked
ids/slugs, render detail from `foundations_v` as today. The EIN short-circuit
(#1014, already merged) and the Postgres hybrid path remain as a **fallback** if
`TYPESENSE_URL` is unset or the engine is unreachable (fail-open).

## Provisioning runbook (AG project)

```
railway link -p "AI Grant Helper" -e production
railway add -s typesense -i typesense/typesense:30.2 \
    -v "TYPESENSE_DATA_DIR=/data" -v "TYPESENSE_ENABLE_CORS=true" \
    -v "TYPESENSE_API_KEY=<generated, not echoed>"
railway volume add -s typesense -m /data        # persistent index storage
railway domain -s typesense -p 8108             # public domain for GS sync
# verify: curl https://<domain>/health  -> {"ok":true}
```

AG reaches it at `typesense.railway.internal:8108` (internal); GS at the public
domain.

## Phasing

- **Phase 1:** service up → GS indexes keyword + EIN + facets (raw `name`) → AG
  queries it. Delivers the full speed win + EIN + typo tolerance.
- **Phase 2:** index `display_name` (after GS #1560/#1561) for clean name
  matching; optionally push embeddings → Typesense hybrid, retiring pgvector.

## Build sequencing

1. Provision Typesense (this design) + capture `infra/typesense/` in AG.
2. GS indexer PR (connector + index service + Dagster nightly, alias-swap).
3. AG query-swap PR (FoundationSearchService → Typesense, Postgres fallback).
4. Verify end-to-end (latency < 100ms; "LPR Charitable Trust" and EIN both find
   LPR; facets work) → promote on a Tuesday.

## Rollback

AG's Postgres fallback means disabling Typesense = unset `TYPESENSE_URL` (search
reverts to the current path). The Typesense service + volume can be deleted
without touching AG or GS data (it is a derived index).

# Lane 2 — Keeping a derived search index consistent with a Postgres source of truth

Research for GrantSpider (GS) / AI Grant Helper (AG). Every factual claim carries a URL.
Statements marked **[INFERENCE]** are my reasoning, not documented fact. Statements marked
**[LOW-CONFIDENCE SOURCE]** come from secondary/SEO-shaped blogs I could not corroborate
against a primary doc.

---

## 0. One-page patterns matrix

| # | Pattern | What it is | Ops complexity | Freshness | Principal failure modes | Documented users / implementations |
|---|---------|-----------|----------------|-----------|------------------------|-----------------------------------|
| A | **Blue/green full rebuild behind an alias** | Build `idx_<ts>` from scratch, atomically repoint a virtual name, drop the old one | **Low** (one cron + one janitor) | = rebuild period (GS: 24 h) | Half-built orphan index eats RAM/disk; in-flight queries 404 if old index dropped too eagerly; no resume — a kill at 90 % restarts at 0 %; index is stale for the whole build window | Typesense aliases ([docs](https://typesense.org/docs/30.2/api/collection-alias.html)); Meilisearch `swapIndexes` ([docs](https://www.meilisearch.com/blog/zero-downtime-index-deployment)); Elasticsearch reindex+alias; Solr `REINDEXCOLLECTION` ([docs](https://solr.apache.org/guide/solr/latest/indexing-guide/reindexing.html)); Algolia `replaceAllObjects` ([docs](https://www.algolia.com/doc/tutorials/indexing/synchronization/atomic-reindexing/)); Searchkick `reindex(mode: :async)` + `promote` ([repo](https://github.com/ankane/searchkick)); GOV.UK ([runbook](https://docs.publishing.service.gov.uk/manual/reindex-elasticsearch.html)); Manticore plain-index `--rotate` ([manual](https://manual.manticoresearch.com/Adding_data_from_external_storages/Rotating_an_index?static=true)) |
| B | **Watermark / cursor incremental upsert + tombstones** | Poll `WHERE updated_at > last_watermark`, bulk-upsert; a deletes table drives deletions | **Low–medium** | seconds–minutes | Out-of-order commits silently skip rows forever; `updated_at` not maintained by a trigger; deletes and *eligibility flips* invisible; bulk backfill = thundering herd; cursor written before the apply commits = silent loss | Typesense's own documented recommendation ([guide](https://typesense.org/docs/guide/syncing-data-into-typesense.html)); Sequin's survey ([post](https://blog.sequinstream.com/all-the-ways-to-capture-changes-in-postgres/)); Airbyte incremental + `xmin` mode ([docs](https://docs.airbyte.com/integrations/sources/postgres)) |
| C | **Transactional outbox + relay** | Business write and an `outbox` row in one ACID txn; a relay drains the outbox to the index | **Medium** | seconds | Sequence gaps + out-of-order commit make naive `position > last` lose messages (fix: `xid8` + `pg_snapshot_xmin`); write amplification; unbounded outbox if the relay stalls | Debezium Outbox Event Router ([docs](https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html)); SeatGeek ([post](https://chairnerd.seatgeek.com/transactional-outbox-pattern/)); the ordering fix ([event-driven.io](https://event-driven.io/en/ordering_in_postgres_outbox/)) |
| D | **CDC via logical decoding** | Read the WAL through a replication slot; stream inserts/updates/deletes | **High** | sub-second | Slot not consumed ⇒ unbounded WAL retention ⇒ DB outage; slot dropped after inactivity (Neon: ~40 h); publisher compute pinned awake (Neon: no scale-to-zero); snapshot↔stream handoff; schema evolution | Debezium ([PG connector](https://debezium.io/documentation/reference/stable/connectors/postgresql.html)), Debezium Server standalone/no-Kafka with HTTP + Redis sinks ([docs](https://debezium.io/documentation/reference/stable/operations/debezium-server.html)); PGSync, MIT, Postgres→ES/OpenSearch, no Kafka, checkpointed ([repo](https://github.com/toluaina/pgsync)) |
| E | **Snapshot-format bulk build + CDC catch-up** | Build the engine's native on-disk index offline, restore it, then reconcile against a live-write temp index | **Very high** | hours for the base, ~1 h catch-up | Needs a big batch engine (Spark); engine-specific snapshot format; only pays off at very large corpora | Notion, Spark → ES native snapshots, then `_reindex` from `tmp-*` with `version_type: external`, `conflicts: proceed` ([case study](https://www.zenml.io/llmops-database/rebuilding-a-production-search-reindexing-pipeline-at-scale)) |
| F | **No sync at all — index inside Postgres** | BM25/vector index maintained transactionally by the DB | **Lowest** (no pipeline) | transactional | Ties search RAM/CPU to the OLTP box; extension availability on managed Postgres; licence | ParadeDB `pg_search` ([docs](https://docs.paradedb.com/welcome/introduction)); `pgvector`; GS already runs `tsvector`+`pg_trgm`+`pgvector` |
| G | **Dual write from the app** | App writes DB and index directly | Low to build, **unbounded to operate** | seconds | The classic race: two writers apply DB and index in opposite orders and diverge permanently, with no self-healing | Named as an anti-pattern by Kleppmann ([post](https://martin.kleppmann.com/2015/03/04/turning-the-database-inside-out.html)) and by every outbox write-up |

**Reading of the matrix for GS [INFERENCE]:** GS is at 203k slow-changing docs on a
$50/month Neon budget. Rows A + B (nightly alias rebuild for the base, watermark upsert for
the delta) is the shape the Typesense docs themselves prescribe. D and E are for corpora one
to three orders of magnitude larger than GS's, and D specifically costs real money on Neon.

---

## 1. The canonical patterns

### 1.1 Blue/green full rebuild behind an alias

**Typesense.** An alias is "a virtual collection name that points to a real collection,"
usable anywhere a collection name is accepted
(https://typesense.org/docs/30.2/api/collection-alias.html). The documented workflow is
exactly GS's: create `companies_june11`, index into it in the background, then repoint the
`companies` alias; applications need no change. The alias docs say nothing about what happens
to a *failed* build — that is left entirely to the caller. The Typesense guide states the
policy plainly: "Reindex into a new collection and then switch the alias over"
(https://typesense.org/docs/guide/syncing-data-into-typesense.html).

Two Typesense-specific hazards:

- **Import always returns HTTP 200.** "The import endpoint will always return a `HTTP 200
  OK` code, regardless of the import results"; per-document results are one JSONL line each,
  and a failed document does not stop the others
  (https://typesense.org/docs/30.2/api/documents.html). A client that checks only the status
  code will happily swap an alias onto a collection missing tens of thousands of documents.
  A secondary write-up lists this as production failure pattern #1
  (https://perun.au/insights/typesense-production) **[LOW-CONFIDENCE SOURCE for the framing;
  the underlying API behaviour is documented above]**.
- **Dropping the old collection immediately after the swap** can 404 in-flight queries that
  already resolved the alias (same secondary source) **[LOW-CONFIDENCE SOURCE]**. The safe
  form is a drain window: swap, wait longer than your query timeout, then delete. Note that
  `DELETE /collections/:collection` "performs disk compaction to reclaim space" and can be
  told not to via `compact_store`
  (https://typesense.org/docs/30.2/api/collections.html) — worth using so the janitor does
  not stall the node.
- Typesense holds its inverted index in RAM, so an orphaned half-built collection is not a
  cosmetic problem, it is a memory leak until something drops it
  (https://typesense.org/docs/guide/system-requirements.html).

**Meilisearch.** `swapIndexes` swaps the contents of two indexes atomically, including
documents, settings and task history, so clients "never see a partial state" and can swap
several pairs in one request (https://www.meilisearch.com/blog/zero-downtime-index-deployment,
spec at https://specs.meilisearch.dev/specifications/text/0191-swap-indexes-api.html). After
the swap the temporary index holds the *old* content, so rollback is a second swap. That
rollback property is strictly better than Typesense's create-and-repoint, where rollback means
keeping the previous timestamped collection alive.

**Elasticsearch / OpenSearch.** `_reindex` supports `requests_per_second` throttling and
sliced parallelism, and the documented recovery advice for a failed reindex is blunt: "you can
resume the process if there are any errors by removing the partially completed source and
starting over"
(https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reindex-indices). There is no
built-in checkpoint. Elastic's own comparison article notes that "writes accepted by the
source index after the scroll search starts are not guaranteed to appear in the destination
index," so exact parity needs a write pause or a final short catch-up window
(https://www.elastic.co/search-labs/blog/elasticsearch-index-comparison).

**Solr.** `REINDEXCOLLECTION` handles the alias for you: if the target name equals the source
name, "a unique sequential name will be generated for the target collection, and after
reindexing is done an alias will be created that points from the source name to the actual
sequentially-named target collection"
(https://solr.apache.org/guide/solr/latest/indexing-guide/reindexing.html).

**Algolia.** `replaceAllObjects` builds `<index>_tmp` and moves it over. Documented caveats
that generalise to every blue/green scheme: record count temporarily doubles; if a step
errors "the temporary index won't be deleted" (i.e. orphans are the expected failure residue);
and settings/synonyms are recreated from the source, silently discarding dashboard edits
(https://www.algolia.com/doc/tutorials/indexing/synchronization/atomic-reindexing/,
https://support.algolia.com/hc/en-us/articles/4407531208337-What-is-a-temporary-index).
Algolia's guidance is to run it at most **1–3 times per month**
(https://support.algolia.com/hc/en-us/articles/38545749534865-How-often-should-I-run-replaceAllObjects)
— i.e. the vendor with the most experience of atomic reindex treats it as a rare operation,
not a nightly one, with incremental updates carrying the load in between.

**Manticore.** Plain (disk) indexes cannot be updated at all — "You only can batch rebuild the
entire disk index from scratch" — and rotation is a filesystem rename plus SIGHUP to `searchd`,
governed by `seamless_rotate`
(https://manual.manticoresearch.com/Adding_data_from_external_storages/Rotating_an_index?static=true).
Real-time indexes are the incremental alternative. This is the cleanest statement of the
industry's fork: rebuild-and-rotate *or* real-time, and mature systems run both.

**Long-running rebuild checkpointing.** No mainstream engine checkpoints a rebuild for you.
Every documented example pushes the checkpoint into the *producer*:

- Debezium chunks by primary key with `ORDER BY <pk> LIMIT <chunk>` and a `WHERE` excluding
  already-processed keys, and streamed events carry "serialized PK related to it to enable
  resume of the windowing upon connector restart"
  (https://github.com/debezium/debezium-design-documents/blob/main/DDD-3.md).
- Searchkick, with Redis, exposes `Searchkick.reindex_status(index_name)` so a parallel
  reindex is observable mid-flight, and `promote(index_name)` is a separate explicit step
  from the build (https://github.com/ankane/searchkick).
- GOV.UK simply **locks the index against writes** for the ~2 h rebuild and republishes
  anything lost on rollback
  (https://docs.publishing.service.gov.uk/manual/reindex-elasticsearch.html). Crude, honest,
  and it works at their scale.

### 1.2 Incremental sync with a watermark + tombstones

This is what the Typesense documentation actually recommends for a system like GS. Verbatim
options from https://typesense.org/docs/guide/syncing-data-into-typesense.html:

1. Poll the primary DB every ~30 s for rows with `updated_at` since the last sync, and
   `import` them with `action=upsert`.
2. Hook a CDC/change listener and queue updates, flushing a bulk import every ~5 s.
3. Buffer changes in a table so the application never waits on Typesense.

Deletes: "use soft deletes with an `is_deleted` boolean field, or save deleted record IDs in a
separate table with timestamps," then `DELETE /collections/:c/documents?filter_by=id:[id1,id2,...]`
(same guide; delete-by-filter documented at
https://typesense.org/docs/30.2/api/documents.html).

**The pitfalls, with mechanisms:**

- **Out-of-order commits — the one that silently loses rows forever.** Sequin states it
  directly: "Postgres datetimes and sequences can commit out-of-order," creating race
  conditions where rows mid-commit are skipped during the polling window
  (https://blog.sequinstream.com/all-the-ways-to-capture-changes-in-postgres/). The mechanism
  is that `now()`/`nextval()` are evaluated *before* commit, so a long transaction can commit a
  row whose `updated_at` is already behind a watermark you advanced. The rigorous fix is a
  transaction-id gate: store `xid8` on the row and read only rows with
  `transaction_id < pg_snapshot_xmin(pg_current_snapshot())`, which is "the minimum active
  transaction id," so you never read past an in-flight transaction
  (https://event-driven.io/en/ordering_in_postgres_outbox/;
  https://pgpedia.info/p/pg_snapshot_xmin.html). The cheap fix is an **overlap window** —
  re-scan the last N minutes every time, where N exceeds your longest write transaction. Because
  `action=upsert` is idempotent, overlap costs only throughput.
- **`xmin` as the cursor is a trap at scale.** Airbyte offers a cursorless `xmin` mode but
  documents that the 32-bit xid wraps at 4,294,967,295, after which "the xmin column cannot be
  reliably used as a cursor," causing full re-syncs; their connector detects wraparound and
  errors telling you to switch to CDC (https://docs.airbyte.com/integrations/sources/postgres).
  `xid8` (64-bit, used by `pg_current_snapshot`) does not wrap.
- **`updated_at` must be maintained by a trigger, not by the ORM.** [INFERENCE, but this is
  the single most common cause of permanently-missing documents: any code path that writes the
  row without touching `updated_at` — a bulk `UPDATE ... SET display_name = ...`, an Alembic
  data migration, a psql one-off — removes that row from the change stream forever, and nothing
  ever notices.]
- **Deletes are invisible, and *eligibility flips* are worse.** A row that goes
  `is_active_grantmaker = false` or `foundation_code = 5` is an UPDATE in Postgres and a DELETE
  in the index. If the syncer's source query is the *eligible* set, that row simply stops
  appearing and is never removed from the index. Both Sequin and the Typesense guide flag
  deletes as needing separate machinery
  (https://blog.sequinstream.com/all-the-ways-to-capture-changes-in-postgres/;
  https://typesense.org/docs/guide/syncing-data-into-typesense.html). [INFERENCE: the fix is
  to scan the **base** table by watermark and let the syncer decide per row whether to upsert or
  delete, rather than scanning a pre-filtered eligible view.]
- **Bulk backfills produce a thundering herd.** A `display_name` backfill that touches 300k
  rows makes every one of them "changed" at the same instant. Typesense returns HTTP 503 as
  backpressure and asks for exponential retry at 10–60 s intervals, and warns to "limit
  concurrent bulk imports to N-2 cores"
  (https://typesense.org/docs/guide/syncing-data-into-typesense.html). [INFERENCE: better than
  retry-storming is to let the *nightly rebuild* absorb known bulk backfills — mark them so the
  incremental syncer skips them — since a full rebuild is already scheduled.]
- **Cursor durability ordering.** Write the new watermark only after the index write is
  acknowledged and durable; the reverse order turns a crash into silent loss. [INFERENCE, but
  it is the standard rule for at-least-once pipelines and the reason upserts must be idempotent.]

**LISTEN/NOTIFY as the trigger is not a substitute for the watermark.** Notifications are
at-most-once and transient, the payload is capped under 8000 bytes, every NOTIFY-carrying commit
takes a lock that serialises commits, and PgBouncer in transaction mode silently breaks LISTEN
(https://www.postgresql.org/docs/current/sql-notify.html;
https://blog.sequinstream.com/all-the-ways-to-capture-changes-in-postgres/;
https://www.stacksync.com/blog/beyond-listen-notify-postgres-request-reply-real-time-sync).
Sequin's verdict is the right one: use it to *shorten latency* on top of a polling loop, never
as the loop itself.

### 1.3 Change Data Capture

**Debezium.** The reference implementation. For Postgres it consumes a logical replication slot
(https://debezium.io/documentation/reference/stable/connectors/postgresql.html). The
snapshot↔streaming handoff is its most transferable idea: **incremental snapshots**, based on
Netflix's DBLog watermark paper, run snapshot chunks *concurrently* with streaming, writing
`snapshot-window-open` / `snapshot-window-close` records to a signalling table; when the
connector sees the window markers in the log it reconciles, dropping from the chunk buffer any
key that also arrived as a streamed event, so there is exactly one winning version
(https://debezium.io/blog/2021/10/07/incremental-snapshots/;
https://github.com/debezium/debezium-design-documents/blob/main/DDD-3.md). Chunks are ordered
by PK and bounded by the max key at snapshot start; the connector resumes from the last
recorded key after a restart. **This is the design GS should steal even without adopting CDC**
[INFERENCE].

Debezium can run **without Kafka**: Debezium Server is "a ready-to-use application that streams
change events from a data source directly to a configured data sink without relying on an
Apache Kafka Connect infrastructure," with sinks including Redis Streams, RabbitMQ, NATS,
Pub/Sub, Kinesis and **HTTP webhooks**
(https://debezium.io/documentation/reference/stable/operations/debezium-server.html;
https://github.com/debezium/debezium-server;
https://debezium.io/blog/2026/07/06/kafka-less-migration/). One JVM container on Railway is
therefore technically feasible for GS.

**PGSync.** MIT-licensed, ~1.4k stars, Postgres/MySQL → Elasticsearch/OpenSearch, using
logical replication with **no Kafka**; you declare the target document shape in JSON and it
generates the denormalising joins. It is checkpointed — "fault-tolerant: does not lose data,
even if processes crash… The process can be recovered from the last checkpoint" — with optional
Redis/Valkey backing, and gives transactionally-consistent, correctly-ordered output
(https://github.com/toluaina/pgsync;
https://medium.com/@toluaina/real-time-integration-of-postgresql-with-elasticsearch-with-pgsync-9425ffa9b4e9).
Requires `wal_level = logical` and `max_replication_slots >= 1`. **Bad fit for GS: it targets
Elasticsearch/OpenSearch only, not Typesense.**

**The replication-slot hazard is the real cost of CDC.** If the consumer stalls, Postgres
retains WAL for the slot until the disk fills and the database stops accepting writes
(https://blog.peerdb.io/overcoming-pitfalls-of-postgres-logical-decoding;
https://www.postgresql.org/docs/current/logicaldecoding-explanation.html). The mirror-image
problem is a slot that never *advances* because the captured tables are quiet, which Debezium
solves with heartbeats — `heartbeat.interval.ms` plus a `heartbeat.action.query`, or
`pg_logical_emit_message(false, 'heartbeat', now()::varchar)` — so the slot's
`confirmed_flush_lsn` keeps moving
(https://www.morling.dev/blog/insatiable-postgres-replication-slot/).

**Neon specifically — this is the decisive fact for GS.** Neon supports logical replication as
a publisher, but the docs state that while a subscriber is connected "your compute stays active
while subscribers are connected and **will not scale to zero**, resulting in ongoing compute
usage and higher bills"; limits are `max_wal_senders = 10` and `max_replication_slots = 10`;
and Neon **drops inactive replication slots after roughly 40 hours** without progress
acknowledgment (https://neon.com/docs/guides/logical-replication-neon;
https://neon.com/docs/introduction/cost-optimization). Pricing: minimum compute is 0.25 CU and
Launch is $0.106/CU-hour, so a permanently-awake compute floors at ~187.5 CU-hours/month ≈
**$19.87/month of compute you cannot avoid**, before storage
(https://neon.com/pricing; https://neon.com/docs/introduction/plans). Against a $50/month Neon
target that is ~40 % of the budget spent on the sync mechanism alone. **[INFERENCE: if GS's
Dagster daemon already keeps the compute awake round the clock, the *marginal* cost is near
zero — so measure current scale-to-zero hours before believing either number.]**

Supabase and other hosted Postgres offer logical replication on comparable terms; GS is on
Neon, so the Neon numbers govern.

### 1.4 Outbox, dual writes, and derived data

Kleppmann's framing is the one to use in design docs: secondary indexes, caches and
materialized views are all "derived data structures created from a primary dataset," and
application-managed dual writes are unsafe because "two processes concurrently writing to the
database and also updating the cache… might update the database in one order, and the cache in
the other order, and now the two are inconsistent." Developers "just pretend that the race
conditions don't exist, because they are just too much to think about"
(https://martin.kleppmann.com/2015/03/04/turning-the-database-inside-out.html). The remedy is a
single ordered write path from which every derived view is rebuilt.

The **transactional outbox** is the practical, non-Kafka form of that: business row and event
row in one ACID transaction, converting a dual write into a single write, with a relay draining
the outbox (https://chairnerd.seatgeek.com/transactional-outbox-pattern/;
https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html).
In Postgres, triggers writing old/new JSONB to a changelog table, consumed with
`FOR UPDATE SKIP LOCKED`, is the standard shape; the documented costs are write amplification
and an unbounded queue if the worker falls behind
(https://blog.sequinstream.com/all-the-ways-to-capture-changes-in-postgres/). And the
non-obvious correctness bug — bigserial gaps and out-of-order commits — has the `xid8` +
`pg_snapshot_xmin` fix given above (https://event-driven.io/en/ordering_in_postgres_outbox/).

**[INFERENCE for GS: an outbox is strictly better than a watermark scan and only marginally
more work, because it captures deletes and eligibility flips natively. But it requires every
writer to go through the trigger — which, being a trigger rather than application code, it
does. A single `AFTER INSERT OR UPDATE OR DELETE ON foundations` trigger writing
`(id, op, xid8, changed_at)` to `search_outbox` is perhaps 30 lines and closes the entire
class of "the backfill forgot to bump updated_at" bugs.]**

### 1.5 No sync at all: the index inside Postgres

ParadeDB's `pg_search` embeds a Tantivy BM25 index in Postgres, maintained inside the writing
transaction and under MVCC, so it "can never drift from the source row"
(https://docs.paradedb.com/welcome/introduction;
https://www.paradedb.com/blog/elasticsearch-vs-postgres). Vendor content, but the structural
claim is correct and worth stating: **the cheapest reconciliation is the one you do not have to
run.** ParadeDB's companion argument about Elasticsearch — that search reads Lucene segments
refreshed asynchronously, so "a recently acknowledged write may not show up until the next
refresh" — is also accurate and applies to any external engine
(https://www.paradedb.com/blog/elasticsearch-was-never-a-database). Trade-offs (search RAM and
CPU land on the OLTP box; extension availability on Neon; licence) belong to Lane 4.

GS already has half of this: a generated `search_tsv` with GIN, `pg_trgm`, `unaccent` and
`pgvector` — all transactionally consistent by construction. The drift problem GS has is
entirely self-inflicted by adding Typesense **[INFERENCE]**.

---

## 2. Reconciliation and verification

### 2.1 What the engines give you

- **Elasticsearch, comparing two indices** (https://www.elastic.co/search-labs/blog/elasticsearch-index-comparison):
  1. `_count` on both as the cheap baseline — if counts match, stop.
  2. With stable IDs, `_reindex` from A into B with `op_type=create`, `conflicts=proceed`:
     the `created` count *is* the set of missing documents, `version_conflicts` the set already
     present. ~6 s for 1M docs, server-side.
  3. With unstable IDs, open a point-in-time, scan with `search_after` on `_shard_doc`, and
     batch-verify with `_msearch` on business keys (~1 m 42 s for 1M docs, or ~36 s split five
     ways). The article's own conclusion: adopt **functional IDs derived from business keys** at
     ingestion time and the whole problem gets cheap.
- **Elasticsearch vs an external store** (https://www.elastic.co/blog/elasticsearch-verifying-data-integrity-with-external-data-stores):
  because "it's often hard to implement solutions surrounding two-phase commits due to the lack
  of transaction support across all systems in play," Elastic recommends restructuring the
  question from "does each document exist?" to "**what is missing?**" — index the numeric
  primary key as a real field and use a histogram aggregation with a bucket selector to return
  only the gaps. That is O(buckets) rather than O(documents).
- **GitLab** ships this as a product feature: *index integrity*, feature-flagged in 15.10 and
  GA in 16.4, "detects and fixes missing repository data," triggered automatically when a scoped
  code search returns no results
  (https://docs.gitlab.com/integration/advanced_search/elasticsearch/). The worker "performs an
  Elasticsearch query with aggregations to get counts for documents and compares aggregations to
  database statistics"; a repository with `repository_size > 0` but `blob_count == 0` is a
  discrepancy. There are Rake tasks (`gitlab:elastic:index_projects_status`) for the same
  question asked manually, and the long-standing issue arguing for periodic repair is
  https://gitlab.com/gitlab-org/gitlab/-/issues/214601.
- **Notion** ran **two offline validators in CI**: an aggregate validator comparing document
  counts and type distributions, and a field-level validator doing *stratified sampling by
  block type* asserting byte-for-byte identical field values. That took them from ~90 % to
  100 % consistency
  (https://www.zenml.io/llmops-database/rebuilding-a-production-search-reindexing-pipeline-at-scale).
  Their catch-up reconciliation used `version_type: external` with `conflicts: proceed`, i.e.
  **document versioning makes the merge safe and retryable**.
- **Meilisearch** has the best introspection of the small engines: `GET /tasks` exposes every
  indexing task with `enqueued`/`processing`/`succeeded`/`failed`/`canceled`, type (including
  `indexSwap`), `enqueuedAt`/`startedAt`/`finishedAt`, duration, batch id and full error detail,
  filterable by index, status, type and time range
  (https://www.meilisearch.com/docs/reference/api/tasks). You can build a freshness SLI directly
  off it.
- **Typesense** has much less. What exists and is useful:
  `GET /collections/:c` and `GET /collections` return **`num_documents`** per collection;
  collections carry an arbitrary **`metadata` object** whose fields "are persisted and returned
  in the `GET /collections` end-point," with the docs' own example being
  `{"batch_job": 325, "indexed_from": "2023-04-20T00:00:00.000Z"}`
  (https://typesense.org/docs/30.2/api/collections.html). Plus `GET /health`, `GET /stats.json`,
  `GET /metrics.json`, `POST /operations/snapshot` for a point-in-time data-directory backup,
  and `POST /operations/db/compact`
  (https://typesense.org/docs/30.2/api/cluster-operations.html). There is no task queue API and
  no per-document version field.
- **Solr / Manticore**: neither offers source-vs-index reconciliation; Solr's alias-based
  `REINDEXCOLLECTION` leaves verification to you
  (https://solr.apache.org/guide/solr/latest/indexing-guide/reindexing.html).

### 2.2 Freshness SLOs

The generic framing that transfers: a freshness SLI measures "how current your data is relative
to its source"; events should carry event time, ingestion time, processing time and
availability time so you can compute end-to-end lag; the SLO is then "no older than X, Y % of
the time" (https://oneuptime.com/blog/post/2026-01-30-freshness-slos/view;
https://pipecode.ai/blogs/data-freshness-sla-monitoring-budgets) **[LOW-CONFIDENCE SOURCES —
the concept is standard, these are the clearest write-ups I found, not authorities]**.

Dagster productises this: **asset freshness policies** (time-window and cron), which superseded
freshness checks in 1.12 (https://docs.dagster.io/guides/observe/asset-freshness-policies), and
**asset checks** which, with `blocking=True`, prevent downstream materialization when they fail
(https://docs.dagster.io/guides/test/asset-checks). Since GS already runs Dagster, a blocking
asset check is the natural home for a "do not swap the alias" gate.

### 2.3 A concrete reconciliation design for GS **[INFERENCE, built on documented APIs]**

Nothing off the shelf compares Postgres to Typesense. Build it from three documented primitives:

1. **Total parity.** `GET /collections/<alias>` → `num_documents`; compare with the eligible
   row count from Postgres. Alert on any difference beyond a small tolerance.
2. **Per-partition parity, cheap.** One Typesense search with `q=*`, `per_page=0`,
   `facet_by=state`, `max_facet_values=100` gives ~50 bucket counts in one request; the
   Postgres side is one `GROUP BY state`. Repeat on `foundation_code`. This is Elastic's
   "what is missing?" trick — O(buckets), not O(documents) — transplanted onto Typesense
   facets. Per-bucket comparison catches a truncated import that a total-count check with a
   1 % tolerance would wave through.
3. **Sampled field-level spot-check.** Notion's stratified sample: pull 200 random eligible
   foundations stratified by state, fetch each by id from Typesense, and assert the indexed
   `name`, `display_name`, `asset_amount` and `state` equal the DB.

The canary rule from the estate's own doctrine applies with full force: **this check must ship
with the fixture that makes it fail.** Build a scratch collection, delete 50 documents from it,
and prove the checker goes red for the stated reason; a reconciliation canary that has never
been seen red is decoration.

---

## 3. Long-running batch jobs under a supervisor that kills silent workers

GS's Dagster zombie reaper kills a run after 45 minutes with no log events, and the 3.5–4 h
rebuild gets killed on some nights, leaving an orphan collection and a two-night-old corpus.

### 3.1 The measurement to take first

203k documents in 3.5–4 h is **~14 documents/second**. Typesense documents the bulk import
endpoint as the performant path and says explicitly that "sending 10,000 documents over 10,000
different single API calls is going to be an order of magnitude more CPU intensive and slower
than sending those 10K documents in a single bulk import API call"
(https://typesense.org/docs/guide/syncing-data-into-typesense.html). Typesense's own published
benchmarks are of a system serving 104 concurrent searches/second on 4 vCPUs
(https://typesense.org/docs/overview/benchmarks.html) — 14 writes/second is not a Typesense
number. **[INFERENCE: the bottleneck is almost certainly on the producer side, not in
Typesense. The three candidates, in order of prior probability:**

- **`OFFSET`-based pagination over the source query.** OFFSET costs O(offset + page_size) per
  page while keyset/seek pagination costs O(page_size) regardless of depth
  (https://use-the-index-luke.com/no-offset). Over 203 pages of 1000, that is quadratic and
  entirely consistent with hours.
- **Per-row N+1 queries** to fetch enrichment prose or display names per foundation.
- **Single-document writes**, or `import` called with a tiny client-side chunk (Typesense's
  server-side `batch_size` defaults to 40 and the docs advise *not* changing it; client-side
  chunking is where you get throughput —
  https://typesense.org/docs/30.2/api/documents.html).

**The diagnostic is one run: time writing the JSONL to a local file, then time `curl`-ing that
file into a scratch collection. That splits producer from consumer in a single measurement and
should be done before any architecture changes.]**

### 3.2 Best practice for the job itself

- **Make the unit of work smaller than the supervisor's patience.** Dagster's documented
  mechanism is partitioned assets with a `BackfillPolicy`: `max_partitions_per_run=10` turns
  100 partitions into 10 runs, so "if one partition fails, only its batch of 10 needs to retry"
  (https://docs.dagster.io/examples/best-practices/partition-backfill-strategies;
  https://docs.dagster.io/guides/build/partitions-and-backfills/backfilling-data). A 4 h job
  split into 24 ten-minute partitions can never trip a 45-minute silence reaper, and a crash
  costs ten minutes rather than four hours.
- **Heartbeat from the ledger, not from the log.** Dagster's own run monitoring uses daemon
  heartbeats written to instance storage, detects hung run workers, honours
  `max_runtime_seconds` (also settable per job via the `dagster/max_runtime` tag) and can
  relaunch a worker up to `max_resume_run_attempts` (default 3)
  (https://docs.dagster.io/deployment/execution/run-monitoring). [INFERENCE: emitting a log
  line per batch will satisfy GS's reaper, but it is the weaker fix — it makes the job *look*
  alive rather than *be* resumable. Do both, and treat the per-batch ledger row as the real
  heartbeat, because it survives the log pipeline and answers "how far did it get?".]
- **A ledger table, keyed by batch.** The shape that follows from Debezium's chunking
  (ordered by PK, bounded by the max key at start, resume from the last recorded key —
  https://github.com/debezium/debezium-design-documents/blob/main/DDD-3.md):

  ```
  search_index_build(build_id pk, collection_name, engine, started_at, finished_at,
                     status, source_watermark, expected_doc_count)
  search_index_batch(build_id, batch_no, key_lo, key_hi, doc_count,
                     status, attempts, finished_at)
  ```

  Resume = re-run every batch not `done`. Safety = `action=upsert` keyed on the foundation id,
  which the Typesense docs define as "creates a new document or updates an existing document if
  a document with the same `id` already exists"
  (https://typesense.org/docs/30.2/api/documents.html) — so a replayed batch is a no-op.
- **Assert the import actually landed.** Because import returns 200 regardless, parse the JSONL
  response and count `{"success": true}` lines per batch; store that in the ledger as
  `doc_count` and reconcile the sum against `expected_doc_count` before the swap
  (https://typesense.org/docs/30.2/api/documents.html).
- **Keyset-paginate the source.** `WHERE (state, id) > (:last_state, :last_id) ORDER BY state,
  id LIMIT n` with a matching composite index (https://use-the-index-luke.com/no-offset). This
  also makes `key_lo`/`key_hi` in the ledger natural.
- **Sweep orphans on every start.** List collections (`GET /collections` returns names and
  `num_documents`), and drop any `foundations_*` that is neither the current alias target nor
  younger than the current build. Typesense holds indexes in RAM, so orphans are not free
  (https://typesense.org/docs/guide/system-requirements.html).

---

## 4. Multi-engine consistency (keyword in Typesense, vectors in pgvector, FTS fallback)

The generic statement of the problem: "index consistency is the property that both indexes
represent the same current corpus," which requires "a single metadata contract where chunk
identifiers, document identifiers, and access-control fields must match across both indexes so
filters behave the same way," and both indexes must be updated "in the same pipeline step to
prevent synchronisation drift"
(https://bigdataboutique.com/blog/hybrid-search-explained;
https://unstructured.io/insights/the-developers-guide-to-hybrid-search-implementation)
**[LOW-CONFIDENCE SOURCES — these are practitioner blogs; I found no authoritative treatment.
The principle is nonetheless the one every hybrid architecture converges on.]**

GS has a harder version: **three** paths (Typesense keyword, pgvector semantic,
Postgres-FTS fallback) with **two** definitions of eligibility (Typesense `filter_by` on
`foundation_code<=4 / country=US / min_assets`, and the SQL predicate
`is_active_grantmaker AND foundation_code<=4 AND country='US'` inside `match_foundations`).
Those are maintained in different repos and different languages.

**Recommendations [INFERENCE throughout, but each is cheap and testable]:**

1. **One eligibility definition, in Postgres, materialised as a column.** A generated or
   trigger-maintained `is_search_eligible boolean` on `foundations`. The Typesense indexer's
   source query filters on it; `search_foundations_keyword`, `search_foundations_semantic` and
   `match_foundations` filter on it; the reconciliation canary counts it. A change to the
   definition then lands in exactly one place, and — usefully for Lane 3 — it is also the
   column a **partial HNSW index** would be built on, which is the documented remedy for the
   filtered-KNN post-filtering wander.
2. **Also index the flag as a Typesense facet field**, so the canary can prove the two agree
   with a facet count rather than a full export.
3. **Stamp `index_build_id` (or `source_updated_at`) on every document.** It makes "find
   documents this build did not touch" answerable with one `filter_by`, which turns an in-place
   refresh into a safe operation (build, then delete everything with an older stamp) — the same
   trick Solr/Nutch-style crawl indexers use, and it removes the need for an alias swap when you
   want it to.
4. **Refuse the swap on a parity failure.** A Dagster `@asset_check(blocking=True)` that
   compares the new collection's `num_documents` and per-state facet counts to Postgres, and
   fails if the total deviates by more than a threshold, so the alias-repoint asset never
   materialises (https://docs.dagster.io/guides/test/asset-checks). This is a documented
   Dagster mechanism, not a bespoke guard. Note the threshold must be **two-sided** — an index
   that is unexpectedly *larger* than the source means the janitor is failing.
5. **Instrument the fallback path.** The fail-open-to-Postgres design means the two ranking
   paths diverge precisely when nobody is looking. Log which path served each query and alert
   on the fallback rate; a fallback rate that is quietly 100 % is exactly the "a check that
   cannot fail" shape.
6. **The honest structural answer:** three paths with two eligibility definitions is the drift
   generator. Either the vectors move into Typesense (documented support for vector fields and
   hybrid rank fusion — note the open ranking bug at
   https://github.com/typesense/typesense/issues/2163), or keyword moves back into Postgres via
   `pg_search`. Lane 4 owns that call; Lane 2's contribution is that **every consistency
   mechanism proposed above gets cheaper or disappears in the one-engine world.**

---

## 5. Freshness expectations for this data

The two corpora have genuinely different clocks — foundations change on an IRS-yearly cadence
plus continuous enrichment; gov opportunities change daily.

**The hybrid is the vendor's own documented recommendation, not an exotic invention.** The
same Typesense guide prescribes *both* nightly reindex-into-a-new-collection-and-swap-the-alias
*and* a ~30 s `updated_at` polling upsert for live data
(https://typesense.org/docs/guide/syncing-data-into-typesense.html). Algolia's guidance points
the same way from the other side: `replaceAllObjects` at most 1–3 times a month, incremental
updates in between
(https://support.algolia.com/hc/en-us/articles/38545749534865-How-often-should-I-run-replaceAllObjects).
Manticore's plain-vs-RT split is the same architecture expressed as two index types
(https://manual.manticoresearch.com/Adding_data_from_external_storages/Rotating_an_index?static=true).

**When a full rebuild is genuinely the right choice [INFERENCE, from the evidence above]:**

- The corpus fits comfortably in the rebuild window with headroom (GS: 203k docs *should* be
  minutes, not hours — see §3.1).
- Staleness up to the rebuild period is acceptable to users. For foundations, whose underlying
  IRS data moves yearly, 24 h staleness is not a product problem; for gov opportunities with
  daily close dates it is borderline.
- The transformation is not incrementally computable — e.g. a schema or analyser change, a new
  field, a re-embedding. Then you *must* rebuild, and having a working rebuild is the escape
  hatch that makes incremental sync safe to adopt.
- You want a periodic self-heal. A nightly rebuild bounds the lifetime of *any* drift to 24 h
  regardless of what the incremental path got wrong. **This is its most underrated property and
  the reason to keep it even after adopting incremental sync.**

**When CDC earns its complexity:** when the corpus is large enough that a rebuild cannot fit
in the acceptable staleness window (Notion: two weeks, then two days —
https://www.zenml.io/llmops-database/rebuilding-a-production-search-reindexing-pipeline-at-scale),
or when sub-minute freshness is a product requirement. Neither is true of GS foundations today.
It becomes true if `grants` (hundreds of thousands to millions of rows) becomes a search
surface.

---

## 6. What this implies for GS — ranked options

### Option 1 (recommended) — Keep the nightly alias swap; make it fast, resumable, and verified

Do not change the architecture. Fix the four defects that make it fragile. Ordered by
value-per-hour:

| # | Change | Why | Evidence |
|---|--------|-----|----------|
| 1 | **Measure producer vs consumer** — write JSONL to a file, then import the file — before changing anything | 14 docs/s is not a Typesense number; you may be fixing the wrong system | https://typesense.org/docs/guide/syncing-data-into-typesense.html |
| 2 | **Keyset-paginate the source query**, kill any N+1 enrichment lookup, batch the import client-side | OFFSET is O(offset+n) per page; single-doc writes are an order of magnitude slower than bulk import | https://use-the-index-luke.com/no-offset ; https://typesense.org/docs/30.2/api/documents.html |
| 3 | **Parse the import response and count successes per batch** | Import returns 200 even when every document was rejected | https://typesense.org/docs/30.2/api/documents.html |
| 4 | **Partition the rebuild into Dagster partitions under the reaper window**, with a `search_index_build` / `search_index_batch` ledger; resume re-runs only unfinished batches | Makes the reaper harmless and a crash cost minutes; the ledger is a better heartbeat than a log line | https://docs.dagster.io/examples/best-practices/partition-backfill-strategies ; https://github.com/debezium/debezium-design-documents/blob/main/DDD-3.md |
| 5 | **Blocking parity check before the swap**: total `num_documents` + per-state and per-foundation_code facet counts vs Postgres, two-sided threshold | A `@asset_check(blocking=True)` refuses to materialise the alias-repoint asset; this is the documented Dagster gate | https://docs.dagster.io/guides/test/asset-checks ; https://www.elastic.co/blog/elasticsearch-verifying-data-integrity-with-external-data-stores |
| 6 | **Stamp collection `metadata`** at creation: `build_id`, `built_at`, `source_max_updated_at`, `expected_doc_count` | Documented, persisted, returned by `GET /collections`; makes "how stale is the served corpus?" a single HTTP call, feeding the existing liveness sweep | https://typesense.org/docs/30.2/api/collections.html |
| 7 | **Orphan janitor + drain window**: on start, drop `foundations_*` that is neither the alias target nor the current build; after a swap, wait past the query timeout before deleting the old collection | Typesense keeps indexes in RAM, so orphans cost memory; in-flight queries can 404 on an eagerly deleted collection | https://typesense.org/docs/guide/system-requirements.html ; https://perun.au/insights/typesense-production **[LOW-CONFIDENCE on the 404]** |
| 8 | **Freshness alarm**: alert when `alias → collection → metadata.built_at` exceeds 36 h | A two-night-old corpus currently fails silently | (composition of 6) |
| 9 | **Negative fixture for every check above** | A parity canary never seen red is decoration; this is estate doctrine and it applies exactly here | — |

Estimated effort: days, not weeks. No new infrastructure, no new bill.

### Option 2 (recommended as the *next* step, after Option 1 is green) — Add a watermark upsert lane on top

Nightly rebuild stays as the self-heal; a 1–5 minute polling loop carries the delta. This is
literally the Typesense-documented pair.

- Source the scan from the **base** `foundations` table, not the eligible view, and decide
  per row: upsert if eligible, `filter_by=id:[...]` delete if not. This is what catches
  eligibility flips, the case that a naive design misses forever.
- Gate the watermark with `transaction_id < pg_snapshot_xmin(pg_current_snapshot())` (add an
  `xid8` column), or, if that is too invasive, use a generous overlap window — upserts are
  idempotent, so overlap costs only throughput
  (https://event-driven.io/en/ordering_in_postgres_outbox/).
- Maintain `updated_at` with a **trigger**, never in application code.
- Give bulk backfills an opt-out so a 300k-row `display_name` sweep does not stampede the
  syncer; let the nightly rebuild absorb them
  (https://typesense.org/docs/guide/syncing-data-into-typesense.html on 503 backpressure).
- Gov opportunities (9k docs, daily close dates) should get this lane *first* — the corpus is
  small enough that even a full hourly rebuild is a rounding error.

### Option 3 — Upgrade the watermark to a trigger-based outbox

`AFTER INSERT OR UPDATE OR DELETE ON foundations` → `search_outbox(id, op, xid8, changed_at)`,
drained with `FOR UPDATE SKIP LOCKED`. Strictly more correct than Option 2 (captures hard
deletes, cannot be bypassed by a forgetful writer) at maybe a day more work and some write
amplification (https://blog.sequinstream.com/all-the-ways-to-capture-changes-in-postgres/).
Do this if Option 2 shows real drift; do it immediately if hard deletes on `foundations` are
ever a thing.

### Option 4 (not recommended now) — CDC via logical decoding

Debezium Server with an HTTP sink into Typesense is technically feasible on Railway with no
Kafka (https://debezium.io/documentation/reference/stable/operations/debezium-server.html).
Reasons to decline today:

- Neon compute cannot scale to zero while a subscriber is connected
  (https://neon.com/docs/guides/logical-replication-neon), floor ~$19.87/month on Launch at
  0.25 CU (https://neon.com/pricing) — ~40 % of the Neon budget for a mechanism whose product
  benefit over Option 2 is seconds-vs-minutes on a corpus that changes yearly. **[Caveat: if
  Dagster already keeps the compute awake continuously, the marginal cost is ~0. Measure before
  deciding.]**
- Neon drops replication slots after ~40 h without progress, so an outage over a long weekend
  silently ends replication (https://neon.com/docs/guides/logical-replication-neon).
- An unconsumed slot retains WAL until the database stops accepting writes
  (https://blog.peerdb.io/overcoming-pitfalls-of-postgres-logical-decoding). This is the
  highest-severity new failure mode GS would be adopting, and it lands on the production
  database rather than on the search box.
- A new JVM container to operate, on an estate that is deliberately shoestring.

Revisit when `grants` becomes a search surface, or if AG's product genuinely needs sub-minute
foundation freshness.

### Option 5 (Lane 4's call, noted here) — Delete the sync problem

`pg_search` / a single engine removes reconciliation, alias swaps, orphan janitors, parity
canaries and the fallback-divergence problem in one move, because the index is maintained in
the writing transaction (https://docs.paradedb.com/welcome/introduction). Everything in
Options 1–3 is work that a one-engine architecture would not need. That is not an argument to
do it — it is an argument to **not build more sync machinery than Option 1 requires** until
Lane 4 has ruled.

---

## 7. Things I could not establish

- **No documented standard exists for "refuse the alias swap if counts differ by more than
  x %."** Everyone describes verifying counts (GOV.UK, GitLab, Notion, Elastic) but the
  abort-threshold guard appears to be universally bespoke. Algolia's `safe` parameter is the
  nearest packaged analogue, and it only orders the operations, it does not validate
  (https://support.algolia.com/hc/en-us/articles/12035248850833-Should-I-use-the-safe-parameter-with-replaceAllObjects).
- **No open-source Postgres↔Typesense reconciliation tool** exists that I can find. PGSync is
  Elasticsearch/OpenSearch only.
- **Typesense has no document versioning** (no `version_type: external` equivalent), so the
  Notion-style "swap first, then reconcile a catch-up index with conflicts:proceed" pattern
  does not port directly. **[INFERENCE: the workaround is that a catch-up which re-reads
  current state from Postgres and upserts is naturally last-write-wins-correct, provided it
  runs strictly after the swap and never replays a stale buffer.]**
- **Typesense's exact behaviour on deleting a collection with queries in flight** is only
  attested by a secondary source; I did not find it in the official docs or a tracked issue.
- **The 3.5–4 h rebuild's actual bottleneck** is unmeasured. Everything in §3.1 is inference
  from the throughput number and Typesense's documented performance guidance.

---

## 8. Source provenance note

`debezium.io` returns HTTP 403 to automated fetching. The three `debezium.io` URLs cited
(`/blog/2021/10/07/incremental-snapshots/`, `/documentation/reference/stable/connectors/postgresql.html`,
`/documentation/reference/stable/transformations/outbox-event-router.html`,
`/documentation/reference/stable/operations/debezium-server.html`) were surfaced by search
results and their content corroborated through the fetched
`github.com/debezium/debezium-design-documents/blob/main/DDD-3.md`, which I did read in full.
Treat the Debezium URLs as citations to be spot-checked in a browser rather than as pages I
personally rendered.

`elastic.co/docs/reference/.../reindex-indices` and both `elastic.co` blog posts, the Neon
docs and pricing pages, the Typesense docs pages, the Meilisearch tasks reference, the
Searchkick repo, the Notion case study, the GOV.UK runbook, the Morling post and the
event-driven.io post were all fetched and read directly.

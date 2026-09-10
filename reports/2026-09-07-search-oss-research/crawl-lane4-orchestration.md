# CRAWL LANE 4 — Orchestrating and supervising long-running crawls
### One container, Postgres frontier, strict compute budget

Research date: 2026-09-07. Target: GrantSpider (Dagster on one Railway container, Neon Postgres,
SQLAlchemy/Alembic, B2 for bodies, ~$50/mo Neon budget, 12h daily work window).

Every claim is tagged **[DOC]** (vendor/primary documentation or source), **[REPORT]**
(practitioner blog, benchmark, issue thread — credible but not authoritative), or
**[INFER]** (my reasoning, not sourced).

---

## 0. The three findings that matter most

1. **Dagster's crash detection does not work for GrantSpider.** "Detecting run worker crashes
   only works when using a run launcher other than the `DefaultRunLauncher`" **[DOC]**, and
   resume-after-crash is limited to `K8sRunLauncher`+`k8s_job_executor` and
   `DockerRunLauncher`+`docker_executor` **[DOC]**. GS runs `DefaultRunLauncher`, so of the
   run-monitoring feature set it gets only `start_timeout_seconds`, `cancel_timeout_seconds`,
   `max_runtime_seconds` and `free_slots_after_run_end_seconds` — *not* zombie-worker restart.
   GS's own 45-minute event-log-silence sensor is therefore not redundant with `run_monitoring`;
   it is the only zombie detector GS has. **[INFER]**
2. **Railway's healthcheck is not a liveness probe.** "The healthcheck endpoint is currently not
   used for continuous monitoring as it is only called at the start of the deployment" **[DOC]**,
   and the default restart policy is ON_FAILURE with max 10 restarts **[DOC]** — it fires only on
   a non-zero exit. A hung (not crashed) daemon is never restarted by Railway. This is exactly
   the GS#1545 failure mode and confirms the standing memory note. The external watchdog is
   load-bearing, not belt-and-braces.
3. **Neon does not actually reach zero.** Neon's control plane runs a periodic
   `check_availability` ping that wakes the compute ~30–40×/day and resets the idle timer,
   producing a floor of roughly 0.25 CU × 24 h ≈ 6 CU/day regardless of traffic **[REPORT —
   community discussion + respondent, not official docs]**. At Launch-plan $0.106/CU-hour
   **[DOC]** that is ~$0.64/day ≈ $19/mo *per project* as a floor. Consequence for GS: **batching
   writes to let Neon autosuspend has a hard ceiling on how much it can save.** The lever that
   still pays is *autoscaling headroom* (keeping the compute at 0.25 CU rather than scaling up)
   and *fewer, larger transactions*, not "let it sleep".

---

## 1. Queue library comparison table

| Library | Lang | License | Postgres-native? | Claim mechanism | Lease / stall recovery | SQLAlchemy fit | Activity / notes |
|---|---|---|---|---|---|---|---|
| **procrastinate** | Python | MIT **[DOC]** | Yes — PG 13+, LISTEN/NOTIFY + SKIP LOCKED **[DOC]** | SQL function, SKIP LOCKED | **Best in class**: workers write a heartbeat every 10 s (default); `JobManager.get_stalled_jobs()` + built-in `retry_stalled_jobs` task, default 30 s since heartbeat, tunable via `seconds_since_heartbeat` / `update_heartbeat_interval` / `stalled_worker_timeout` **[DOC]** | **Direct**: ships `SQLAlchemyPsycopg2Connector` "if you want to use SQLAlchemy to manage your database connection and share your connection pool with the rest of your app" **[DOC]** | ~1.4k stars, 3.5k commits; project is openly "seeking additional maintainers" **[DOC]** — a real risk flag |
| **pgqueuer** | Python | MIT (PyPI) | Yes — PG 13+, LISTEN/NOTIFY + `FOR UPDATE SKIP LOCKED` **[DOC]** | SKIP LOCKED, per-entrypoint concurrency limits **[DOC]** | `heartbeat_timeout` on `pgq.run()`, default 30 s (replaced per-entrypoint `retry_timer`) **[DOC]** | Drivers: asyncpg, psycopg (async+sync), psycopg2 **[DOC]** — you'd hand it a DSN, not a Session. Coexists with SQLAlchemy rather than integrating | Active; Prometheus metrics, tracing, live dashboard, cron scheduling, in-memory test mode **[DOC]** |
| **pgmq** | SQL extension | PostgreSQL licence (pgxn) | Yes — it *is* an extension | `read()` with visibility timeout (SQS semantics) **[DOC]** | Visibility timeout only: unacked message reappears. **No per-job retry counter, no scheduling, no DLQ** **[REPORT — benchmark harness]** | N/A — call `pgmq.send/read/delete` via `text()` | v1.11.1 released 2026-04-19 **[DOC]**. **Requires installing an extension** — a blocker if Neon doesn't offer it on your plan; verify before designing around it |
| **pg-boss** | Node.js | MIT | Yes — own `pgboss` schema; v10 uses declarative list partitioning on the `job` table, plus archive + retention pruning **[DOC]** | SKIP LOCKED | Retry limits (default 2, opt-out since v10) **[DOC]** | None (Node) — **reference design only** | Mature; the partitioned-job-table design is the single best idea to steal |
| **graphile-worker** | Node.js | MIT | Yes | SKIP LOCKED, `locked_at`/`locked_by`, `is_available` generated column **[DOC]** | **Weak**: a worker sweeps for jobs locked >4 hours, every 8–10 min. "Graphile Worker cannot be sure that a job is crashed until the 4 hour window has expired" **[DOC]** | None (Node) — **reference design only, and a cautionary one** | Docs explicitly say "Database tables are not a public interface!" **[DOC]** — the fixed 4 h lease is the anti-pattern to avoid |
| **River** | Go | MPL-2.0 | Yes | SKIP LOCKED; transactional enqueue with app data **[DOC]** | Leader election for periodic jobs; unique jobs by args/period/queue/state **[DOC]** | None (Go) — **reference design only** | Best-articulated design rationale (brandur.org/river). Recovered from *every* chaos scenario in the independent benchmark **[REPORT]** |
| **Celery + SQLAlchemy broker** | Python | BSD | Kombu `sqlalchemy` transport | Polling | — | Uses SQLAlchemy, but as a transport | **Bad fit.** Transport does not support remote control commands or events (no Flower, no Django admin monitor) **[DOC]**; experimental brokers "don't have dedicated maintainers" **[DOC]** |
| **Dramatiq + dramatiq-pg** | Python | LGPL-3 (Dalibo) | Yes — single table, JSONB payload, LISTEN/NOTIFY, auto-purge **[DOC]** | — | "automatic recovery after crash" claimed **[DOC]** | Independent of SQLAlchemy | Dalibo original + a `danielgatis` fork updated for Dramatiq 2.0/Py3.10+ **[DOC]**. Fork-of-fork situation = maintenance risk |
| **Huey** | Python | MIT | **No first-class Postgres backend found** in this sweep (SQLite/Redis are its homes) | — | — | — | **Bad fit** for a Postgres frontier |
| **pgque** | SQL/ext | — | Yes | Append-only event log, consumer-group cursors **[REPORT]** | Different contract (event bus) | — | Fastest in benchmark (39.9k jobs/s) but it is **not a job queue** |

### Independent benchmark, 2026-05-09 sweep **[REPORT — hardbyte/postgresql-job-queue-benchmarking]**

Peak clean throughput: pgque 39,898/s (event bus) · awa 14,158/s · pgmq 11,277/s ·
pg-boss 2,387/s · river 501/s · absurd 410/s · oban 284/s · **procrastinate 269/s**.

Chaos recovery: only awa, pgque and river recovered from *every* scenario. Sustained pressure:
only awa, oban and pgque completed all tests; pg-boss, river, absurd and procrastinate timed
out. pgmq showed an "active-readers cliff" and **anti-scaled past 16 workers**.

**Reading for GS [INFER]:** procrastinate's 269 jobs/s looks alarming until you price GS's actual
rate. At 5 s/host politeness and 24-way cross-domain concurrency, the *fetch* ceiling is ~4.8
URLs/s — roughly **1.8% of procrastinate's slowest measured throughput**. Queue throughput is not
GS's constraint and should not drive the choice. Durability, stall recovery and operational
legibility should. The benchmark's *chaos* column is the relevant one, and it is uncomfortable
for procrastinate.

---

## 2. Postgres as a work queue

### 2.1 The canonical claim

The universally-cited form is a CTE that selects with `FOR UPDATE SKIP LOCKED` and an `UPDATE …
FROM` that stamps the claim, returning the rows — one statement, one transaction **[DOC/REPORT,
many sources]**:

```sql
WITH claimed AS (
  SELECT id FROM frontier
  WHERE status = 'pending' AND next_eligible_at <= now()
  ORDER BY priority DESC, next_eligible_at
  LIMIT :batch
  FOR UPDATE SKIP LOCKED
)
UPDATE frontier f
   SET status='fetching', claimed_by=:worker, claimed_at=now(),
       lease_expires_at = now() + :lease, claim_token = gen_random_uuid(),
       attempts = attempts + 1
  FROM claimed c WHERE f.id = c.id
RETURNING f.*;
```

`SKIP LOCKED` has been in Postgres since 9.5 and exists for exactly this **[DOC]**.

### 2.2 Lease, heartbeat, claim token

Three separate mechanisms, often conflated **[DOC/REPORT]**:

- **Row lock** — lives only for the claiming transaction. If the worker crashes *mid-transaction*
  the lock releases and the row reverts. Free, but only covers the claim itself.
- **Lease (`lease_expires_at`)** — survives the transaction. A reaper returns rows whose lease has
  expired. Simple; the whole design hinges on picking the timeout.
- **Heartbeat (`heartbeat_at`, refreshed every N s)** — lets the lease be *short* without killing
  long jobs. Rule of thumb from the stall-detection literature: **`stale_timeout >= 3 ×
  heartbeat_interval`**, so a single missed beat doesn't trigger recovery **[REPORT]**.
  procrastinate uses 10 s beat / 30 s stall **[DOC]**; pgqueuer defaults to 30 s **[DOC]**.

**Claim token.** A stale worker that wakes up after its lease was reaped must not be able to
finalise a job it no longer owns. Carry a `claim_token` (uuid) in the claim and require it in the
completion `UPDATE … WHERE claim_token = :token` **[REPORT]**. Without it, a laptop resuming from
suspend can overwrite work another worker has since done. **This is directly relevant to GS's
WSL2-suspend failure mode.** **[INFER]**

**Anti-pattern to avoid: graphile-worker's fixed 4-hour stale-lock sweep** **[DOC]**. It is the
"lease with no heartbeat" design, and it means a crashed crawl sits invisible for four hours.

### 2.3 Index shape for a hot queue table

- One **partial index** on the claim predicate: `CREATE INDEX … ON frontier (priority DESC,
  next_eligible_at) WHERE status='pending'` **[DOC — PlanetScale]**. The partial predicate keeps
  the index proportional to the *ready* set, not the corpus.
- **Do not index high-churn columns** you don't need for the claim **[REPORT]**. Every indexed
  column that an `UPDATE` touches defeats HOT.
- **HOT (heap-only tuple) updates**: if an update changes no indexed column *and* there is room on
  the page, Postgres updates in place without touching any index — "HOT updates dramatically
  reduce both table and index bloat" **[REPORT]**. Pair with **`fillfactor ≈ 85`** on the queue
  table so pages retain room **[REPORT]**.
- The tension is real: `status` must be indexed (for the partial predicate) *and* is the hottest
  column. That is precisely why the partial index "gets thrashed especially hard, since rows
  constantly enter and leave that condition" **[REPORT]**. **[INFER]** The escape is to make the
  hot table small — see 2.5.

### 2.4 Bloat and vacuum under churn

- Dead tuples accumulate faster than autovacuum clears them; tables reach tens of GB with minimal
  live data **[REPORT]**.
- Tune `autovacuum_vacuum_scale_factor` **per hot table (0.01–0.05)**, never globally **[REPORT]**.
- Long-running *readers elsewhere in the database* hold back the MVCC horizon and stop vacuum from
  reclaiming queue tuples at all. PlanetScale measured: 800 jobs/s with an unconstrained analytics
  workload → 383,000 dead tuples and >300 ms lock times; with the competing workload's concurrency
  capped → 0–23,000 dead tuples and ~2 ms lock times **[REPORT]**. **The queue's health is decided
  by what *else* runs on the instance.** Relevant to GS: the enrichment/analytics queries against
  the same Neon branch are a bloat multiplier for the frontier. **[INFER]**
- Contention modes at high worker counts: `LWLock:MultiXactMemberSLRU` /
  `MultiXactOffsetSLRU` from many concurrent lockers, `ProcArrayLock`, "every lock/unlock is a
  full WAL-logged transaction", and `SKIP LOCKED` still *scanning* locked rows **[REPORT]**.
  **[INFER]** At GS's ~5 claims/s across ≤24 workers none of these bite; recording them so nobody
  re-litigates at 10× scale.

### 2.5 The two structural fixes worth more than any tuning

- **Keep the hot set in a small table.** "Keep list of entries to process duplicated in a separate
  tiny table … in that case autovacuum will be able quickly clean dead entries from the index"
  **[REPORT]**. A `frontier_ready` table of ~10⁵ rows refilled from `mine_urls` (10⁷+) vacuums in
  seconds; a partial index over the whole `mine_urls` table does not. **[INFER]**
- **Partition and drop, don't delete.** pg-boss v10 moved to declarative list partitioning with
  retention pruning of old partitions **[DOC]**. `DROP PARTITION` produces zero dead tuples;
  `DELETE` of a month of history produces millions.

---

## 3. Dagster patterns for crawls

### 3.1 Run monitoring — what GS actually gets

`dagster.yaml` defaults **[DOC]**:

```yaml
run_monitoring:
  enabled: true
  start_timeout_seconds: 180
  cancel_timeout_seconds: 180
  max_resume_run_attempts: 3      # inert on DefaultRunLauncher
  poll_interval_seconds: 120
  free_slots_after_run_end_seconds: 300
  max_runtime_seconds: <optional>
```

- `max_runtime_seconds` globally, or the **`dagster/max_runtime` tag per run — the tag value must
  be a string** **[DOC]**, and run monitoring must be enabled or the tag silently does nothing
  **[DOC]**. There is an open issue of users unable to make the tag work at all (dagster#21813)
  **[DOC — issue]**. **Treat `max_runtime` as unverified until GS has seen it fail a run on
  purpose.** A timeout that has never been observed timing out is a decoration.
- `poll_interval_seconds: 120` sets the *detection granularity*: nothing is noticed faster than
  ~2 minutes **[DOC]**.
- `free_slots_after_run_end_seconds: 300` exists because ended runs otherwise leave concurrency
  slots pinned **[DOC]** — worth setting explicitly if GS uses `dagster/concurrency_key`.
- **`max_resume_run_attempts` is dead config under `DefaultRunLauncher`** **[DOC]**. Leaving it in
  `dagster.yaml` reads as protection that does not exist. **[INFER]**

### 3.2 Run isolation on one container

`DefaultRunLauncher` "spawns a new process in the same node as a job's code location" **[DOC]** —
subprocesses, no cgroup, no memory cap. Dagster's own docs warn that "a non-isolated run that
exhausts the code location server's resources can crash the server and disrupt other processes"
**[DOC]**. `DockerRunLauncher` supports `container_kwargs` for per-run memory limits **[DOC]**.

**[INFER] Options for GS, cheapest first:**
1. Do nothing structural; cap risk in-process (`RLIMIT_AS` via `resource.setrlimit` in the run
   worker's entry, plus the existing 200 MB body cap). Zero infra change.
2. Run docker-in-docker on Railway for `DockerRunLauncher` — almost certainly not worth it on a
   single shoestring container.
3. Systemd-style cgroup limits are unavailable inside a Railway container.
   → **Recommendation: (1).** The realistic OOM source for a crawler is a single huge response or
   a runaway parse, and those are better bounded at the fetch layer than by the launcher.

### 3.3 Partitioned assets vs one long op

- Backfill shapes: default one-run-per-partition, a batched approach, or single-run via
  `BackfillPolicy`, "each with distinct trade-offs in terms of overhead, fault isolation, and
  resource utilization" **[DOC]**.
- `DynamicPartitionsDefinition` with `instance.add_dynamic_partitions` /
  `SensorResult(dynamic_partitions_requests=…)` — and returning *only*
  `dynamic_partitions_requests` adds partitions **without launching runs** **[DOC]**.
- Sensors can currently only yield disconnected partitioned runs or single-run backfills, not
  multi-run backfill requests (dagster#27759) **[DOC — issue]**.

**[INFER] For a 300k-foundation crawl, do not model foundations as partitions.** Dynamic
partitions are per-key metadata in Dagster's own event log; 300k keys makes the Dagster instance
DB the bottleneck and the UI unusable, and the frontier already lives in Postgres where it can be
indexed and prioritised properly. The right shape is:

- **Coarse partitions for accounting** (a daily time partition, or a bucket partition of ~50–200
  keys) so the UI shows progress and backfills are resumable at a useful granularity;
- **A batched op inside each run** that claims N rows from the Postgres frontier, processes them,
  commits, and loops until its budget (wall-clock or row-count) is spent;
- **Idempotence carried by the frontier, not by Dagster.** A re-run claims whatever is still
  pending. That satisfies "manually launchable in-session, idempotent, DB-resumable" without
  Dagster having to know anything about resumption.

### 3.4 Sensors vs schedules

Practitioner report of five Dagster production failure patterns **[REPORT — perun.au]**, of which
three apply directly:

- **Sensor daemon blocking** — a sensor doing synchronous external I/O without a timeout stalls
  the daemon's *sequential* tick loop and every other sensor with it. Fix: explicit timeouts on
  all I/O in sensor bodies, return `SkipReason` on timeout, alert when tick latency exceeds 2×
  the tick interval. **GS's zombie-reaper sensor queries Postgres; if Neon is cold-starting or
  the connection hangs, the sensor that exists to detect hangs is itself the hang.** **[INFER]**
- **Backfill resource contention** — a backfill saturating shared concurrency starves scheduled
  runs. Fix: distinct `concurrency_key` for backfill vs live, priority tags, off-peak scheduling.
- **Daemon single-process crash** — no active/passive replication; one daemon crash halts queueing,
  sensors and schedules indefinitely. Fix (their words) is a K8s liveness probe. **On Railway
  there is no liveness probe (§4), so this is precisely the gap GS's external watchdog fills.**

`QueuedRunCoordinator`: `max_concurrent_runs` default 10; `tag_concurrency_limits` apply **at job
granularity only** — for op/asset-level limits inside one job use `multiprocess_executor`'s own
`tag_concurrency_limits` **[DOC]**.

### 3.5 How other people run crawlers under orchestrators

Honest answer: **there is no well-documented public case study of a large crawl run as
orchestrator-native tasks.** What the search surfaced instead:

- Airflow's answer to long waits is **deferrable operators** — offload polling to the triggerer and
  release the worker slot **[DOC]**. That is the shape for "wait on an external system", not for
  "do a multi-day fetch".
- Prefect's answer is **background/deferred tasks on a task server** **[DOC]** — again, work moved
  *out* of the flow.
- Scrapy's own answer is `JOBDIR`: an on-disk persistent scheduler + dupefilter + spider state, so
  a crawl can be stopped and resumed with the same command **[DOC]** — with the caveats that the
  dir must not be shared between spiders or jobs, requests must be picklable, and there is an open
  issue that persistence is *not fully* persistent (scrapy#4106) **[DOC — issue]**.
- StormCrawler treats the crawl as a **continuous stream** on Storm, with state in Elasticsearch
  and status-count dashboards in Kibana **[DOC]**; Nutch is batch and "can slow down as the crawl
  grows" **[REPORT]**.

**[INFER] The convergent lesson:** every serious crawler keeps its frontier and its resume state
in *its own* store and treats the orchestrator as a launcher. GS's existing shape (Postgres
frontier + Dagster as launcher) is the mainstream design, not a workaround. The gap is not the
orchestrator — it is that the frontier has no lease (GS#1777).

---

## 4. Watchdog design

### 4.1 What Railway does and does not do

| Mechanism | Behaviour | Covers a hung daemon? |
|---|---|---|
| Healthcheck path | "only called at the start of the deployment, to ensure it is healthy prior to routing traffic" **[DOC]**; default timeout 300 s **[DOC]** | **No** |
| Restart policy ON_FAILURE (default, max 10) | Restarts only on non-zero exit **[DOC]** | **No** |
| `serviceInstanceRedeploy` GraphQL mutation at `https://backboard.railway.com/graphql/v2` **[DOC]**, or `railway restart` CLI (restarts without rebuilding, reuses the image) **[DOC]** | Programmatic restart | **Yes — if something calls it** |

So the watchdog chain must be: *something outside the container observes a heartbeat, and calls
`serviceInstanceRedeploy` when it goes stale.*

### 4.2 The heartbeat substrate — three choices

| Substrate | Survives container death? | Readable off-box? | Cost | Verdict |
|---|---|---|---|---|
| **Heartbeat file** on the container FS | No — dies with the container | No | 0 | Useless for this purpose **[INFER]** |
| **DB row** (`crawl_heartbeat`) | Yes | Yes, but the reader needs Neon creds and **wakes the compute** | Adds Neon active-time (§5) | Good for *in-app* checks, poor for the outer watchdog **[INFER]** |
| **Outbound ping to a dead-man's-switch service** | Yes | Yes | Free tier | **Correct substrate for the outer ring** |

Dead-man's-switch options:

- **healthchecks.io** — open source, self-hostable, free tier 20 checks, $20/mo hosted; understands
  cron and systemd `OnCalendar` schedules with timezones, and records **job duration, exit codes
  and captured output** **[DOC/REPORT]**. Self-hosting needs Docker/Python + Postgres + a mail
  server **[REPORT]**.
- **Sentry Crons** — `in_progress` / `ok` / `error` check-ins with `max_runtime` and
  `checkin_margin`; the Python SDK's `with sentry_sdk.monitor(monitor_slug=…)` context manager
  sends all three automatically **[DOC]**. Pricing: 1 monitor free, then $0.78/monitor/month
  **[REPORT]**. No self-hosted equivalent **[REPORT]**. Known SDK issue: the `in_progress`
  check-in is sometimes dropped, producing a spurious failure that the later `ok` resolves
  (sentry-python#3279) **[DOC — issue]**.
- **Uptime Kuma** — self-hosted, has *push* monitors ("something checks in every N minutes, tell me
  when it stops") but no cron/timezone semantics, no duration, no exit codes, no captured output
  **[REPORT]**.

**[INFER] Recommendation for GS: Sentry Crons.** GS already has `SENTRY_API_TOKEN` and a triage
sweep that drives Sentry to inbox zero; a missed crawl heartbeat then lands in a queue the estate
already drains every session, at $0.78/month, with no new service to keep alive. healthchecks.io
is the better *product* (captured output and exit codes are genuinely useful) but it adds a
service, and self-hosting it recreates the who-watches-the-watchdog problem one level down.

### 4.3 The chain, and where it terminates

The literature's framing: a watchdog is "a liveness detector that answers a simple question: is
the system still making forward progress?" **[REPORT]**, and the standard resolution of
who-watches-the-watchdog is that **the outermost ring must be a party that is not you** — a
background task rewrites a liveness beat, and "when the beat goes stale, it pushes an out-of-band
alert that survives the agent dying because it isn't the agent" **[REPORT]**. `watchdogd` and
systemd's `WatchdogSec` are the canonical in-host forms **[DOC]**.

**Proposed chain for GS (4 rings, each ring watched by the next):**

```
Ring 0  crawl op            → refreshes frontier lease heartbeat every 30 s (in-DB)
Ring 1  reaper sensor       → returns rows with expired leases; Dagster restarts the work
Ring 2  daemon watchdog     → observes Dagster daemon heartbeat + event-log silence;
        (in container)        calls Railway serviceInstanceRedeploy on stale
Ring 3  Sentry Cron         → the container pings "crawl alive" every 15 min from a thread
        (off box)             that is NOT the crawl loop; missing ping = Sentry issue
                              = next session's sentry-triage sweep
```

Ring 3 is the terminator: it is off-box, it is not code GS runs, and its failure mode (Sentry
down) is loud rather than silent. **[INFER]**

### 4.4 Debouncing restarts

Nothing authoritative surfaced on restart debouncing for this exact shape, so **[INFER]**:

- **Require two consecutive stale observations** before restarting. With Dagster's 120 s poll and
  a 15-minute Sentry period, one missed beat during a Neon cold start is normal.
- **Exponential backoff with a cap**: 1st restart immediate, 2nd after 10 min, 3rd after 30 min,
  then stop restarting and only alert. Railway's own ON_FAILURE policy caps at 10 restarts
  **[DOC]** — mirror the idea, don't fight it.
- **Persist the restart count outside the container** (a Sentry tag, or a Neon row written *before*
  the restart), or the counter resets on every restart and the loop is unbounded.
- **A restart must be recorded, not silent.** A watchdog that quietly fixes things every night is
  indistinguishable from a healthy system — the estate's own inert-controls rule.
- **The watchdog must prove it can alert.** A synthetic "force a stale heartbeat" path, exercised
  on a schedule, is the only thing that distinguishes "nothing went wrong" from "the watchdog is
  dead". Silence is its failure mode.

---

## 5. Checkpointing and resumability for multi-day drains

### 5.1 Delivery semantics

Object-store/event pipelines are **at-least-once**; "your function may receive the same event
multiple times. Idempotency keys are the standard solution: check before processing, skip if
already seen" **[REPORT]**. Content-addressed storage makes this free: "every data object is
identified by a unique identifier derived from its content … identical content always produces the
same hash … making deduplication a direct product of how addressing works" **[REPORT]**.

**[INFER] GS is already in the good position here.** Markdown bodies are hash-addressed in B2, so a
duplicate fetch is a no-op write of identical bytes. Exactly-once is unnecessary and expensive;
**at-least-once + hash addressing is exactly-once in effect** for the artifact, and the only thing
needing idempotence is the *stamping* (`markdown_b2_key`, `markdown_snapshot_at`), which is a
last-writer-wins UPDATE and is naturally idempotent.

The one hole: **B2 write succeeds, Neon stamp fails.** Then the object exists and the row says
unfetched, so the next pass re-fetches the live site — a wasted HTTP request, not corruption.
Order the operations B2-then-stamp (never the reverse) and this is the only failure mode, and it
is benign. **[INFER]**

### 5.2 Batch-level commits and the ledger

The design principle from the crawling-at-scale writeups: **"a properly designed crawling pipeline
should be idempotent at every layer — re-running a stage must never corrupt the layers below"**,
and a **crawl manifest keyed by URL with last-fetched time and content hash** drives re-crawl
decisions **[REPORT]**.

**[INFER] Concrete shape for GS:**

- Commit the Neon stamp **once per batch of N URLs** (N ≈ 200–500), not per URL. One transaction,
  one WAL flush, one Neon wake.
- Between batches, keep results in a **local SQLite ledger in WAL mode** — SQLite's WAL mode
  "batches syncs" and gives non-blocking writes **[REPORT]** — so a mid-batch crash loses at most
  N URLs of *stamping*, and zero fetched bytes (they're already in B2).
- On restart, the resume path is: replay the local ledger's unstamped rows into Neon, *then* claim
  new work. This makes the drain resumable without Neon knowing anything mid-batch. This is the
  Nathan design ruling on GS#2384 (manifest pull, local ledger, batched upsert) — the research
  supports it.

### 5.3 Laptop sleep / WSL2 suspend

Documented estate fact: in-session drains halt when the laptop sleeps, with no completion
notification. **[INFER] Three specific consequences and mitigations:**

1. **A suspended worker still holds its lease.** On wake, its `lease_expires_at` is long past and
   the reaper has reissued the rows. Without a **claim token**, the woken worker will happily
   stamp rows another worker has since fetched. → Claim token is not optional for GS.
2. **The lease timeout must be tuned to fetch time, not sleep time.** Don't set an 8-hour lease to
   "survive" overnight sleep; set it to ~3× the p99 batch duration and accept that a sleeping
   worker's rows get reissued. Reissue is cheap (a re-fetch); a stuck row is expensive.
3. **On wake, a worker should self-check before doing anything**: if `now() > lease_expires_at`,
   flush the local ledger for rows it still owns by token, drop the rest, and re-claim. A
   monotonic-clock check (`time.monotonic()` jump vs wall clock) detects the suspend cheaply.

---

## 6. Compute-budget shaping

### 6.1 The Neon floor

- Scale-to-zero after a configurable idle period, **default 5 minutes**; resume in a few hundred ms
  **[DOC]**. Compute billed at **$0.106/CU-hour on Launch**; 1 CU = 1 vCPU + 4 GB **[DOC]**.
  Storage metered separately at $0.35/GB-month **[DOC]**.
- **But**: control-plane `check_availability` pings wake the compute ~30–40×/day and reset the
  idle timer, so a low-traffic project still burns ≈6 CU/day ≈ $19/mo **[REPORT — community
  discussion, Neon staff/respondent answer, *not* official documentation]**. Neon's suggested
  mitigations were consolidating projects into one database with schema separation, or accepting
  the floor **[REPORT]**.
- Neon's docs note write operations "grow into a log (delta) over time and count toward your
  storage usage" **[DOC]** — so churn costs storage even when it doesn't cost compute.

**[INFER] What this means for GS's $50/mo target:**
- Batching writes to enable autosuspend has a *bounded* payoff (~$19/mo floor per project). It is
  worth doing, but it is not the lever that gets to $50.
- The larger levers are: (a) **stay at 0.25 CU** — autoscaling up is what actually multiplies the
  bill, so keep the frontier's working set indexed and small enough that no query provokes a scale
  up; (b) **fewer projects/branches**, since the floor is per-project; (c) **keep churn off Neon**
  — the local SQLite ledger avoids both compute *and* the delta-log storage growth.
- **Measure, don't assume.** Neon's Monitoring page distinguishes ALLOCATED CU from ENDPOINT
  INACTIVE **[REPORT]**; a per-run measurement of CU-hours consumed is the only way to know
  whether the 12-hour work window is actually buying idle. **[INFER]** Record CU-hours per drain
  in the drain's own report, so a regression in batching is visible as a cost regression.

### 6.2 Work windows

**[INFER]** The 12:00–23:59 UTC window helps only if *nothing else* touches Neon in the other 12
hours. One Dagster sensor polling the instance DB every 30 s keeps the compute awake all night and
silently voids the window. Audit: which processes touch Neon outside the window, and can the
Dagster instance storage live somewhere other than the Neon branch the crawl uses? (Dagster's own
event log is a continuous writer by design.) This is the single most likely reason a work window
underdelivers.

---

## 7. Observability for crawlers

### 7.1 What the established crawlers give you

- **StormCrawler**: URL status + content in Elasticsearch, Storm metrics into `metrics*` indices,
  Kibana dashboards, and specifically **"a visualization for Kibana which gives an instant
  breakdown of the number of URLs per status"** **[DOC]**. Per-status counts were a deliberate
  feature request (storm-crawler#389) **[DOC — issue]**.
- **Heritrix**: ships a web frontend for monitoring and configuring crawls **[REPORT]**.
- **Nutch**: batch-step oriented; monitoring is per-step **[REPORT]**.

**[INFER] The common denominator is a status × host breakdown, live.** That is the minimum GS
should expose: for each host, counts of `queued / fetching / fetched / empty / blocked / error`,
plus median time-in-`fetching`. GS's `mine_urls` already carries the fields; what's missing is the
rollup view and the alarm on it.

### 7.2 Trap detection

Documented heuristics:

- **Trap families**: dynamic URL parameters, infinite calendar pagination, session-ID URLs,
  filter/sort combinations, symlink loops — "each one causes a crawler to generate or follow an
  unbounded number of unique URLs" **[REPORT]**. Archive-It publishes an operator-level guide to
  identifying and avoiding them **[DOC]**.
- **Fingerprint collapse**: BUbiNG computes a hash over *summarised* content — HTML attributes
  stripped, digits and dates discarded — "this simple heuristic allows for instance to collapse
  pages that differ just for visitor counters or calendars" **[DOC — BUbiNG paper]**.
- **Depth-vs-similarity**: compare SimHash fingerprints of pages at increasing depths; in a trap,
  depth-15 and depth-50 pages are near-identical (same template, different parameters) **[REPORT]**.
- Google's crawler patents use a **de-tagged fingerprint keyed by host hash** as the dedup
  structure **[DOC — US7627613B1]**; Charikar's technique for finding f-bit fingerprints differing
  in ≤k bits is the standard near-dup index **[DOC]**.

**[INFER] Cheapest useful trap guard for GS, in order:**
1. **Hard per-host URL cap** (GS already has ~1000 in sitemap walk — extend it to the *host*, not
   the sitemap walk, so multiple entry points can't multiply it).
2. **Per-host z-score on newly-discovered URL count per tick.** A host whose discovery rate is >3σ
   above its own trailing mean is a trap candidate. z-score/IQR is the standard statistical
   baseline for exactly this class of metric **[REPORT]**.
3. **Template collapse**: hash the trafilatura markdown with digits and dates stripped; if a host's
   last K pages collapse to ≤2 distinct hashes, stop the host. This is BUbiNG's heuristic and it is
   nearly free because GS already extracts markdown and already hashes it for B2.
4. Only then consider SimHash/near-dup — more machinery, later payoff.

### 7.3 Canaries

- **Dagster asset checks** give pass/fail with severity; **freshness checks** "pass if the asset is
  found to be fresh, and fail if the asset is found to be overdue" **[DOC]**. In OSS (no Dagster+
  alerting), "you can write a sensor that checks for failed asset checks in the Dagster event log
  and invokes code to alert on them" **[DOC]**. `blocking=True` on `@asset_check` stops downstream
  materialisation **[DOC]**. Caveat: a known issue that freshness sensors do not run when assets
  are pending or failed (dagster#21949) **[DOC — issue]**.
- **The canary must assert it can alert on every run.** A freshness check on an asset that is never
  materialised is silent, not passing (that is the substance of #21949). **[INFER]** Pair every
  freshness check with a *negative fixture*: a synthetic asset deliberately stamped stale, whose
  check must be red. If the synthetic canary is green, the checking machinery is broken.

---

## 8. Prioritising 300k foundations

### 8.1 What the literature says

- **OPIC (Abiteboul, Preda, Cobena, WWW 2003)**: each page holds "cash" distributed equally to the
  pages it points to; importance is the accumulated cash flow. Works online, uses far fewer
  resources than PageRank, needs no stored link matrix, refines continuously **[DOC]**. **Adaptive
  OPIC** maintains history over a time window so pages present since the start don't dominate newer
  ones **[DOC]**. A variant is used by Xyleme **[DOC]**; `crawl-frontier` ships an OPIC backend
  **[DOC]**.
- **Cho & Garcia-Molina, "Effective page refresh policies for Web crawlers" (TODS 2003)**: models
  change as a **Poisson process**, validated against 270 sites; defines *freshness* and *age*;
  derives refresh policies and shows the optimal policy substantially beats what crawlers used
  **[DOC]**. Their frequency estimators cluster pages by features correlated with change frequency
  from past history **[DOC]**.
- **"Learning to Crawl" (arXiv 1905.12781)**: refresh scheduling under bandwidth constraints;
  learn per-site update patterns rather than a uniform schedule **[DOC]**.
- **Google's operational statement**: crawl allocation factors popularity, user value, content
  uniqueness and serving capacity; "if Googlebot visits a URL ten times and the content has not
  changed once, it will lower the recrawl frequency for that URL" **[DOC/REPORT]**.

### 8.2 Why OPIC is the wrong tool here **[INFER]**

OPIC and PageRank-lite score *link importance within a crawled graph*. GS's corpus is not a graph
it discovers by link-following — it is an **externally enumerated set of 300k organisations from
IRS data**, most with one small site. There is almost no inter-foundation link structure to flow
cash through. Importing OPIC would be machinery for a signal that doesn't exist. **Record it as
considered and rejected, with the reason.**

The transferable ideas are (a) *change-rate-driven recrawl*, which is Cho & Garcia-Molina and is
directly applicable, and (b) *value-weighted budget*, where the value comes from GS's own
business signals rather than from link topology.

### 8.3 Proposed priority score

**[INFER]** A single stored, recomputable `priority` float on the frontier, as a weighted sum of
normalised terms — legible, auditable, tunable without code:

| Term | Signal | Why | Weight (start) |
|---|---|---|---|
| **AG user demand** | foundation appeared in an AG search / match / saved list in last 90 d | Directly serves paying users; the north star | 0.35 |
| **Asset size** | IRS 990 total assets or total giving, log-scaled | A $500M foundation matters more to a grant writer than a $50k one | 0.25 |
| **Staleness** | `now - markdown_snapshot_at`, capped | Cho & Garcia-Molina; also the 5-years-stale-is-useless law | 0.20 |
| **Discovery confidence** | website resolution provider rank (IRS 990 > Wikidata > DDG scrape) × verification status | Don't spend the budget crawling a mis-resolved site (GS#2160/#2229/#2548) | 0.10 |
| **Change rate** | observed distinct content hashes / fetches, per host | Earn a faster cadence by actually changing | 0.10 |

Two hard rules on top of the score **[INFER]**:
- **Never-crawled beats any recrawl.** First coverage of a foundation is worth more than a
  freshness refresh of one already covered — coverage is the product gap, and the estate's law is
  100% *current* coverage rather than historical depth. Implement as a coarse tier, not a weight,
  so tuning can't accidentally starve first-crawl.
- **A host that has produced N consecutive empty/blocked results is demoted, not retried** — with
  the empty-result TTL GS already uses (90 days) as the backoff, and the *reason* recorded, so
  "blocked" never gets laundered into a data class.

### 8.4 Recrawl cadence

**[INFER]** Adaptive, per-host, cheap:
- Start every host at 180 days.
- On a fetch that produces an **unchanged content hash**, multiply the interval by 1.5 (cap 365 d
  — the stale law's outer bound).
- On a **changed hash**, halve it (floor 14 d).
- This is a crude multiplicative-weights approximation of the Poisson estimator, needs one integer
  column, and converges without any model. Google's stated behaviour is the same shape **[DOC]**.
- **Use conditional requests.** ETag / `If-Modified-Since` turn most recrawls into a 304 — the
  cheapest possible freshness check for both GS and the host, and good bot citizenship. GS
  reportedly makes no use of these today; this is likely the highest-leverage single change in
  this whole section.

---

## 9. Proposed design — GS lease-based frontier (GS#1777)

### 9.1 Schema

**[INFER]** Additive columns on the frontier table (`mine_urls`, or a new small `frontier_ready`
hot table — see 2.5, which I'd prefer):

```sql
claimed_by        text          -- worker identity: <host>/<pid>/<run_id>
claimed_at        timestamptz
lease_expires_at  timestamptz
claim_token       uuid          -- invalidates a woken zombie worker
heartbeat_at      timestamptz
attempts          smallint  not null default 0
last_error        text
next_eligible_at  timestamptz not null default now()
priority          real      not null default 0

-- the only index the claim needs:
CREATE INDEX frontier_claimable
  ON frontier (priority DESC, next_eligible_at)
  WHERE status = 'pending';

-- the reaper's index:
CREATE INDEX frontier_expiring
  ON frontier (lease_expires_at)
  WHERE status = 'fetching';

ALTER TABLE frontier SET (fillfactor = 85,
  autovacuum_vacuum_scale_factor = 0.02);
```

`status='fetching'` — the value GS already defines but never sets — becomes real.

### 9.2 The four operations

1. **Claim** — the CTE + `UPDATE … RETURNING` of §2.1, `LIMIT` = batch size, lease = 3× p99 batch
   duration, returning `claim_token`.
2. **Heartbeat** — every 30 s, one `UPDATE frontier SET heartbeat_at=now(),
   lease_expires_at=now()+:lease WHERE claim_token = ANY(:tokens)`. One statement for the whole
   in-flight batch, so it costs one round trip per 30 s per worker, not per URL. **[INFER]** This
   is the pattern that lets the lease be short without killing long fetches.
3. **Complete** — `UPDATE … SET status=…, markdown_b2_key=…, claimed_by=NULL, claim_token=NULL
   WHERE id=:id AND claim_token=:token`. **The token predicate is the whole safety property**: a
   woken zombie's update affects 0 rows and it knows to discard.
4. **Reap** — a sensor (or a maintenance op inside the crawl job, which avoids §3.4's
   sensor-daemon-blocking risk) that runs `UPDATE frontier SET status='pending', claim_token=NULL,
   next_eligible_at = now() + backoff(attempts) WHERE status='fetching' AND lease_expires_at <
   now()`, and sends any row past `max_attempts` to a terminal `status='abandoned'` with
   `last_error`. **The reaper must count and log what it reaped**; a reaper that silently returns
   thousands of rows a night is a crawler that isn't working, presented as a healthy one.

### 9.3 Timings **[INFER]**

| Parameter | Value | Rationale |
|---|---|---|
| Batch size | 200–500 URLs | One Neon transaction per batch (§5.2) |
| Heartbeat interval | 30 s | One statement/worker/30 s ≈ negligible Neon wake cost |
| Lease | 5 min | ≥3× heartbeat (the stall-detection rule of thumb **[REPORT]**), and > p99 batch |
| Reap interval | 2 min | Matches Dagster's `poll_interval_seconds` default, so nothing is detected slower than the platform's own granularity |
| Backoff | 5 min → 30 min → 4 h, then abandon at 3 attempts | Standard; keeps a poisoned URL from consuming the frontier |

### 9.4 Negative fixtures the change must ship with

Per the estate's own rule that a regression test never seen red is not a regression test — the
lease design has four properties and each needs a test that fails without it **[INFER]**:

| Property | Fixture | Mutant that must turn it red |
|---|---|---|
| Two workers never claim the same row | Two concurrent claims of a 1-row frontier | Remove `SKIP LOCKED` → deadlock/duplicate |
| An expired lease is reissued | Claim, freeze clock past lease, run reaper | Remove the `lease_expires_at < now()` conjunct |
| A live heartbeat is **not** reaped | Claim, beat, run reaper | Reaper must reap 0 — invert to `>` and it reaps |
| A woken zombie cannot stamp | Claim with token A, reap, re-claim with token B, complete with A | Drop `AND claim_token=:token` → the stale write lands |
| `attempts` cap terminates | Fail a row `max_attempts` times | Remove the cap → infinite retry loop |

---

## 10. Ranked cheapest resilience wins

Ordered by (value ÷ effort). Each names its mechanism, not an intention.

| # | Win | Effort | Why it pays |
|---|---|---|---|
| 1 | **Sentry Cron heartbeat from a thread that is not the crawl loop** | Hours | Closes the outermost watchdog ring at $0.78/mo, into a queue the estate already drains. Today a hung container is invisible until someone looks. **[DOC on mechanism]** |
| 2 | **Claim token on the frontier** | Hours | The single line that makes laptop-sleep resumption *correct* rather than merely tolerable. Cheap now, near-impossible to retrofit after a data corruption. |
| 3 | **Conditional requests (ETag / If-Modified-Since) on recrawl** | Hours | Turns most recrawls into a 304: less bandwidth, less B2, less Neon churn, better bot citizenship. Probably the largest single cost saving available. |
| 4 | **Lease + heartbeat + reaper (GS#1777 proper)** | Days | Converts "a crashed drain loses its in-flight rows silently" into "the reaper returns them in 5 minutes and says so". |
| 5 | **Audit what touches Neon outside the 12h work window** | Hours | The window may already be void (§6.2). Measurement before optimisation; the answer may be that the biggest saving is free. |
| 6 | **Record CU-hours per drain run in the run's own report** | Hours | Makes a batching regression visible as a cost regression rather than a surprise at month end. |
| 7 | **Per-host status rollup view + z-score alarm on discovery rate** | Days | The StormCrawler-standard breakdown GS lacks; catches the next GS#1545 trap before it freezes anything. |
| 8 | **Template-collapse guard (digits/dates-stripped markdown hash, ≤2 distinct over last K)** | Days | BUbiNG's heuristic **[DOC]**, nearly free given GS already hashes markdown. |
| 9 | **Move the frontier's hot set into a small `frontier_ready` table** | Days | Bounds vacuum/bloat structurally instead of by tuning; also makes the claim index tiny. |
| 10 | **Verify `dagster/max_runtime` actually fails a run** (string-typed tag, monitoring enabled) | Hours | Documented as fragile with an open issue **[DOC]**. An unverified timeout is a decoration. |
| 11 | **Delete `max_resume_run_attempts` from `dagster.yaml`, or comment why it's inert** | Minutes | It cannot work under `DefaultRunLauncher` **[DOC]**. Config that reads as protection and isn't, is worse than absent. |
| 12 | **Move the reaper out of a sensor into a maintenance op** | Hours | Avoids the sensor-daemon-blocking pattern **[REPORT]** where the hang-detector is itself the hang. |
| 13 | **`RLIMIT_AS` in the run-worker entry point** | Hours | The only run-isolation lever available under `DefaultRunLauncher` on Railway **[DOC on the limitation]**. |
| 14 | **Priority score column + never-crawled tier** | Days | Turns 300k undifferentiated rows into a budget aimed at AG users. |
| 15 | **Synthetic stale-heartbeat canary on a schedule** | Days | Proves rings 1–3 can alert. Without it, silence is indistinguishable from health. |

## 11. Bad fits, recorded with reasons

- **OPIC / PageRank-lite** — scores link importance in a discovered graph; GS's corpus is
  externally enumerated with negligible inter-site link structure. **[INFER]**
- **Celery with the SQLAlchemy broker** — no remote control or events (so no Flower), experimental
  transports have no dedicated maintainers **[DOC]**.
- **Huey** — no first-class Postgres backend.
- **graphile-worker's lease model** — a fixed 4-hour stale sweep with no heartbeat **[DOC]**; the
  design GS should *not* copy.
- **pgmq** — requires a Postgres extension (verify Neon availability), no retry counter/DLQ, and
  anti-scales past 16 workers **[DOC/REPORT]**. Its *visibility-timeout semantics* are worth
  copying; the extension is not worth adopting.
- **Dagster dynamic partitions keyed per foundation** — 300k keys in the Dagster event log, for
  metadata that already lives better-indexed in Postgres. **[INFER]**
- **Replacing the frontier with a queue library at all** — GS's fetch ceiling (~4.8 URLs/s under
  5 s/host politeness) is ~2% of the slowest measured library throughput **[REPORT + INFER]**.
  The frontier is not a throughput problem; it is a *lease* problem, and 60 lines of SQL solve it
  without a dependency that owns its own schema.

---

## Sources

**Postgres as a queue**
- https://www.postgresql.org/docs/current/sql-select.html (SKIP LOCKED, since 9.5)
- https://www.prisma.io/blog/you-dont-need-a-job-queue-postgres-already-has-skip-locked
- https://www.netdata.cloud/academy/update-skip-locked/
- https://aminediro.com/posts/pg_job_queue/
- https://neon.com/guides/queue-system
- https://dev.to/daniel_romitelli_44e77dc6/the-queue-was-a-table-how-i-built-claimunclaim-workers-with-skip-locked-stale-recovery-and-1ojm
- https://planetscale.com/blog/keeping-a-postgres-queue-healthy
- https://richyen.com/postgres/2026/05/04/postgres_job_queue.html
- https://www.tusharagrawal.in/blog/postgresql-index-bloat-vacuum-deep-dive
- https://blog.rajpoot.dev/posts/postgresql/postgres-vacuum-bloat-2026/

**Queue libraries**
- https://github.com/procrastinate-org/procrastinate
- https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html
- https://procrastinate.readthedocs.io/en/stable/howto/basics/connector.html
- https://github.com/janbjorge/pgqueuer · https://pgqueuer.readthedocs.io/
- https://github.com/pgmq/pgmq · https://pgxn.org/dist/pgmq/
- https://github.com/timgit/pg-boss/releases/tag/10.0.0 · https://pgboss.io/introduction
- https://worker.graphile.org/docs/schema · https://worker.graphile.org/docs/scaling · https://github.com/graphile/worker/issues/222
- https://brandur.org/river · https://github.com/riverqueue/river
- https://docs.celeryq.dev/projects/kombu/en/latest/reference/kombu.transport.sqlalchemy.html
- https://labs.dalibo.com/dramatiq-pg · https://gitlab.com/dalibo/dramatiq-pg
- https://github.com/hardbyte/postgresql-job-queue-benchmarking (2026-05-09 sweep)
- https://drumbeats.io/queue-worker-monitoring (stale_timeout ≥ 3× heartbeat)

**Dagster**
- https://docs.dagster.io/deployment/execution/run-monitoring
- https://docs.dagster.io/deployment/oss/oss-instance-configuration
- https://docs.dagster.io/deployment/dagster-plus/run-isolation
- https://docs.dagster.io/examples/best-practices/partition-backfill-strategies
- https://dagster.io/blog/dynamic-partitioning
- https://docs.dagster.io/guides/observe/asset-freshness-policies · https://docs.dagster.io/guides/test/asset-checks
- https://github.com/dagster-io/dagster/issues/21813 (max_runtime tag)
- https://github.com/dagster-io/dagster/issues/23359 (confusing run-monitoring docs)
- https://github.com/dagster-io/dagster/issues/21949 (freshness sensor doesn't run on pending/failed)
- https://github.com/dagster-io/dagster/issues/27759 (sensors can't request multi-run backfills)
- https://perun.au/insights/dagster-production/ (five production failure patterns)

**Watchdog / monitoring**
- https://docs.railway.com/deployments/healthchecks · https://docs.railway.com/deployments/restart-policy
- https://docs.railway.com/guides/manage-deployments · https://docs.railway.com/cli/restart
- https://docs.sentry.io/product/crons/getting-started/http/ · https://github.com/getsentry/sentry-python/issues/3279
- https://healthchecks.io/docs/healthchecks_sentry_comparison/
- https://futurion.blog/self-hosting-uptime-kuma-vs-healthchecks-io-honest-trade-offs-for-solo-builders/
- http://0pointer.de/blog/projects/watchdog.html · https://github.com/troglobit/watchdogd
- https://github.com/jasoncarreira/mimir/blob/main/docs/watchdog.md

**Checkpointing / storage / Neon**
- https://docs.scrapy.org/en/latest/topics/jobs.html · https://github.com/scrapy/scrapy/issues/4106
- https://dev.to/3ni8ma/crawling-at-scale-scheduling-deduplication-and-storage-3e5p
- https://stonefly.com/blog/content-addressable-storage-enterprise-guide/
- https://neon.com/docs/introduction/scale-to-zero · https://neon.com/docs/introduction/cost-optimization
- https://github.com/neondatabase/neon/discussions/12900 (check_availability / 6 CU/day floor)

**Crawler observability, traps, prioritisation**
- https://stormcrawler.apache.org/docs/ · https://github.com/DigitalPebble/storm-crawler/issues/389
- https://www.elastic.co/blog/stormcrawler-open-source-web-crawler-strengthened-by-elasticsearch-kibana
- https://support.archive-it.org/hc/en-us/articles/208332943-How-to-identify-and-avoid-crawler-traps
- https://arxiv.org/pdf/1601.06919 (BUbiNG — summarised-content fingerprint)
- https://patents.google.com/patent/US7627613B1/en (de-tagged fingerprint + host hash)
- https://dl.acm.org/doi/10.1145/775152.775192 (OPIC) · https://www2003.org/cdrom/papers/refereed/p007/p7-abiteboul.html
- https://crawl-frontier.readthedocs.io/en/opic/topics/opic-backend.html
- https://dl.acm.org/doi/10.1145/958942.958945 (Cho & Garcia-Molina, refresh policies)
- https://research.google.com/pubs/archive/34428.pdf (estimation of page change rates)
- https://arxiv.org/pdf/1905.12781 (Learning to Crawl)
- https://developers.google.com/crawling/docs/crawl-budget
- https://openobserve.ai/blog/ai-anomaly-detection-guide/ (z-score / IQR baselines)

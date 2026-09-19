# CRAWL LANE 1 — Open-source crawler frameworks and frontier/politeness design

Research date: **2026-09-07**. Judged against GrantSpider as described in `BRIEF-CRAWL.md`
(httpx, SQLAlchemy/Alembic, Dagster in **one** Railway container, Neon Postgres frontier,
B2 bodies, **no headless browsers**, **fixed 5 s/host** + robots crawl-delay max,
`asyncio.Semaphore(24)` cross-domain, one static egress IP, 12 h daily window, two-person shop).

Every quantitative claim below is tagged:
- **[FACT]** — read directly from source code, official docs, or the GitHub API in this session.
- **[INFER]** — my judgement, derived from those facts. Rejectable.

Repo activity numbers were pulled live via `gh api repos/<owner>/<repo>` on 2026-09-07.

---

## 1. Comparison table

Legend for **Frontier persistence**: *crash-safe* = documented to survive an unclean kill;
*clean-only* = documented to require an orderly shutdown; *external* = lives in another service.

| Project | License | Lang | Stars | Open iss. | Latest release (date) | Frontier: per-host queues | Frontier persistence | Politeness model | Trap / scope controls | Needs browser for JS? | Postgres frontier fit | Python cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Scrapy** | BSD-3 | Py | 64,228 | 407 | 2.18.0 (2026-08-20) | Yes — download slots, `DownloaderAwarePriorityQueue` default | Disk queue via `JOBDIR`, **clean-only** | Fixed `DOWNLOAD_DELAY` (±50 % jitter) + optional AutoThrottle (`latency / target_concurrency`). **Crawl-delay NOT honoured** (#892, open since 2014) | `DEPTH_LIMIT`, `URLLENGTH_LIMIT` 2083, `CLOSESPIDER_PAGECOUNT` (global, not per host) | Yes (needs scrapy-playwright etc.) | Poor — its scheduler owns the frontier | Low (it *is* Python) but replaces the app's control flow |
| **scrapy-redis** | MIT | Py | 5,643 | 40 | v0.9.1 (2024-07-06) | Inherits Scrapy's | Redis (external, durable) | Inherits Scrapy's | Inherits Scrapy's | Same as Scrapy | N/A — Redis, not PG | Adds a Redis container |
| **Frontera** | BSD-3 | Py | 1,333 | 95 | PyPI 0.8.1 (**2019-04-05**) | Yes (designed for it) | HBase / SQLAlchemy backends | Per-host delay | Some | Same as Scrapy | Had a SQLAlchemy backend | **Effectively dead** |
| **Crawlee for Python** | Apache-2.0 | Py | 9,489 | 99 | v1.10.0 (2026-08-31) | Not per-host; global autoscaling | **`SqlStorageClient` — Postgres via SQLAlchemy** (marked *Experimental*) | Global `max_tasks_per_minute` + autoscaling; per-domain throttle only for HTTP 429 (#1762). **Crawl-delay NOT supported** (#1396, open) | `max_requests_per_crawl` (global) | Optional (`PlaywrightCrawler`); `HttpCrawler` is browserless | **Best of the field** | Already in GS as `crawlee_bridge.py` |
| **Apache Nutch 1.x** | Apache-2.0 | Java | 3,285 | 12 | release-1.23 tag (2026-08-08) | Yes — `fetcher.queue.mode=byHost` | CrawlDb (Hadoop MapFile), batch-generational | **`fetcher.server.delay = 5.0`**, `fetcher.threads.per.queue = 1`, `fetcher.max.crawl.delay = 30` | `generate.max.count` per host/domain, `db.max.outlinks.per.page = 100`, URL filter/normalizer plugin chain | No (parse-html plugin only) | No — CrawlDb is the frontier | Java + Hadoop; JVM subprocess only |
| **StormCrawler** | Apache-2.0 | Java | 994 | 75 | 3.7.0 (2026-07-29) | Yes, via status backend / URLFrontier | OpenSearch / Solr / SQL / URLFrontier modules | Per-queue delay, adaptive scheduling | `urlfrontier.max.urls.per.bucket`, fetch-interval policy | No | Has an `external/sql` module | **Requires Apache Storm 3.0.0 cluster + Java 25** |
| **Heritrix 3** | NOASSERTION (Apache-2.0 in practice) | Java | 3,316 | 37 | 3.17.0 (2026-08-25) | Yes — one work queue per host, "only one URI from any given host is processed" | BDB-JE + checkpoints + `frontier.recover.gz` journal → **crash-safe** | **Adaptive**: `delayFactor = 5.0`, `minDelayMs = 3000`, `maxDelayMs = 30000`, `respectCrawlDelayUpToSeconds = 300`, `maxPerHostBandwidthUsageKbSec = 0` | **`queueTotalBudget`, `balanceReplenishAmount = 3000`, `errorPenaltyAmount = 100`, `precedenceFloor = 255`; `TooManyPathSegmentsDecideRule` maxPathDepth 20, `TooManyHopsDecideRule` maxHops 20, `PathologicalPathDecideRule` maxRepetitions 2** | No | No | JVM; borrow designs only |
| **BUbiNG** | Apache-2.0 | Java | 92 | 4 | no releases; **last push 2021-11-04** | Yes — *visit state* per host, grouped into *workbench entries* per IP | Mercator sieve on disk + virtualizer | **Dual: `schemeAuthorityDelay` (per host) AND `ipDelay` (per IP)**, with `ipDelayFactor` | `maxUrlsPerSchemeAuthority` (per-host URL ceiling) | No | No | **Dormant**; a paper to read, not code to run |
| **crawl4ai** | Apache-2.0 | Py | 81,879 | 176 | v0.9.3 (2026-08-31) | No per-host frontier | None durable | `RateLimiter(base_delay=(1.0,3.0), max_delay=60.0, max_retries=3, rate_limit_codes=[429,503])` per domain; `MemoryAdaptiveDispatcher` | Deep-crawl `filters.py`/`scorers.py`; no per-host budget | Playwright by default; **`AsyncHTTPCrawlerStrategy` exists** and `check_robots_txt` is supported | No | LLM-extraction-shaped; heavy deps |
| **Firecrawl (self-host)** | **AGPL-3.0** | TS | 177,514 | 604 | v2.11.0 (2026-06-19) | No | NuQ on **Postgres** (their queue) | Not documented as per-host | No | Playwright service required in the baseline stack | Its own Postgres, not yours | **Wrong stack** (Node) + AGPL |
| **Colly** | Apache-2.0 | Go | 25,501 | 194 | v2.2.0 (**2025-03-27**) | `LimitRule{DomainGlob, Delay, RandomDelay, Parallelism}` | `InMemoryQueueStorage{MaxSize:100000}` default; `Storage` interface is pluggable | Per-domain fixed + random delay; robots.txt supported | None built in | No | Interface exists, no PG impl shipped | Go; subprocess only |
| **spider-rs** | MIT | Rust | 2,701 | 0 | v2.52.2 (2026-03-31) | `with_delay(ms)`, `with_limit`, `with_depth` | Not durable by default | Fixed delay, `with_respect_robots_txt(true)` | Depth only | HTTP-first, Chrome on demand (`crawl_smart()`) | No | Rust; vendor-adjacent (Spider Cloud) |
| **Katana** | MIT | Go | 17,403 | 51 | v1.7.0 (2026-08-05) | `-hrl/-hrlm` host rate limit per second/minute | `-resume resume.cfg` | Fixed `-rd delay`, `-rl 150/s`, `-hrl` per host. **Does not obey robots.txt** — `-kf robotstxt` treats it as a *discovery source* | **Best-in-class**: `-fst` (path position → parameter after 10 distinct values), `-pcs` simhash/tfidf/bm25 similarity with `-pcsd 3` Hamming, `-pcsn 1` budget per cluster, `-mdp` max pages per domain, `-filter-page-type error,captcha,parked`, `-cs/-cos` regex scope | Optional `-hl` | No | Go; **borrow the heuristics** |
| **Browsertrix Crawler** | AGPL-3.0 | TS | 1,129 | 146 | v1.14.3 (2026-08-20) | per-seed scope | Redis-backed state | archival-grade | scope rules, `--limit` | **Browser is the point** | No | Contrast case only |
| **Brozzler** | Apache-2.0 | Py | 818 | 64 | (repo active; last push 2026-08-20) | RethinkDB frontier | RethinkDB | archival-grade | scope/SURT | **Requires Chrome + a graphical environment (Xvfb/Xvnc)** | No | Contrast case only |
| **URLFrontier** | Apache-2.0 | Java | 65 | 2 | 2.6 (2026-08-19) | **Yes — the spec is per-host queues** | Implementation-defined | `BlockQueueUntil`, per-host crawl rate | queue-level | N/A | gRPC service, any backend | A *spec* worth reading |

Sources for the table are inline in §3 and §7.

---

## 2. How to read this table

Only three rows have a frontier that is **documented crash-safe and per-host**: Heritrix,
BUbiNG, and Nutch's CrawlDb. **[FACT]** All three are JVM/Hadoop and none can host a Dagster
op's frontier in Postgres. Everything Python-shaped either has no durable frontier
(crawl4ai, Colly-style in-memory), a clean-shutdown-only one (Scrapy `JOBDIR`), or an
experimental one (Crawlee `SqlStorageClient`). **[INFER]** That is the central finding of this
lane: GS's Postgres frontier is not a gap in its design, it is the one part of GS that most
frameworks would *downgrade*.

---

## 3. Per-framework sections

### 3.1 Scrapy (+ scrapy-redis, Frontera)

- **License / governance** — BSD-3-Clause; Zyte-originated, community-governed.
  https://github.com/scrapy/scrapy
- **Activity [FACT]** — 64,228 stars, 407 open issues, last push 2026-09-07, release **2.18.0
  on 2026-08-20** (`gh api repos/scrapy/scrapy`, `.../releases/latest`).
- **Frontier [FACT]** — `SCHEDULER_PRIORITY_QUEUE` defaults to
  `scrapy.pqueues.DownloaderAwarePriorityQueue`, documented as working "better than
  ScrapyPriorityQueue when you crawl many different domains in parallel"; memory queue is
  LIFO by default, disk queue `PickleLifoDiskQueue`.
  https://docs.scrapy.org/en/latest/topics/settings.html
- **Resumability [FACT] — this is the disqualifier.** `JOBDIR` persists the scheduler queue,
  the dupefilter and `spider.state`, but the docs state verbatim: *"Job pausing and resuming
  is only supported when the spider is paused by stopping it cleanly. Forced, sudden or
  otherwise unclean shutdown can lead to data corruption in the job directory, which may
  prevent the spider from resuming correctly."* and *"A job must be resumed with the same
  Scrapy version that paused it."* https://docs.scrapy.org/en/latest/topics/jobs.html
  **[INFER]** GS's external daemon watchdog *restarts the container* on a hang (GS#1771);
  that is precisely the "forced, sudden" shutdown class. A Scrapy `JOBDIR` frontier would be
  corruptible by GS's own resilience mechanism.
- **Politeness [FACT]** — `DOWNLOAD_DELAY` is a fixed per-domain minimum,
  `RANDOMIZE_DOWNLOAD_DELAY=True` jitters it to 0.5×–1.5×. `CONCURRENT_REQUESTS_PER_DOMAIN`
  default 1. AutoThrottle computes `target_delay = latency / AUTOTHROTTLE_TARGET_CONCURRENCY`,
  then `new_delay = average(previous_delay, target_delay)`, clamped to
  `[DOWNLOAD_DELAY, AUTOTHROTTLE_MAX_DELAY]`; non-200 responses may only *increase* the delay.
  https://docs.scrapy.org/en/latest/topics/autothrottle.html
- **robots [FACT]** — `ROBOTSTXT_OBEY`, parser `ProtegoRobotParser` (Protego 0.6.2,
  2026-06-25). **Crawl-delay is not honoured**: the settings doc says `DOWNLOAD_DELAY` does
  not read robots Crawl-delay, and scrapy#892 "Crawl-Delay support for robots.txt" has been
  **open since 2014-09-20** (last touched 2025-06-03).
  https://github.com/scrapy/scrapy/issues/892
- **Traps / scope [FACT]** — `DEPTH_LIMIT` (0 = unlimited), `URLLENGTH_LIMIT` 2083,
  `CLOSESPIDER_PAGECOUNT`. There is **no per-host URL budget** and no template/anomaly
  detection.
- **Canonicalization [FACT]** — `RFPDupeFilter` fingerprints on canonical URL + method + body;
  canonicalization is `w3lib.url.canonicalize_url` (see §6c).
- **JS without a browser** — no; Scrapy needs `scrapy-playwright`/Splash.
- **Postgres + Dagster fit [INFER]** — poor. Scrapy owns the reactor and the process
  lifecycle. Running it inside a Dagster op means either `CrawlerProcess` in-process (Twisted
  vs Dagster's asyncio) or a subprocess whose durable state is a corruptible `JOBDIR`.
- **scrapy-redis [FACT]** — MIT, 5,643 stars, v0.9.1 (2024-07-06), requires **Redis ≥ 5.0**;
  its own README defers to Frontera for "URL expiration, advanced URL prioritization".
  https://github.com/rmax/scrapy-redis — **[INFER]** a second container GS's one-container
  constraint forbids.
- **Frontera [FACT]** — PyPI **0.8.1, 2019-04-05**; repo last commit 2025-06-06. Dead for
  practical purposes.

**Verdict [INFER]:** Scrapy's *AutoThrottle formula* is worth borrowing. Scrapy itself is not,
because its durable frontier is weaker than the Postgres one GS already has, and it is behind
GS on the one politeness point GS is legally exposed on (Crawl-delay).

---

### 3.2 Crawlee for Python

- **License / governance [FACT]** — Apache-2.0, Apify (a commercial scraping platform).
  9,489 stars, 99 open issues, **v1.10.0 on 2026-08-31**, last push 2026-09-07.
- **Frontier [FACT]** — `RequestLoader` (read-only) / `RequestManager` (writable) /
  `RequestManagerTandem` (dedup across the two).
  https://crawlee.dev/python/docs/guides/request-loaders
- **Persistence — the interesting part [FACT]** — five storage clients:
  `FileSystemStorageClient`, `MemoryStorageClient`, **`SqlStorageClient` (SQLite, PostgreSQL,
  MySQL/MariaDB, via SQLAlchemy — `pip install 'crawlee[sql_postgres]'`,
  `postgresql+asyncpg://…`)**, `RedisStorageClient`, `ApifyStorageClient`. The SQL client is
  marked **"Experimental — its API and behavior may change in future releases."**
  https://crawlee.dev/python/docs/guides/storage-clients
  **[FACT]** A GitHub code search for `SKIP LOCKED` in `apify/crawlee-python` returns 0 hits —
  the SQL request queue does not use the lease pattern GS would want.
- **Politeness [FACT]** — `ConcurrencySettings` with `max_tasks_per_minute` is **global, not
  per-host**; issue #1762 added *opt-in per-domain throttling for HTTP 429 backoff* only.
  https://crawlee.dev/python/docs/guides/session-management
- **robots [FACT]** — supported (`respect_robots_txt_file`; issues #1166, #1499, #1502, #2065
  are all robots-handling fixes), but **Crawl-delay is not implemented** — issue **#1396 "Add
  support for crawl-delay robots.txt directive", open since 2025-09-05**.
  https://github.com/apify/crawlee-python/issues/1396
- **Traps / scope** — `max_requests_per_crawl` is global. No per-host budget, no template
  detection. **[FACT]** (absence verified by reading the concurrency/session docs and the
  storage-client guide.)
- **JS without a browser [FACT]** — `HttpCrawler`/`ParselCrawler`/`BeautifulSoupCrawler` are
  browserless; `PlaywrightCrawler` and `AdaptivePlaywrightCrawler` need Chromium.
- **Postgres + Dagster fit [INFER]** — the best of any framework here, and GS already has a
  `crawlee_bridge.py` for the gov path. But adopting `SqlStorageClient` as *the* foundation
  frontier would move GS from a schema it controls (with `mine_urls`, `page_classification`,
  `fetch_strategy`, B2 keys) to an experimental library-owned schema, and would *lose*
  crawl-delay compliance. **Not worth it.**

**Verdict [INFER]:** keep using Crawlee as a *library* (retry policy, session pool, HTTP
client abstraction) exactly as GS does today. Do not promote it to frontier owner.

---

### 3.3 Apache Nutch (1.x)

- **License [FACT]** — Apache-2.0. 3,285 stars, **12** open issues (a well-drained tracker),
  last push 2026-09-04. Latest 1.x tag **release-1.23, tagged 2026-08-08** (`gh api
  repos/apache/nutch/git/refs/tags/release-1.23`). 2.x is abandoned (last tag release-2.4).
- **Frontier [FACT]** — CrawlDb + generational `inject → generate → fetch → parse → updatedb`.
  Politeness/scheduling knobs from `conf/nutch-default.xml` (read verbatim this session):
  - `fetcher.server.delay = 5.0` — **the same 5 s GS chose, as an upstream default**
  - `fetcher.server.min.delay = 0.0`
  - `fetcher.max.crawl.delay = 30` — *"If the Crawl-Delay in robots.txt is set to greater than
    this value (in seconds) then the fetcher will skip this page"*
  - `fetcher.queue.mode = byHost` (also `byDomain`, `byIP`)
  - `fetcher.threads.per.queue = 1`, `fetcher.threads.fetch = 10`
  - `generate.max.count = -1` with `generate.count.mode = host` — **the per-host URL ceiling**
  - `db.max.outlinks.per.page = 100`
  - `http.content.limit = 1048576` (1 MB) — note GS's cap is 200 MB
- **Adaptive recrawl [FACT]** — `AdaptiveFetchSchedule` with `db.fetch.schedule.adaptive.inc_rate = 0.4`
  (interval grows when unmodified), `dec_rate = 0.2` (shrinks when modified),
  `min_interval = 60.0 s`, `max_interval = 31536000.0 s` (365 d), `sync_delta = true`,
  `sync_delta_rate = 0.3`; defaults `db.fetch.interval.default = 2592000` (30 d),
  `db.fetch.interval.max = 7776000` (90 d). Default schedule class is `DefaultFetchSchedule`.
  https://github.com/apache/nutch/blob/master/conf/nutch-default.xml
- **Canonicalization [FACT]** — pluggable `urlnormalizer-*` and `urlfilter-*` plugin chains.
- **JS** — none without a plugin.
- **Fit [INFER]** — Hadoop-shaped batch generational crawling maps *conceptually* onto Dagster
  ops, but the CrawlDb is the frontier and it is a Hadoop MapFile. Java + Hadoop in a
  one-container Python shop is not a two-person-shop decision. **Borrow the constants, not the
  code.**

---

### 3.4 StormCrawler

- **License [FACT]** — Apache-2.0 (an ASF top-level project). 994 stars, 75 open issues,
  release **3.7.0 on 2026-07-29**, last push 2026-09-07.
- **Hard requirement [FACT]** — the README states you must *"install Apache Storm 3.0.0 to run
  the crawler"* and *"StormCrawler requires Java 25 or above."*
  https://github.com/apache/stormcrawler/blob/master/README.md
- **Frontier [FACT]** — pluggable status backends under `external/`: `elasticsearch`,
  `opensearch`, `opensearch-java`, `solr`, **`sql`**, **`urlfrontier`**, plus `warc`, `tika`,
  `playwright`, `langid`, `ai`, `aws`.
- **Defaults [FACT]** from the archetype `crawler-conf.yaml`: `fetcher.threads.number: 50`,
  `urlfrontier.max.buckets: 50`, `urlfrontier.max.urls.per.bucket: 10`,
  `fetchInterval.default: 1440` (min), `fetchInterval.fetch.error: 120`, `fetchInterval.error: -1`.
- **Fit [INFER]** — a Storm cluster is a multi-container distributed system. Categorically
  incompatible with "one Railway container". Rejected. Its `external/urlfrontier` module is
  the pointer worth following (§3.13).

---

### 3.5 Heritrix 3 — the reference design for politeness and budgets

- **License / governance [FACT]** — GitHub reports `NOASSERTION` (Apache-2.0 text in-tree);
  Internet Archive. 3,316 stars, 37 open issues, releases **3.15.0 (2026-06-09), 3.16.0
  (2026-07-03), 3.17.0 (2026-08-25)** — a monthly cadence after twenty years.
- **Frontier [FACT]** — `BdbFrontier`; the `queueAssignmentPolicy` is per-host so that *"at any
  given time only one URI from any given host is processed."*
  https://heritrix.readthedocs.io/en/latest/configuring-jobs.html
- **Politeness, read from source [FACT]** —
  `org/archive/crawler/postprocessor/DispositionProcessor.java`:
  ```
  setDelayFactor(5.0f);                  // "How many multiples of last fetch elapsed time
                                         //  to wait before recontacting same server"
  setMinDelayMs(3000);                   // always wait at least this long
  setRespectCrawlDelayUpToSeconds(300);  // honour robots Crawl-Delay up to 5 minutes
  setMaxDelayMs(30000);                  // never wait more than this
  setMaxPerHostBandwidthUsageKbSec(0);   // 0 = off
  ```
  https://github.com/internetarchive/heritrix3/blob/master/engine/src/main/java/org/archive/crawler/postprocessor/DispositionProcessor.java
  The wiki gives the operator recipe *"min-interval-ms=2000 max-delay-ms=30000 delay-factor=1
  min-delay-ms=0"* for "never more than one request every 2 seconds."
  https://github.com/internetarchive/heritrix3/wiki/Politeness-parameters
- **Budgets / precedence [FACT]** — from the bean reference: `balanceReplenishAmount = 3000`,
  `errorPenaltyAmount = 100`, `queueTotalBudget = -1` (off by default), `precedenceFloor = 255`,
  `maxRetries = 30`, `retryDelaySeconds = 900`.
  https://heritrix.readthedocs.io/en/latest/bean-reference.html
  Mechanism [FACT]: `WorkQueueFrontier` keeps `inactiveQueuesByPrecedence` — queues are
  deactivated by precedence rank, and a queue at or below `precedenceFloor` is not crawled.
- **Trap rules [FACT]** — `TooManyPathSegmentsDecideRule` `maxPathDepth = 20`,
  `TooManyHopsDecideRule` `maxHops = 20`, `PathologicalPathDecideRule` `maxRepetitions = 2`
  (*"rejects any URI that contains an excessive number of identical, consecutive
  path-segments"*).
- **Canonicalization [FACT]** — a rule pipeline in
  `modules/src/main/java/org/archive/modules/canonicalize/`: `LowercaseRule`,
  `StripExtraSlashes`, `StripSessionIDs`, `StripSessionCFIDs`, `StripUserinfoRule`,
  `StripWWWRule`, `StripWWWNRule`, `FixupQueryString`, plus a generic `RegexRule`.
  **[INFER]** `StripSessionIDs`/`StripSessionCFIDs` are exactly the class of rule GS needs
  against CMS-generated session-parameter traps like the Liferay incident (GS#1545).
- **Crash recovery [FACT]** — `frontier.recover.gz` journal of URI-completion and
  URI-discovery events; *"If a crash occurs during a crawl, the `frontier.recover.gz` journal
  can be used to recreate the approximate status of the crawler at the time of the crash."*
  Two modes: **full recovery** (replay the whole file — two passes: mark included, then
  re-enqueue; checkpoints taken during replay are *not* valid snapshots) and **split
  recovery** (pre-split into `.include.gz` + `.schedule.gz` so the recovery itself can be
  checkpointed). https://heritrix.readthedocs.io/en/latest/operating.html
  **[INFER]** GS gets this for free: a Postgres frontier *is* the recovery journal.
- **JS** — none. Heritrix is HTML-only by design (Brozzler is IA's browser answer).
- **Fit [INFER]** — Java, Spring-bean-configured, single-process, not a library. **Borrow the
  numbers and the rule taxonomy; do not run it.**

---

### 3.6 BUbiNG — the reference design for dual-axis politeness

- **License / activity [FACT]** — Apache-2.0, LAW @ Università di Milano. 92 stars, 4 open
  issues, **last push 2021-11-04, no GitHub releases**. Dormant.
- **The paper is the deliverable.** Boldi, Marino, Santini, Vigna, *"BUbiNG: Massive Crawling
  for the Masses"*, ACM TWEB. https://vigna.di.unimi.it/ftp/papers/BUbiNG.pdf
- **Politeness [FACT]** — *"politeness constraints are satisfied both at the host and the IP
  level, i.e., any two consecutive data requests to the same host (name) or IP are separated
  by at least a specified amount of time"* — configured as `schemeAuthorityDelay` (per host)
  and `ipDelay` (per IP), with `ipDelayFactor` scaling the IP delay by the number of known
  agents. https://github.com/LAW-Unimi/BUbiNG/blob/master/src/it/unimi/di/law/bubing/StartupConfiguration.java
- **The workbench [FACT]** — *"a priority queue of priority queues of FIFO queues"*: each
  **visit state** is one host's FIFO of path+query byte arrays plus a `next-fetch` timestamp;
  visit states are grouped into **workbench entries** by resolved IP, each with its own
  IP-level `next-fetch`; the workbench is the priority queue over entries. *"there is a host
  that can be visited without violating host or IP politeness constraints if and only if the
  host associated with the top visit state of the top workbench entry can be visited."*
  The structure is explicitly *"a significant improvement over IRLBot's two-queue approach…
  it can detect in constant time whether a URL is ready for download without violating
  politeness limits."*
- **Per-host ceiling [FACT]** — `maxUrlsPerSchemeAuthority`, *"The maximum number of URLs we
  shall download from each scheme+authority."*
- **Dedup [FACT]** — a Mercator **sieve** (64-bit hashes in a sorted disk file, merged
  periodically) fronted by an in-core LRU cache of 128-bit fingerprints that *"discards more
  than 90% of the URLs discovered"* before they touch the sieve. Content dedup: a hash
  fingerprint over *summarised content* — HTML attributes stripped, digits and dates
  discarded — *"allows for instance to collapse pages that differs just for visitor counters
  or calendars"*; default **intra-site only** (digest seeded with the host name), and the
  authors measured that going inter-site would remove only 3.3–8.6 % more pages.
- **Traps — honest admission [FACT]** — the paper's future work says: *"Future work on BUbiNG
  includes integration with spam-detection software, and proper handling of spider traps
  (especially, but not only, those consisting in infinite non-cyclic HTTP-redirects)."*
  **[INFER]** Even the state-of-the-art academic crawler shipped without trap handling. GS
  should not feel behind for having built traps-by-incident; it should feel behind only for
  not having encoded the *lessons* as reusable rules.
- **Fit** — none as code. **Read the paper; borrow the workbench and the summarised-content
  digest.**

---

### 3.7 crawl4ai

- **License / activity [FACT]** — Apache-2.0. **81,879 stars**, 176 open issues, **v0.9.3
  (2026-08-31)**, last push 2026-09-07. Huge attention, young API (still 0.x).
- **Browserless path [FACT]** — `crawl4ai/async_crawler_strategy.py` defines both
  `AsyncPlaywrightCrawlerStrategy` (line 46) and **`AsyncHTTPCrawlerStrategy` (line 2496)**
  taking an `HTTPCrawlerConfig`. So a no-browser lane exists, though every tutorial is
  browser-first.
- **robots [FACT]** — `AsyncWebCrawler` instantiates a `RobotsParser` and honours
  `config.check_robots_txt`, returning `error_message="Access denied by robots.txt"` with an
  `X-Robots-Status` header. (`crawl4ai/async_webcrawler.py`, lines 164, 383–395.)
- **Politeness [FACT]** — `RateLimiter(base_delay=(1.0, 3.0), max_delay=60.0, max_retries=3,
  rate_limit_codes=[429, 503])`; base delay is documented as *"between consecutive requests to
  the same domain"*. Dispatchers: `MemoryAdaptiveDispatcher` (pauses on memory pressure),
  `SemaphoreDispatcher`. https://docs.crawl4ai.com/advanced/multi-url-crawling/
- **Frontier** — `deep_crawling/` has `bfs_strategy.py`, `dfs_strategy.py`, `bff_strategy.py`,
  `filters.py`, `scorers.py`. **[INFER]** In-process and per-invocation; there is no durable,
  resumable, per-host frontier.
- **Fit [INFER]** — crawl4ai's centre of gravity is *LLM-ready extraction from a handful of
  URLs*, which is the opposite of GS's problem (300k hosts, no LLM on the crawl path, a
  durable frontier). Its `RateLimiter` shape and `MemoryAdaptiveDispatcher` are worth a look;
  the framework is not.

---

### 3.8 Firecrawl (self-hosted)

- **License [FACT]** — **AGPL-3.0** (`LICENSE` is the GNU AGPL v3 text). 177,514 stars, 604
  open issues, v2.11.0 (2026-06-19). TypeScript.
- **Self-host stack [FACT]** — API service + **PostgreSQL** (their NuQ queue; FoundationDB
  optional) + Redis + RabbitMQ + a **Playwright service**. `SELF_HOST.md` states the baseline
  is *"bundled Playwright with basic fetch fallback"* and *"Queue: NuQ PostgreSQL."*
  https://github.com/firecrawl/firecrawl/blob/main/SELF_HOST.md
- **Documented self-host gaps [FACT]** — no Fire-engine (their anti-bot layer), no
  screenshots/interaction, no agent/browser features, no specialised formats, no LLM
  extraction without an external provider.
  https://docs.firecrawl.dev/contributing/self-host
- **Fit [INFER]** — five services where GS has one; a browser in the baseline path GS has
  deliberately removed; AGPL over a codebase that feeds a commercial SaaS (AI Grant Helper) —
  a licence question Nathan should not have to answer. **Rejected on three independent
  grounds.**

---

### 3.9 Colly

- **License / activity [FACT]** — Apache-2.0, Go. 25,501 stars, 194 open issues, **v2.2.0
  released 2025-03-27** (17 months old) though `master` was pushed 2026-09-02.
- **Politeness [FACT]** — `LimitRule{DomainRegexp, DomainGlob, Delay, RandomDelay, Parallelism}`
  from `http_backend.go` — per-domain fixed delay + jitter + concurrency, matched by glob or
  regex. Robots.txt is a listed feature.
  https://github.com/gocolly/colly/blob/master/http_backend.go
- **Frontier [FACT]** — `queue/queue.go` defines a `Storage` interface, default
  `InMemoryQueueStorage{MaxSize: 100000}`. No Postgres implementation ships in-tree.
- **Traps / dedup** — nothing built in.
- **Fit [INFER]** — Go binary, in-memory queue, no durable frontier. Its only transferable
  idea is the `DomainGlob → LimitRule` shape, i.e. **per-host politeness *policy* selected by
  pattern**, which GS could use for its known-slow or known-fragile hosts.

---

### 3.10 spider-rs

- **License / activity [FACT]** — MIT, Rust. 2,701 stars, **0** open issues, **v2.52.2
  (2026-03-31)**, last push 2026-09-05.
- **Features [FACT]** — `with_limit(50)` concurrency, `with_depth(10)`, `with_delay(500)` ms,
  `with_respect_robots_txt(true)`. *"Spider runs HTTP-first and launches headless Chrome only
  when a page needs JavaScript"* via `crawl_smart()`.
  https://github.com/spider-rs/spider/blob/main/README.md
- **[INFER]** The HTTP-first-then-render policy is exactly what GS#1102's render-class routing
  is trying to build, and spider-rs is the cleanest public statement of it. But the project is
  the engine behind **Spider Cloud**, a paid service — a vendor-adjacent OSS with a zero-issue
  tracker is a governance smell for a load-bearing dependency, and it is Rust. **Study the
  routing policy; do not adopt.**

---

### 3.11 Katana — the trap-detection donor

- **License / activity [FACT]** — MIT, ProjectDiscovery. 17,403 stars, 51 open issues,
  **v1.7.0 (2026-08-05)**, last push 2026-09-07.
- **robots [FACT]** — **Katana does not obey robots.txt.** `-kf, -known-files
  all,robotstxt,sitemapxml` treats robots.txt as a *source of URLs to crawl*, described as
  *"Option to enable crawling robots.txt and sitemap.xml file, disabled as default."* There is
  no obey flag. **[INFER]** As a security tool that is deliberate, and it disqualifies Katana
  as GS's crawler outright — GS's whole legitimacy posture (GS#2586) is the opposite.
- **Trap and scope controls, read from `pkg/types/options.go` [FACT]** — this is where Katana
  is genuinely ahead of everything else in this table:
  ```
  FilterSimilar          // "filters crawling of similar looking URLs by normalizing
                         //  variable path segments (IDs, UUIDs, hashes, dates)"
  FilterSimilarThreshold // "number of distinct values at a path position before it is
                         //  treated as a parameter (default 10, lower = more aggressive)"
  PageContentSimilar     // Layer-2 content similarity filtering
  PageContentSimilarMode // "simhash, tfidf, or bm25 (default simhash)"
  PageContentSimilarDistance // "max SimHash Hamming distance (default 3)"
  PageContentSimilarBudget   // "how many pages per similarity cluster to fully process (default 1)"
  MaxDomainPages         // "maximum number of pages to crawl per domain (0 = unlimited)"
  FilterPageType         // -filter-page-type error,captcha,parked
  ```
  https://github.com/projectdiscovery/katana/blob/main/pkg/types/options.go
  Plus `-cs/-cos` in/out-of-scope regex, `-fs dn|rdn|fqdn` field scope, `-hrl/-hrlm` per-host
  rate limits, `-resume resume.cfg`, `-mrs 4194304` max response size.
- **[INFER]** Three of these are directly answerable to GS incidents: `FilterSimilar` is a
  general form of the Liferay layout-permutation trap (GS#1545); `MaxDomainPages` is the
  per-host budget GS lacks; `FilterPageType error,captcha,parked` is the *"honest
  classification of blocked vs empty vs down"* the brief asks for, already shipped as an
  enum by someone else. **This is the single richest borrow in the lane.**

---

### 3.12 Browsertrix Crawler / Brozzler — the headless-first contrast

- **Browsertrix Crawler [FACT]** — AGPL-3.0, Webrecorder, 1,129 stars, 146 open issues,
  **v1.14.3 (2026-08-20)**. Runs a real browser in a single Docker container; the browser
  *is* the fidelity guarantee.
- **Brozzler [FACT]** — Apache-2.0, Internet Archive, 818 stars, 64 open issues, last push
  2026-08-20. Requires Python 3.9+, **RethinkDB**, **Chromium/Chrome v64+**, and warcprox; the
  README states *"The browser requires a graphical environment to run"* (Xvnc4/Xvfb on
  servers). https://github.com/internetarchive/brozzler/blob/master/README.rst
- **[INFER] Why this contrast matters to GS.** Both are built by organisations whose *product*
  is archival fidelity, and both pay for it with a browser per fetch plus a state store
  (RethinkDB / Redis). That is the cost curve GS declined when it deprecated Playwright on
  2026-05-11. The contrast validates the decision: nobody has made browser-fidelity cheap.
  It also frames GS#1102 correctly — the question is not "should GS add a browser" but
  "how much of the browser's output can be recovered from `__NEXT_DATA__`, platform APIs and
  archives", which is a *different* engineering problem, not a cheaper version of this one.

---

### 3.13 URLFrontier — the spec nobody mentions

- **[FACT]** Apache-2.0, `crawler-commons/url-frontier`, 65 stars, **2** open issues, release
  **2.6 on 2026-08-19**. *"a crawler/language-neutral API for the operations that web crawlers
  do when communicating with a web frontier"*, defined in gRPC, per-host queues, with
  `GetURLs`, `PutURLs`, `DeleteQueue`, `BlockQueueUntil` and per-hostname crawl-rate control.
  StormCrawler ships `external/urlfrontier` against it.
  https://github.com/crawler-commons/url-frontier
- **[INFER]** GS should not *implement* the gRPC service. But the **operation set is a design
  checklist**: GS's frontier service today has no equivalent of `BlockQueueUntil` (block a
  whole host until timestamp T — the natural home for 429/Retry-After, Cloudflare challenge
  backoff, and robots-fetch failure), and no `DeleteQueue` (retire a host wholesale). Adding
  those two verbs to the GS frontier service is a small, high-value change.

---

## 4. Answer (a) — replace the bespoke httpx stack, or borrow?

**Borrow. Do not replace.** **[INFER]**, on these documented grounds:

1. **No framework's durable frontier beats a Postgres one under GS's constraints.** The only
   crash-safe per-host frontiers in the field are Heritrix's BDB+recovery-journal, BUbiNG's
   sieve+workbench, and Nutch's CrawlDb — all JVM, none embeddable in a Dagster op. **[FACT]**
   The Python options are: Scrapy `JOBDIR`, documented to corrupt on unclean shutdown
   (https://docs.scrapy.org/en/latest/topics/jobs.html); Crawlee `SqlStorageClient`, marked
   Experimental (https://crawlee.dev/python/docs/guides/storage-clients); scrapy-redis, which
   needs a second container; crawl4ai, which has none. **A Postgres table with an index is
   already the strongest durable frontier available to a Python one-container shop.**
2. **The one-container constraint eliminates half the field on its own.** StormCrawler needs a
   Storm 3.0.0 cluster and Java 25 **[FACT]**; Firecrawl self-host needs five services
   including Playwright **[FACT]**; Brozzler needs RethinkDB plus an X server **[FACT]**;
   scrapy-redis needs Redis **[FACT]**.
3. **Adopting a framework would make GS *less* compliant, not more.** GS honours robots
   Crawl-delay (max with 5 s). **[FACT]** Scrapy does not (#892, open 12 years) and Crawlee
   does not (#1396, open). Katana does not obey robots at all. Trading a compliant fetcher for
   a non-compliant one, in a business whose crawler publishes an identity page and is applying
   for Cloudflare Verified Bots, is a strictly negative trade.
4. **GS's frontier is not generic — and that is load-bearing.** `mine_urls` carries
   `discovery_method`, `content_type`, `url_metadata`, `page_classification`, `fetch_strategy`
   and B2 keys; the crawl is *one stage of a data pipeline*, not the product. Every framework
   here would demand that state live outside its own frontier, i.e. GS would keep the
   Postgres tables *and* gain a second source of truth. **[INFER]**
5. **The genuine gaps are all inside GS's own code**, not at the framework boundary: no
   lease/claim (GS#1777, `status='fetching'` defined but unused), no per-host URL budget, no
   adaptive delay, no template/anomaly detection, no conditional requests, no change-rate
   recrawl model. Each is 50–300 lines in a middle-layer service. **[INFER]** A framework
   migration would cost more than all of them combined and would deliver only the ones the
   framework happens to have — which, per the table, is *fewer than half*.

**The one thing worth adopting as code, not design:** nothing at the frontier layer. At the
*library* layer, `courlan` (§6c) and `protego` (already in Scrapy's orbit, BSD-3, 0.6.2
released 2026-06-25) are cheap, focused, and additive.

---

## 5. Answer (b) — what the literature prescribes, and what GS lacks

### Adaptive politeness

| Source | Prescription | GS today |
|---|---|---|
| **IIR ch. 20 (Mercator frontier)** **[FACT]** | *"the new entry t_e could be the current time plus ten times the last fetch time"* — i.e. **delay = 10 × last fetch latency**, enforced by a heap of earliest-permissible-times over per-host back queues. https://nlp.stanford.edu/IR-book/html/htmledition/the-url-frontier-1.html | Fixed 5 s. No latency feedback. |
| **Heritrix** **[FACT]** | `delayFactor = 5.0` × last elapsed fetch time, clamped to `[minDelayMs 3000, maxDelayMs 30000]`, with robots Crawl-Delay honoured up to `respectCrawlDelayUpToSeconds = 300`. | Fixed 5 s = Heritrix's `minDelayMs` (3 s) rounded up. No factor, no cap-driven adaptation. GS *does* honour Crawl-delay — with no documented upper bound. |
| **Nutch** **[FACT]** | `fetcher.server.delay = 5.0` fixed, one thread per host queue, and **`fetcher.max.crawl.delay = 30`** — a robots Crawl-Delay above 30 s means *skip the page*, not wait. | GS takes `max(5, crawl_delay)` with **no ceiling**. |
| **BUbiNG** **[FACT]** | Two independent delays: `schemeAuthorityDelay` (per host) **and** `ipDelay` (per IP), because many hosts share one IP. | Per-host only. |
| **Scrapy AutoThrottle** **[FACT]** | `target = latency / target_concurrency`; `new = mean(previous, target)`; clamped to `[DOWNLOAD_DELAY, MAX_DELAY]`; non-200s may only increase. | None. |

**What GS lacks, ranked [INFER]:**
1. **A robots Crawl-Delay ceiling.** GS takes `max(5 s, crawl_delay)` unbounded. A site
   advertising `Crawl-delay: 3600` silently converts one foundation into a 1-host-per-hour
   drain inside a 12-hour window. Both Nutch (30 s → skip) and Heritrix (300 s cap) put a
   number on this. **This is a live throughput bug, not a nicety.**
2. **Per-IP politeness.** GS crawls ~300k foundations, an enormous share of which are on
   Squarespace/Wix/GoDaddy/Network Solutions shared IPs. Per-host 5 s with
   `Semaphore(24)` cross-domain can legitimately put 24 concurrent requests on **one IP**.
   BUbiNG treats this as a first-class constraint; GS does not model it at all. From a single
   static egress IP this is also the most likely cause of a blanket block by a large host.
3. **Latency-adaptive delay.** Every reference design multiplies the *observed* latency. GS's
   fixed 5 s is simultaneously too aggressive for a struggling small-church host (800 ms
   response → Mercator would wait 8 s, Heritrix 4 s) and needlessly slow for a fast CDN
   (80 ms → Heritrix would wait its 3 s floor). A `max(5.0, delay_factor × last_latency)`
   floor-preserving form keeps Nathan's 5 s ruling intact while adding the protective half.

### Per-host URL ceilings

**[FACT]** Four independent prescriptions:
- Heritrix `queueTotalBudget` (default −1 = off) with `balanceReplenishAmount = 3000` and
  `errorPenaltyAmount = 100` — a queue *spends* budget and is deactivated when it runs out.
- BUbiNG `maxUrlsPerSchemeAuthority`.
- Nutch `generate.max.count` with `generate.count.mode = host`.
- Katana `MaxDomainPages`.

**GS lacks all of it.** **[FACT per brief]** GS caps sitemap *enumeration* at ~1000 URLs and
sitemap recursion at depth ≤ 10 with a 60 s/foundation deadline — those are *discovery*
limits, not a *fetch* budget. A site that passes the sitemap stage with 1000 URLs and then
generates more via the homepage shallow-crawl fallback has no ceiling. **[INFER]** Heritrix's
*error-penalty* refinement is the subtle and valuable part: a host that returns errors burns
budget faster than one that returns pages, so bad hosts fall out of the crawl automatically
rather than being retried on a fixed schedule. GS's circuit breaker is the on/off version of
this; a budget is the graduated version.

### Trap detection

**[FACT]** The prescriptions, from strongest to weakest:
- **Katana**: normalise variable path segments (IDs, UUIDs, hashes, dates) and treat a path
  position as a parameter once it has shown ≥ 10 distinct values; then budget 1 page per
  similarity cluster.
- **Heritrix**: `PathologicalPathDecideRule` maxRepetitions 2 (identical consecutive path
  segments — the classic `/a/b/a/b/a/b/` trap), `TooManyPathSegmentsDecideRule` maxPathDepth
  20, `TooManyHopsDecideRule` maxHops 20.
- **Scrapy**: `URLLENGTH_LIMIT = 2083`, *"Prevents infinite URL growth from programming
  errors."*
- **BUbiNG**: admits it has none, and names *"infinite non-cyclic HTTP-redirects"* as the case
  it cannot handle.
- **IIR**: only *"Crawlers must be designed to be resilient to such traps"* — no mechanism.

**What GS lacks [INFER]:** every one of the mechanical rules. GS has an incident history
(Liferay layout permutations, per-show sitemaps, GS#1545 freezing the Dagster daemon) and a
*timeout* response (60 s deadline threaded through recursion, external watchdog). A timeout is
a containment, not a detection: it stops the trap from killing the process, but the trap still
consumes the whole 60 s budget every time the foundation is revisited, and it is never
recorded as a trap. The four rules above are all pure functions of a URL string — they cost
nothing, run before any fetch, and would have caught the Liferay case at rule 1 or 3.
GS *does* have redirect protection (20-hop cap with per-hop SSRF checks) — that is the one
trap class where GS is ahead of BUbiNG.

---

## 6. Answer (c) — URL canonicalization and near-duplicate detection

### 6c.1 Canonicalization libraries

| Library | Licence | Latest (date) | Stars | What it does | Verdict for GS |
|---|---|---|---|---|---|
| **w3lib** | BSD-3 | **2.4.1, 2026-03-20** | 418 | `canonicalize_url`: safe-URL conversion, query args **sorted by key then value**, spaces→`+`, percent-encoding case-normalised (`%2f`→`%2F`), blank query values dropped, fragment dropped, dot-segments resolved, IPv6 host normalised. `safe_url_string` is documented against the WHATWG URL standard and RFC 3986. `url_query_cleaner` keeps only a named parameter list. https://w3lib.readthedocs.io/en/latest/w3lib.html | **The dedup-key primitive.** Battle-tested (it is Scrapy's own `RFPDupeFilter` basis), tiny, no deps. |
| **url-normalize** | MIT | **3.0.0, 2026-04-25** | 100 | IDNA2008+UTS46 IDN, scheme/host lowercase, default-port removal, RFC-compliant dot-segment resolution, minimal uppercase-hex percent-encoding, **UTF-8 NFC**. Python 3.10+. Self-describes as *"Ideal for database deduplication, caching, web crawling."* https://github.com/niksite/url-normalize | Complementary to w3lib: it does the **IDN + NFC** work w3lib does not. Small maintainer surface (100 stars, 0 open issues) — **[INFER]** acceptable for a pure function, and vendorable if it goes quiet. |
| **courlan** | Apache-2.0 | **1.4.0, 2026-06-01** | 176 | Built for crawling, by trafilatura's author (which GS already runs). `clean_url`/`normalize_url`, validation, **spam and tracker detection**, content-type heuristics, `is_external`, `is_navigation_page`, `is_not_crawlable`, `extract_links`, `filter_links` with robots support, and a **`UrlStore`** with per-domain queues, dedup, optional bz2/zlib compression of stored paths, and SIGINT/SIGTERM handlers that dump unvisited URLs. Python 3.10+. https://github.com/adbar/courlan | **The best fit in this list.** Same author and release cadence as trafilatura, which is already a GS dependency, so no new maintainer risk. `is_not_crawlable`/`is_navigation_page` are directly usable by GS's URL-heuristic page classifier (Nathan-law: no LLM tokens on classification). |
| **ural** | **GPL-3.0** | 1.5.0, **2025-03-25** | 77 | SciencesPo médialab URL heuristics. | **Rejected. [FACT]** GPL-3.0 — unusable in a proprietary SaaS backend. Also 18 months since a release. |

**Recommended stack [INFER]:** `w3lib.url.canonicalize_url` for the **stored dedup key**
(deterministic, sorted, fragment-free), `url-normalize` in front of it for IDN/NFC hosts, and
`courlan` for the *policy* functions (is this crawlable, is this a navigation page, is this
spam/tracker) — which is a different job from canonicalization and is where GS currently has
hand-rolled heuristics. **Important caveat [INFER]:** `canonicalize_url` sorts query
parameters, which changes semantics on the minority of sites where parameter order matters.
Store the canonical form as the *dedup key* alongside the *as-discovered URL* used for
fetching; never fetch the canonical form.

`UrlStore` is worth reading but **not** worth adopting — its own docstring says *"a logical
write is not globally atomic — drive mutations from a single writer thread"* **[FACT]**, which
is the in-process constraint GS escaped by putting the frontier in Postgres.

### 6c.2 Near-duplicate content detection, costed at ~1M pages

| Approach | Signature size | Storage @ 1M pages | Index | Notes |
|---|---|---|---|---|
| **Exact hash** (GS today, hash-addressed B2) | 32 B (sha256) | 32 MB | B-tree | Catches byte-identical only. Misses the visitor-counter/date case entirely. |
| **BUbiNG summarised-content digest** | 8–16 B | 8–16 MB | B-tree | **[FACT]** Strip HTML attributes, discard digits and dates, then hash. *"allows for instance to collapse pages that differs just for visitor counters or calendars."* Seed the digest with the host name for intra-site scope. |
| **simhash 64-bit** (Charikar; Manku/Jain/Das Sarma WWW'07) | **8 B** | **8 MB** | 4–20 permuted tables, or brute-force popcount | **[FACT]** *"For a repository of 8 billion webpages, 64-bit simhash fingerprints and k = 3 are reasonable."* https://research.google.com/pubs/archive/33026.pdf — Katana independently ships `-pcsd 3` as its default Hamming distance. |
| **datasketch MinHash/MinHashLSH** | 128 perms × 4 B = **512 B** (`affine32` scheme in 2.0.0, *"stored as uint32, halving memory use"*) | **~512 MB** signatures alone, plus LSH band tables | Redis / Cassandra / MongoDB backends | **[FACT]** datasketch **2.0.0, 2026-07-05**, MIT, 2,962 stars. Docs: *"the price is linear in num_perm"* and *"To insert a large number of MinHashes in sequence, it is advisable to use an insertion session."* http://ekzhu.com/datasketch/lsh.html |

**Library activity [FACT]:** `simhash` on PyPI is **2.1.2, 2022-03-03** (stale);
`seomoz/simhash-py` last pushed 2023-05-15 (423 stars) with `simhash-cpp` behind it (2023-02).
`datasketch` is the only actively maintained option of the two.

**Recommendation [INFER]:** at 1M pages, **simhash is 64× cheaper in storage than MinHash and
sufficient for the actual GS question**, which is *"is this page a template permutation of one
I already have on this host?"* — a near-exact question, not a fuzzy-similarity-search question.
MinHashLSH earns its 512 MB only when you need *"find me everything similar to this"* across
the corpus, which GS does not need on the crawl path. Concretely:

1. Compute BUbiNG's summarised-content digest first (attributes/digits/dates stripped). It is
   ~10 lines, costs 8 bytes, catches the calendar/counter class, and needs no new dependency.
2. Add a 64-bit simhash column, seeded per host, with a Hamming-3 comparison against the last
   N digests for that host. Because the comparison is **intra-host** (BUbiNG's default, and
   they measured inter-site would add only 3.3–8.6 %), N is small and brute-force popcount
   over a host's existing digests is fine — **no LSH index required at all**. **[INFER]** This
   is the whole point: scoping dedup to the host collapses the 1M-page problem into ~300k
   independent problems of a few dozen rows each.
3. Because the maintained pure-Python simhash libraries are stale, implement the 64-bit
   fold over shingle hashes directly (~30 lines). **[INFER]** Depending on a 2022 C++ binding
   for 30 lines of arithmetic is the wrong trade in a two-person shop.

---

## 7. Answer (d) — lease-based frontier on Postgres

### The primitive **[FACT]**

PostgreSQL's own docs on the locking clause:

> *"With `SKIP LOCKED`, any selected rows that cannot be immediately locked are skipped.
> Skipping locked rows provides an inconsistent view of the data, so this is not suitable for
> general purpose work, but can be used to avoid lock contention with multiple consumers
> accessing a queue-like table."*

https://www.postgresql.org/docs/current/sql-select.html — available since PostgreSQL 9.5.
This is the sanctioned pattern, in the vendor's own words, for exactly GS's use.

### The four-part pattern

**[INFER]**, assembled from the libraries surveyed below:

1. **Claim** — `UPDATE mine_urls SET status='fetching', leased_by=:worker, lease_expires_at =
   now() + :ttl, attempt = attempt + 1 WHERE id IN (SELECT id FROM mine_urls WHERE
   status='pending' AND next_eligible_at <= now() ORDER BY priority, next_eligible_at LIMIT
   :n FOR UPDATE SKIP LOCKED) RETURNING *` — one statement, atomic, no double-dispatch.
   GS#1777's `status='fetching'` already reserves the state; this is the missing write.
2. **Lease expiry** — the lease TTL is the *only* thing that makes a Dagster-container restart
   safe. GS's watchdog kills the container; without an expiring lease, every in-flight URL is
   stranded in `fetching` forever. **[INFER] This is the concrete bug GS#1777 is protecting
   against, and it is currently unprotected because the state is defined but unused.**
3. **Heartbeat** — a long fetch (200 MB cap!) can outlive a short TTL. Procrastinate's answer
   **[FACT]**: workers refresh a heartbeat *"every 10 seconds by default"*, and a worker is
   considered stalled after *"30 seconds by default"*.
4. **Reaper** — Procrastinate's documented recipe **[FACT]**:
   ```python
   @app.periodic(cron="*/10 * * * *")
   @app.task(queueing_lock="retry_stalled_jobs", pass_context=True)
   async def retry_stalled_jobs(context, timestamp):
       for job in await app.job_manager.get_stalled_jobs():
           await app.job_manager.retry_job(job)
   ```
   https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html
   Note the `queueing_lock` — the reaper is itself guarded against concurrent runs.
   **[INFER]** In GS this is a Dagster schedule, and it should be *the same sensor* as the
   existing 45-minute zombie reaper, not a second one.

### The libraries

| Library | Licence | Latest (date) | Stars | Mechanism | Fit for a SQLAlchemy/Dagster shop |
|---|---|---|---|---|---|
| **pgqueuer** | MIT | **v1.3.2, 2026-07-27** | 1,522 | **[FACT]** README: *"workers claim jobs with `FOR UPDATE SKIP LOCKED` (never double-processed), with per-entrypoint limits and serialized dispatch"*; *"`LISTEN/NOTIFY` wakes workers the moment a job lands (with a polling fallback)"*; cron + `execute_after`. Drivers: asyncpg and psycopg (`pgqueuer/db.py`, `adapters/`). `pgq install` creates its own tables. | **The cleanest reference implementation to read.** But it owns its own schema and worker loop — adopting it means a second orchestrator beside Dagster. **[INFER] Read `pgqueuer/queries.py`, do not import it.** |
| **procrastinate** | MIT | **3.9.0, 2026-06-20** | 1,378 | **[FACT]** `SELECT FOR UPDATE` to *"lock the impacted rows, and ensure no other process can edit the same row"*; LISTEN/NOTIFY plus `fetch_job_polling_interval`; per-job `lock` so *"if a group of jobs share the same lock, then only one can be executed at a time"*; heartbeat + `get_stalled_jobs()` + documented reaper. Psycopg-based connector. | **The best documentation of the heartbeat/reaper half.** Its **per-job lock is directly analogous to a per-host politeness lock** — *"only one can be executed at a time"* is exactly the per-host serialisation Heritrix and Mercator enforce. **[INFER] The single most transferable idea in this section.** |
| **pgmq** | **PostgreSQL licence** | **v1.13.0, 2026-09-07** (released the day of this research) | 5,230 | **[FACT]** *"Guaranteed 'exactly once' delivery of messages to a consumer within a visibility timeout"*; SQS/RSMQ API parity; FIFO with message-group keys; archive-instead-of-delete. Supports PG 14–18. **Crucially: it installs either as a Rust extension *or* SQL-only — `psql -f pgmq-extension/sql/pgmq.sql` — "Use this method if you are running someplace that does not natively support the PGMQ Extension."** | **[FACT]** `pgmq` does **not** appear in Neon's supported-extensions doc (0 matches in `neondatabase/website` `pg-extensions.md`), but the SQL-only install path means that does not block it. **[INFER]** The **visibility timeout is precisely the lease** GS needs, and it is the most mature statement of the semantics. The Python client `tembo-pgmq-python` is stale (0.10.0, 2025-03-31), so use the SQL functions via SQLAlchemy directly. |
| **graphile-worker** | MIT | 2,385 stars, last push 2026-08-06 | — | TypeScript reference implementation of the same pattern. | **Reference only** — wrong language. |

**Recommendation [INFER]:** **build the lease in GS's own `mine_urls` table** — do not adopt
any of these as a dependency. Reasons: (i) GS already has the table, the SQLAlchemy models,
Alembic, and Dagster schedules — every library here brings its own schema, its own worker
loop, and its own migration tool, i.e. a second orchestrator inside a container that already
runs Dagster with `max_concurrent_runs` 3–4; (ii) the frontier row is not a job payload, it
carries `page_classification`, `fetch_strategy`, `url_metadata` and B2 keys that a generic
queue would force into an opaque JSON blob; (iii) the pattern is ~40 lines of SQL. Borrow
**pgmq's visibility-timeout semantics**, **procrastinate's heartbeat intervals and reaper
recipe**, and **pgqueuer's claim statement**, all of which are readable in an afternoon.

One caution **[FACT]**: Postgres documents `SKIP LOCKED` as giving *"an inconsistent view of
the data"*. **[INFER]** That means any *count* or *progress* query GS runs against the frontier
must not use `SKIP LOCKED`, and any test asserting "exactly N rows claimed" must account for
concurrent claimants. This is also the negative fixture the estate's own doctrine demands: a
lease test with **one** worker is unfalsifiable — stand up two concurrent claimants and assert
the intersection of their claimed id sets is empty, then mutate `SKIP LOCKED` away and watch
it go red.

---

## 8. Ranked: what GS should borrow

Ranked by (value to GS) ÷ (cost to build), with the source of each design.

| # | Borrow | From | Why now | Rough size |
|---|---|---|---|---|
| **1** | **Lease + heartbeat + reaper on `mine_urls`** — `FOR UPDATE SKIP LOCKED` claim, `lease_expires_at`, reaper folded into the existing zombie sensor | PostgreSQL docs; pgmq visibility timeout; procrastinate 10 s/30 s + `get_stalled_jobs()`; pgqueuer's claim statement | GS#1777 is open, `status='fetching'` is defined but unused, and the watchdog *restarts the container* — every in-flight URL is currently stranded on restart. This is a live correctness hole. | ~40 lines SQL + a migration + a sensor |
| **2** | **A ceiling on robots Crawl-Delay** | Nutch `fetcher.max.crawl.delay = 30` (skip the page above it); Heritrix `respectCrawlDelayUpToSeconds = 300` | GS takes unbounded `max(5 s, crawl_delay)`. One hostile or careless `Crawl-delay: 3600` converts a foundation into a permanent drain inside a 12 h window. Silent, and currently unmeasured. | ~5 lines + a metric |
| **3** | **Per-host URL budget with error penalty** | Heritrix `queueTotalBudget` / `balanceReplenishAmount 3000` / `errorPenaltyAmount 100`; BUbiNG `maxUrlsPerSchemeAuthority`; Nutch `generate.max.count` (`count.mode=host`); Katana `MaxDomainPages` | Four independent designs agree. GS caps sitemap *discovery* but not *fetching*; a trap that survives discovery has no ceiling. The error-penalty refinement retires failing hosts automatically. | ~1 column + a check in the claim query |
| **4** | **URL-shape trap rules, applied pre-fetch** | Heritrix `PathologicalPathDecideRule` (maxRepetitions 2), `TooManyPathSegmentsDecideRule` (20), `TooManyHopsDecideRule` (20); Scrapy `URLLENGTH_LIMIT` 2083 | Pure functions of a string, zero fetch cost, and they catch the GS#1545 Liferay class *before* the 60 s deadline is spent. GS has containment (timeouts, watchdog) but no detection. | ~50 lines, one service |
| **5** | **Katana's path-position parameterisation** — normalise variable path segments (IDs, UUIDs, hashes, dates); once a position shows ≥ N distinct values, treat it as a parameter and budget 1 page per cluster | Katana `FilterSimilar` / `FilterSimilarThreshold` (default 10) / `PageContentSimilarBudget` (default 1) | The general form of every template-permutation trap GS has hit. Turns "we found this trap" into "we detect this trap class". | ~100 lines + a per-host counter |
| **6** | **Per-IP politeness alongside per-host** | BUbiNG `schemeAuthorityDelay` + `ipDelay` + `ipDelayFactor`; Nutch `fetcher.queue.mode=byIP` | 300k small foundations means heavy shared-host concentration (Squarespace/Wix/GoDaddy). `Semaphore(24)` can legitimately point 24 concurrent requests at one IP from GS's single static egress IP — the most likely cause of a blanket block, and invisible today. | resolve + cache IP, second delay gate |
| **7** | **`BlockQueueUntil` and `DeleteQueue` as frontier verbs** | URLFrontier 2.6 API | Gives 429/`Retry-After`, Cloudflare challenges, and robots-fetch failure a *single* correct home (block the host until T) instead of per-call-site handling, and gives "retire this host" a name. | ~2 service methods |
| **8** | **Latency-adaptive delay, floor-preserving** — `delay = clamp(factor × last_latency, 5.0, cap)` | IIR/Mercator **10×**; Heritrix `delayFactor 5.0` + `[3 s, 30 s]`; Scrapy AutoThrottle `latency/target_concurrency` averaged | Keeps Nathan's 5 s ruling as the *floor* while adding protection for slow hosts. Note it *raises* politeness, never lowers it — so it does not touch the static-IP/throughput ruling. | ~20 lines |
| **9** | **Summarised-content digest + intra-host 64-bit simhash (Hamming 3)** | BUbiNG (strip attributes, digits, dates; seed digest with host name; intra-site by default); Manku et al. WWW'07 (64-bit, k=3); Katana `-pcsd 3` | GS hashes bytes, so a calendar widget defeats dedup and GS pays B2 + Neon for template permutations. Intra-host scoping means **no LSH index at all** — 8 bytes/page, brute-force popcount over one host's rows. | ~40 lines, one column |
| **10** | **`courlan` for URL policy + `w3lib.canonicalize_url` for the dedup key** | courlan 1.4.0 (same author as trafilatura, already a GS dep); w3lib 2.4.1 | `is_not_crawlable`, `is_navigation_page`, `is_external`, spam/tracker detection are exactly GS's URL-heuristic classifier, already written and maintained. Store canonical-as-key, fetch as-discovered. | one dependency, delete hand-rolled heuristics |
| **11** | **`filter-page-type` as an honest enum** — `error / captcha / parked / blocked / empty` | Katana `FilterPageType`; GS's own retired "blocked-as-a-data-class" mistake | The brief calls for honest classification of blocked vs empty vs down. Katana ships the vocabulary; GS learned the lesson the hard way and has no enum for it. | one enum + classifier |
| **12** | **Nutch `AdaptiveFetchSchedule` as the recrawl model** | `inc_rate 0.4` / `dec_rate 0.2` / `min 60 s` / `max 365 d` / `sync_delta_rate 0.3`, with `db.fetch.interval.default 30 d` | GS recrawl is ad hoc with no change-rate model and no conditional requests. This is a proven, tuned, two-constant algorithm. Pairs with ETag/If-Modified-Since. | ~30 lines + 2 columns |

**Explicitly do not adopt [INFER]:** Scrapy or Crawlee as frontier owner (weaker persistence,
no Crawl-delay); scrapy-redis or Brozzler (second/third container); StormCrawler (Storm
cluster + Java 25); Firecrawl self-host (five services, browser in the baseline, AGPL over a
proprietary SaaS); Frontera (dead since 2019); `ural` (GPL-3.0); Katana or Colly as a
subprocess crawler (Katana ignores robots outright; Colly's queue is in-memory);
`MinHashLSH` at crawl time (64× the storage of simhash for a question GS is not asking);
`courlan.UrlStore` as a frontier (single-writer, in-process — a downgrade from Postgres).

---

## 9. Source list

Live GitHub API pulls (2026-09-07): `scrapy/scrapy`, `rmax/scrapy-redis`,
`scrapinghub/frontera`, `apify/crawlee-python`, `apache/nutch`, `apache/stormcrawler`,
`internetarchive/heritrix3`, `unclecode/crawl4ai`, `firecrawl/firecrawl`, `gocolly/colly`,
`spider-rs/spider`, `projectdiscovery/katana`, `webrecorder/browsertrix-crawler`,
`internetarchive/brozzler`, `LAW-Unimi/BUbiNG`, `crawler-commons/url-frontier`,
`crawler-commons/crawler-commons`, `scrapy/w3lib`, `niksite/url-normalize`, `adbar/courlan`,
`adbar/trafilatura`, `medialab/ural`, `ekzhu/datasketch`, `seomoz/simhash-py`,
`seomoz/simhash-cpp`, `scrapy/protego`, `janbjorge/pgqueuer`,
`procrastinate-org/procrastinate`, `pgmq/pgmq`, `graphile/worker`.
PyPI JSON API for release dates: w3lib, url-normalize, courlan, ural, datasketch, simhash,
scrapy, crawlee, protego, reppy, pgqueuer, procrastinate, tembo-pgmq-python.

Docs and papers:
- https://docs.scrapy.org/en/latest/topics/autothrottle.html
- https://docs.scrapy.org/en/latest/topics/settings.html
- https://docs.scrapy.org/en/latest/topics/jobs.html
- https://github.com/scrapy/scrapy/issues/892
- https://crawlee.dev/python/docs/guides/storage-clients
- https://crawlee.dev/python/docs/guides/request-loaders
- https://crawlee.dev/python/docs/guides/session-management
- https://github.com/apify/crawlee-python/issues/1396
- https://github.com/apache/nutch/blob/master/conf/nutch-default.xml
- https://github.com/apache/stormcrawler/blob/master/README.md
- https://heritrix.readthedocs.io/en/latest/configuring-jobs.html
- https://heritrix.readthedocs.io/en/latest/bean-reference.html
- https://heritrix.readthedocs.io/en/latest/operating.html
- https://github.com/internetarchive/heritrix3/wiki/Politeness-parameters
- https://github.com/internetarchive/heritrix3/blob/master/engine/src/main/java/org/archive/crawler/postprocessor/DispositionProcessor.java
- https://github.com/internetarchive/heritrix3/tree/master/modules/src/main/java/org/archive/modules/canonicalize
- https://vigna.di.unimi.it/ftp/papers/BUbiNG.pdf
- https://github.com/LAW-Unimi/BUbiNG/blob/master/src/it/unimi/di/law/bubing/StartupConfiguration.java
- https://nlp.stanford.edu/IR-book/html/htmledition/the-url-frontier-1.html
- https://nlp.stanford.edu/IR-book/html/htmledition/features-a-crawler-must-provide-1.html
- https://nlp.stanford.edu/IR-book/html/htmledition/crawling-1.html
- https://research.google.com/pubs/archive/33026.pdf (Manku, Jain, Das Sarma, WWW'07)
- https://docs.crawl4ai.com/advanced/multi-url-crawling/
- https://github.com/unclecode/crawl4ai/blob/main/crawl4ai/async_crawler_strategy.py
- https://docs.firecrawl.dev/contributing/self-host
- https://github.com/firecrawl/firecrawl/blob/main/SELF_HOST.md
- https://github.com/gocolly/colly/blob/master/http_backend.go
- https://github.com/gocolly/colly/blob/master/queue/queue.go
- https://github.com/spider-rs/spider/blob/main/README.md
- https://github.com/projectdiscovery/katana/blob/main/pkg/types/options.go
- https://github.com/internetarchive/brozzler/blob/master/README.rst
- https://github.com/crawler-commons/url-frontier
- https://www.postgresql.org/docs/current/sql-select.html
- https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html
- https://procrastinate.readthedocs.io/en/stable/discussions.html
- https://github.com/janbjorge/pgqueuer/blob/main/README.md
- https://github.com/pgmq/pgmq/blob/main/pgmq-extension/README.md
- https://w3lib.readthedocs.io/en/latest/w3lib.html
- https://github.com/adbar/courlan
- https://github.com/niksite/url-normalize
- http://ekzhu.com/datasketch/lsh.html

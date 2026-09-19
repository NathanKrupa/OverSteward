# Context brief: how GrantSpider crawls today (read before researching)

GrantSpider (GS) is a Python crawler + data pipeline (httpx, SQLAlchemy, Alembic, Dagster on a
single Railway container, Neon Postgres, Backblaze B2 for page bodies). It builds a corpus of
US grantmaking foundations (~300k, IRS-derived) and government opportunities for AI Grant Helper,
a SaaS for grant writers at small nonprofits. Budget is shoestring: no paid crawling/proxy SaaS,
no metered LLM on the crawl path (page classification is URL-heuristic by ruling), Neon target
~$50/month, one static egress IP, a 12-hour daily work window (12:00-23:59 UTC) so compute can
idle. Two-person shop; operational simplicity beats capability.

## The pipeline, as built
1. **Website discovery ("resolve websites")** for foundations that have none: provider chain
   IRS 990 `WebsiteAddressTxt` -> Wikidata -> Wikipedia -> GiveFreely -> DuckDuckGo HTML scrape
   (free, no API, sent under a bare browser UA today, GS#2589) -> Brave Search API (metered
   quota; must run after DDG finishes the corpus). ~111k websiteless grantmakers remain
   (GS#1789). Mis-resolution is a live problem: another org's site or a directory listing
   (GrantWatch, aggregator pages keyed by EIN) wins over no-website-at-all (GS#2160, #2229,
   #2548). Content-level verification that the site is about the named foundation runs as a
   manual in-session Haiku drain (GS#2231), not continuously.
2. **Sitemap discovery + enumeration**: robots.txt -> `host_robots.sitemap_urls` -> recursive
   sitemap walk (depth<=10, cycle set, 60 s/foundation deadline, ~1000-URL cap) ->
   `sitemap_candidate_queue` -> `mine_urls` (per-URL crawl graph: status, discovery_method,
   content_type, url_metadata, page_classification, fetch_strategy). Crawler traps happened
   (Liferay layout-permutation sitemaps, per-show sitemaps) and once froze the Dagster daemon
   (GS#1545); the resilience epic GS#1771 threaded the deadline through recursion and added an
   external daemon watchdog. A homepage shallow-crawl fallback exists for sitemap-less sites.
3. **Fetch + snapshot**: plain GET via one httpx factory (identity, robots gate, per-host rate
   limit, circuit breaker, audit log). Politeness is a **fixed 5 s per host** (max with robots
   crawl-delay), `asyncio.Semaphore(24)` cross-domain, 200 MB body cap, 20-redirect cap with
   per-hop SSRF checks. Throughput is raised only by cross-domain concurrency (ruling: keep the
   static IP and 5 s/host). Body -> trafilatura -> markdown -> hash-addressed B2 object; the
   real "crawled" signal is `markdown_b2_key`/`markdown_snapshot_at`. Batched Neon stamping so
   multi-day drains do not hold Neon active.
4. **No headless browsers in production** (Playwright deprecated 2026-05-11; a reserved
   `GrantDiscoveryBot-Render/1.0` sub-identity exists but is unused). JS-rendered sites
   (Next/Nuxt/Apollo SPAs) yield empty markdown. Epic GS#1102 "render-class fetch routing"
   plans lanes: direct HTML / embedded-state (`__NEXT_DATA__`) + platform-API registry / archive
   fallback (Wayback first, Common Crawl CDX-index-only today, no WARC body fetch). The
   classifier is built but has zero callers (GS#2472). PDFs on foundation hosts are excluded at
   three layers and `pdf_extractor` has zero callers (GS#2469). Grant-portal vendors
   (Submittable, Foundant, Fluxx, SmartSimple, Blackbaud, WizeHive, Benevity) are never followed
   (GS#2471). A `crawlee_bridge.py` wraps Crawlee primitives (retry, session pool, concurrency)
   for the gov fetch log; the foundation path is bespoke httpx.
5. **Identity and legitimacy**: declared bot `GrantDiscoveryBot/1.0 (+https://bot.aigranthelper.com)`,
   `From: bot@aigranthelper.com`, public bot page, published IP list, rDNS planned, Cloudflare
   Verified Bots submission planned, Web Bot Auth (IETF draft) planned (GS#2586). Robots +
   crawl-delay honoured (the gate fails open on robots fetch errors). Sub-identities:
   `-Reachability` for liveness probes; a browser-shaped compatibility UA (with the bot token)
   is used against state procurement portals that 403 bot-shaped UAs (GS#2584). Rule: never
   circumvent a technical block; route to public archives instead, with guardrails. Bot-blocked
   sites (Cloudflare/Akamai challenges) are a real fraction of the philanthropic web; an earlier
   verdict class mislabelled "blocked" as a data class.
6. **Orchestration**: Dagster `DefaultRunLauncher` in one container, `max_concurrent_runs` 3-4,
   zombie-reaper sensor (45-min event-log silence), external daemon watchdog that restarts the
   container, per-run `max_runtime`. Frontier has no lease/claim (`status='fetching'` defined but
   unused; GS#1777 open). Runs must be manually launchable in-session, idempotent, DB-resumable.
   Recrawl scheduling is ad hoc (no change-rate model, no ETag/If-Modified-Since use known).
7. **Gov side**: state/federal portal connectors (AmpliFund, Submittable, Socrata, CKAN,
   grants.gov extracts, SAM.gov) as hand-written httpx clients; JS-heavy portals are the pain.

## Questions the research should answer
- Frontier and politeness design at this scale on one box: per-host queues, adaptive delay,
  lease/claim with heartbeat, trap detection, URL canonicalization and dedup, resumability.
- Whether a framework (Scrapy, Crawlee-Python, Nutch, StormCrawler, Heritrix, crawl4ai,
  Firecrawl OSS, Colly, spider-rs, Katana) would replace bespoke code well, or whether GS's
  shape (Postgres frontier, Dagster, no headless) is better served by libraries.
- Discovery without metered search: Common Crawl host/index data, Wikidata, DNS/domain
  heuristics, name->domain resolution methods, and verifying a resolved site is the right org.
- Bot legitimacy in 2026: robots libraries, Cloudflare Verified Bots and Web Bot Auth adoption,
  AI-crawler blocking defaults, how respected crawlers declare and verify themselves, and
  honest classification of blocked vs empty vs down.
- Fetching JS-rendered content without a browser: embedded-state extraction, platform
  fingerprinting (Wappalyzer-derived OSS), Wayback and Common Crawl body fetch (APIs, limits,
  WARC range reads), PDF extraction on CPU, HTML->text extraction quality comparisons,
  near-duplicate detection, conditional requests and change-rate-based recrawl.
- Orchestration: Postgres-as-queue (SKIP LOCKED) libraries, heartbeat/reaper patterns,
  checkpointing long drains, resource isolation on one container, per-host anomaly metrics.
- Domain: how Candid, Grantmakers.io, Instrumentl, Archive-It/Heritrix, Common Crawl and civic
  scrapers approach nonprofit and government sites; measured Common Crawl coverage of a sample
  of well-known foundation domains if you can probe the CC index.

Deliver evidence with URLs (docs, repos, issues, papers), note license / last release /
activity, mark inference vs documented fact, and flag bad fits and why.

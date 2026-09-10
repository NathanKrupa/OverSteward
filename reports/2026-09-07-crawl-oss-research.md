# Open-source crawling research for GrantSpider

Date: 2026-09-07. Companion to `reports/2026-09-07-search-oss-research.md`. Five lanes ran
against a brief describing GS's crawl as built (`crawl-lane1..5` and `BRIEF-CRAWL.md` in
`reports/2026-09-07-search-oss-research/`, probe scripts and result tables under
`crawl-probes/`). Three lanes took live measurements: 220 random production
`foundations.website` rows fetched twice (lane 3), 45 foundation domains across sizes
checked against Common Crawl and Wayback (lane 5), and Wikidata, Common Crawl and Brave
probed for discovery yield (lane 2). Every figure below marked "measured" comes from one of
those runs on 2026-09-07 and is a single-day observation.

## 0. Bottom line

1. **Keep the bespoke httpx stack. No framework would be an upgrade.** The only crash-safe
   per-host frontiers in the field are JVM (Heritrix, BUbiNG, Nutch). Scrapy's job directory
   corrupts on unclean shutdown, which is what GS's watchdog does on purpose; Crawlee's SQL
   storage is experimental and uses no row leases; and neither Scrapy nor Crawlee honours
   robots `Crawl-delay`, so adopting either is a compliance downgrade. GS's Postgres frontier
   is the strong part. The gaps are all inside GS's own code and each is 5 to 300 lines.
2. **Two compliance defects, both filed.** The robots gate fails open on a 5xx; RFC 9309
   requires assuming complete disallow (GS#2598). The robots crawl-delay is honoured with no
   ceiling, so one `Crawl-delay: 3600` turns a host into a one-request-per-hour drain inside a
   12-hour window; Nutch caps at 30 s and skips, Heritrix at 300 s (GS#2601). Both must be
   fixed before applying to Cloudflare Verified Bots, whose written policy names exactly
   this behaviour.
3. **The render-routing epic (GS#1102) is scoped on the wrong premise.** On 220 real
   foundation hosts, JS-rendered pages that yield no text are 0.5 percent. Blocked hosts are
   12.7 percent, and they block the browser user agent and the declared bot identically, so
   the block is fingerprint or reputation, not the UA. Meanwhile 39 percent of reachable
   hosts are WordPress and 88 percent of those serve an open `wp-json` pages API with
   per-page `modified_gmt`, and every Squarespace host answered `?format=json`. Nearly half
   the corpus has a structured lane with a server-generated change signal, and GS is not
   using it.
4. **Discovery: Brave's free tier is gone.** The API now gives $5 of monthly credit at $5
   per thousand requests, so the "DDG then Brave" chain clears about a thousand of the 111k
   websiteless grantmakers per month. The cheap replacement is an offline domain-existence
   oracle: Common Crawl's 3.46 GB domain-ranks file (free, no approval) or ICANN zone files
   (free, weeks of approval) turn name-to-domain guessing into a set-membership test that
   costs zero requests, with probes only on survivors. Wikidata is exhausted (about 0.4
   percent of the corpus). Mojeek at roughly $280 for the whole residue is the honest paid
   lane; DDG scraping is robots-clean on the host GS uses and against DDG's terms.
5. **Archive fallback: Wayback, not Common Crawl.** Common Crawl has zero captures for 7 of
   16 long-tail foundations and a median of 43 pages for county community foundations
   against 424 in Wayback. Common Crawl honours `CCBot` disallows, and Cloudflare's managed
   robots.txt is now shipping those blocks onto small foundation sites that never chose them,
   so it fails precisely on bot-blocked sites and is a decaying asset. Wayback has not
   honoured robots for archival crawls since 2017. Gate any archive fallback on capture
   recency and stamp the capture date; five of 25 small foundations were last captured in
   2025.
6. **Orchestration: the frontier lease (GS#1777) is the live correctness hole.** Dagster's
   crash detection and run resumption are documented as inert on the default run launcher,
   and Railway's healthcheck runs only at deploy time, so the external watchdog is the only
   thing that restarts a hung daemon, and when it does every in-flight URL is stranded in
   `fetching` forever. Build the lease in GS's own table with about 60 lines of SQL and a
   claim token; do not adopt a queue library. Close the outer ring with a Sentry Cron
   heartbeat from a thread that is not the crawl loop.
7. **Two decisions for Nathan.** PyMuPDF is AGPL-3.0 or commercial and is imported in six
   production modules (GS#2602). And the PDF gap (GS#2469) was never compute: 96.9 percent
   of foundation PDFs have a text layer and extract at 144 pages per second on one core.
8. **Nobody in the sector crawls foundation websites.** Candid is filings plus voluntary
   e-reporting plus a nightly read of news articles; Cause IQ is filings plus manual research
   plus LLM synthesis; Instrumentl adds 250 opportunities a week by hand. GS's crawl-derived
   corpus of what funders say about applying is genuinely differentiated. The cheap
   capability GS lacks is Candid's news-article stream.

## 1. Frameworks and frontier design

| Project | License | Frontier persistence | Robots crawl-delay | Verdict |
|---|---|---|---|---|
| Scrapy 2.18 | BSD-3 | `JOBDIR`, documented clean-shutdown only | not honoured (issue open since 2014) | borrow AutoThrottle formula only |
| Crawlee-Python 1.10 | Apache-2.0 | SQL storage client, marked experimental, no `SKIP LOCKED` | not honoured (open) | keep as a library, never as frontier owner |
| Apache Nutch 1.23 | Apache-2.0 | CrawlDb (Hadoop) | `fetcher.server.delay=5.0`, `max.crawl.delay=30` | borrow the constants |
| Heritrix 3.17 | Apache-2.0 | BDB + recovery journal, crash-safe | up to 300 s; adaptive `delayFactor=5`, 3–30 s | borrow budgets and trap rules |
| BUbiNG | Apache-2.0, dormant | sieve + workbench | per-host and per-IP delays | read the paper |
| crawl4ai, Firecrawl, Colly, spider-rs, Katana | various; Firecrawl AGPL | none durable | Katana ignores robots entirely | no; Katana's trap heuristics are the richest borrow |

Nutch's shipped default is 5 seconds per host, so Nathan's ruling is the upstream consensus.
What GS lacks, ranked by value over cost:

1. Lease, heartbeat and reaper on the frontier (§5).
2. A ceiling on robots crawl-delay (GS#2601).
3. A per-host fetch budget with an error penalty (Heritrix's `queueTotalBudget`,
   `errorPenaltyAmount`). GS caps sitemap discovery, not fetching; a host that passes
   discovery has no ceiling.
4. URL-shape trap rules applied before any fetch: repeated path segments, path depth over
   20, URL length over 2083, Katana's path-position parameterisation (a position with ten or
   more distinct values is a parameter; one page per cluster). Pure string functions that
   would have caught the Liferay case before the 60-second deadline was spent.
5. Per-IP politeness beside per-host: 24 concurrent requests from one static egress IP can
   land on one shared Squarespace or Wix IP today.
6. Latency-adaptive delay that keeps 5 s as the floor: `clamp(factor × last_latency, 5, cap)`.
7. `courlan` (same author as trafilatura, already a dependency) for URL policy and
   `w3lib.canonicalize_url` for the dedup key; store the canonical form as the key and fetch
   the as-discovered URL.
8. Intra-host 64-bit simhash over a summarised-content digest (attributes, digits and dates
   stripped) for template collapse. No LSH index needed when scoped per host.

## 2. Discovery and identity

**Discovery sources, measured.** Wikidata: 1,070 US foundations, 504 with a website; 17,221
entities carry an EIN. ProPublica's API has no website field at all. Common Crawl's CDX API
hit 503 twice in twenty queries at one request per six seconds; it is verification-only.
schema.org nonprofit markup sits at one to ten thousand domains. Certificate Transparency
organisation search found nothing useful. The recommended pipeline: normalise the name,
generate 10 to 30 candidate domains, filter against the offline domain set at zero network
cost, probe survivors, then a verification gate.

**Verification gate at resolution time.** Accept only on EIN-on-page, or name similarity
plus city and state match against ProPublica's authoritative address; anything else is
`unverified`, which is not a website. Record rejections with reasons (nomenklatura's
judgement pattern). Two cheap controls close GS#2160, #2229 and #2548: a registrable-domain
deny-list (GrantWatch, Cause IQ, ProPublica, company registries, mapquest, social profiles,
portal vendors), and an auto-detector that rejects any domain already resolved as the
website of three or more other foundations. Lane 3's random sample confirmed the pollution:
mapquest listings, state business registries and grant aggregators appear as
`foundations.website`.

**Identity.** The bot page, `ips.json` in the Google and Cloudflare prefix format, and
forward-confirmed reverse DNS are all live and verified; the brief was stale in GS's favour.
Web Bot Auth is now a chartered IETF working group (`draft-ietf-webbotauth-httpsig-protocol-00`,
2026-09-01) and Cloudflare prioritises signature-based applications; both well-known key
directory paths on the bot host currently 404. Apply to Verified Bots as `Aggregator`, never
`AI Crawler`, after fixing GS#2598, GS#2601 and the browser-shaped UA (GS#2584). Detect
Cloudflare challenges by the `cf-mitigated: challenge` header, not the status code. Harden
the homepage shallow-crawl fallback against Cloudflare's AI Labyrinth by skipping
`rel="nofollow"` and hidden links. Use `protego` (BSD, 2026-06-25) as the robots parser;
`reppy` has been unmaintained since 2019.

**Fetch-outcome vocabulary.** Blocked (challenge), blocked (WAF), paywalled (HTTP 402 is now
a live signal), empty (SPA shell with a hydration marker), down, soft-404 (compare against a
control fetch of a random path on the same host), parked. Store the evidence with the
verdict.

## 3. Fetching and extraction (measured on 220 production hosts)

| Outcome | Share |
|---|---|
| HTTP 200 | 83.2% |
| HTTP 403 to both UAs | 12.7% |
| Connection failure | 4.1% |
| 200 with SPA marker and no text | 0.5% |
| WordPress among 200s | 39.3% (87.5% serve `wp-json` pages) |
| Squarespace among 200s | 9.3% (17 of 17 answer `?format=json`) |
| Wix among 200s | 11.5% (server-rendered, 21 of 21 serve a sitemap) |
| Homepages linking a PDF | 15.8% (31 of 32 PDFs have a text layer) |
| Hosts sending ETag or Last-Modified | 53% |

Lane 5's independent 45-domain census agrees: 68 percent of county community foundations run
WordPress and 16 of 17 serve an open pages API; zero small foundations were JS-only. The
WordPress lane gives full page enumeration, body HTML free of chrome, and `modified_gmt` in
one paginated call, which sidesteps sitemap traps and supplies the recrawl signal GS has
never had. Two guardrails: honour robots against the full query-bearing URL (hewlett.org
disallows `/*?*`), and treat 401 as "API disabled" and fall through to HTML. Squarespace's
JSON is an undocumented surface; ship it with an HTML fallback.

Extraction: keep trafilatura (F1 0.924 on its own news benchmark, 0.791 on the seven-type
WCXB benchmark, where guidelines pages live). Preserve raw `<table>` HTML alongside markdown
because award ranges and deadlines sit in tables and every extractor flattens them. Do not
adopt html2text (GPL and below raw HTML on F1). Recrawl: WordPress hosts answer "did anything
change" in one request; conditional GET where a validator exists; otherwise a content
signature with StormCrawler's adaptive interval bounded 30 to 365 days, per MIME type as
Nutch does. Cho and Garcia-Molina's result that uniform refresh beats proportional refresh
argues for spending budget on first coverage of the never-crawled tail rather than chasing
frequently changing sites.

**Grant-portal vendors (GS#2471) is scoped backwards.** Vendor links appear on 1.1 percent
of foundation homepages, and Foundant, SmartSimple's applicant portal and CyberGrants all
answer `Disallow: /`. Submittable Discover exposes a public unauthenticated JSON API
(`manager.submittable.com/api/opportunities/`, robots-permitted with `Crawl-delay: 10`); I
re-verified it with one request: 1,955 live opportunities, each carrying a deadline and the
funder's own `websiteUrl`, about twenty requests for a full sweep. Detect and record the
vendor as a funder attribute from already-fetched HTML; never fetch the closed portals.

## 4. Orchestration and resilience

- Dagster's run monitoring under `DefaultRunLauncher` gives only start, cancel and max
  runtime timeouts. Crash detection and `max_resume_run_attempts` are documented as
  unsupported on it; GS's 45-minute event-log-silence sensor is the only zombie detector.
  Delete the inert config or comment why it is inert, and verify `dagster/max_runtime` by
  watching it fail a run on purpose (it is string-typed and has an open issue).
- Railway's healthcheck runs only at deploy; the restart policy fires only on non-zero exit.
  A hung daemon is restarted by nothing but the external watchdog, which nothing supervises
  (GS#1821). Close the outer ring with a Sentry Cron check-in from a thread that is not the
  crawl loop; a missed beat lands in the queue the estate already drains every session.
- Neon does not truly sleep: control-plane availability pings wake the compute 30 to 40
  times a day, giving a floor near 6 CU per day (about $19 a month per project, community-
  reported, not official). Batching writes to enable autosuspend has a bounded payoff. The
  levers that pay are staying at 0.25 CU, fewer projects, keeping churn off Neon with a local
  ledger, and auditing what touches Neon outside the work window.
- Delivery semantics are already right: hash-addressed B2 bodies make at-least-once fetches
  exactly-once in effect; the only benign hole is B2-then-stamp ordering.
- Queue libraries: procrastinate has the best heartbeat and reaper documentation and a real
  SQLAlchemy connector, but timed out under sustained pressure in the 2026 independent
  benchmark and is seeking maintainers. GS's fetch ceiling under 5 s per host is about 4.8
  URLs per second, two percent of the slowest library, so throughput is not the constraint.
  Build the lease in `mine_urls` (or a small `frontier_ready` hot table with fillfactor 85
  and a partial index on the claim predicate) and borrow pgmq's visibility-timeout
  semantics, procrastinate's 10 s beat and 30 s stall, and the canonical
  `FOR UPDATE SKIP LOCKED` claim.

## 5. Proposed lease design for GS#1777

Columns: `claimed_by`, `claimed_at`, `lease_expires_at`, `claim_token uuid`,
`heartbeat_at`, `attempts`, `last_error`, `next_eligible_at`, `priority`. Four operations:
claim (one CTE with `SKIP LOCKED`, returning the token), heartbeat (one statement per worker
per 30 s for the whole in-flight batch), complete (`WHERE claim_token = :token`, so a woken
zombie's write affects zero rows), reap (return expired leases with backoff, abandon after
three attempts, and count what was reaped). Timings: batches of 200 to 500, lease 5 minutes,
reap every 2 minutes. The claim token is what makes WSL2 suspend recovery correct rather
than tolerable. Five negative fixtures ship with it, each with the mutant that reddens it:
two workers never claim one row (remove `SKIP LOCKED`), an expired lease is reissued (remove
the expiry conjunct), a live heartbeat is not reaped (invert the comparison), a woken zombie
cannot stamp (drop the token predicate), the attempts cap terminates (remove the cap).

Prioritisation: never-crawled beats any recrawl as a hard tier; then a stored score from AG
user demand, asset size, staleness, discovery confidence and observed change rate. OPIC and
PageRank-style scores are rejected with reason: the corpus is enumerated from IRS data with
negligible inter-site links.

## 6. Recommended sequence

| Phase | Work | Issue |
|---|---|---|
| 0 | Robots 5xx = disallow; crawl-delay ceiling with skip-above-30 s | GS#2598, GS#2601 |
| 0 | Sentry Cron heartbeat off the crawl loop; delete or annotate inert `max_resume_run_attempts` | GS#1821 |
| 0 | Decide PyMuPDF licensing | GS#2602 |
| 1 | Frontier lease with claim token, reaper folded into the existing sensor, five fixtures | GS#1777 |
| 1 | WordPress `wp-json` lane, then Squarespace JSON, both robots-checked on the full URL; route on text yield | GS#1102 (comment posted) |
| 1 | Honest fetch-outcome enum with evidence; `cf-mitigated` detection; per-host status rollup | new |
| 1 | Aggregator deny-list and the "one domain, many EINs" auto-reject at resolution time | GS#2160 |
| 1 | Wire `pdf_extractor`; skip OCR; queue the under-80-chars-per-page minority | GS#2469 (comment posted) |
| 2 | Offline domain-existence oracle from Common Crawl domain ranks; file ICANN CZDS; retire Brave as a bulk lane; Mojeek for the residue | GS#1789 (comment posted) |
| 2 | Submittable Discover connector; vendor detect-and-record | GS#2471 (comment posted) |
| 2 | Per-host fetch budget, URL-shape trap rules, per-IP politeness, adaptive delay floor | GS#1771 family |
| 2 | Wayback-first archive lane, recency-gated, provenance-stamped, batched | GS#1108 |
| 3 | Web Bot Auth key directory and signing; Verified Bots application as Aggregator | GS#2586 |
| 3 | Conditional GET on recrawl plus adaptive interval; `courlan` and canonical dedup key; intra-host simhash | GS#2592 family |

## 7. Corrections and caveats

- Lane 2 measured DDG's robots: `html.duckduckgo.com` allows everything; the terms of
  service prohibit automated use. GS#2589 stands regardless.
- Lane 3 and lane 5 probes ran from the research laptop's IP, not the published egress IP,
  under a declared research UA with the bot contact address. Small volumes with polite
  pacing, but worth knowing if a webmaster diffs logs against the bot page.
- Lane 4's Neon floor figure comes from a community discussion answered by Neon staff, not
  documentation.
- Lane 3's sample is one random draw of 220 rows, homepages only; deep pages may be more
  JS-heavy. None of its conclusions turn on a margin narrower than a factor of five.
- All three measured lanes noted that their samples include mis-resolved non-grantmakers,
  which biases platform mix toward the general small-org web.

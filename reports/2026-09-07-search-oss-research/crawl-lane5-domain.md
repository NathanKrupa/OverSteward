# Crawl Lane 5 — How others crawl the nonprofit, foundation and gov-grant web

*And what the public archive record actually holds for small foundation sites.*

Research date: 2026-09-07. All probes read-only. No repository was modified.

**Evidence key** — every claim below carries one of:
- **[M]** *measured* — I ran the query in this session; the exact command and raw output
  are in `scratchpad/search-research/lane5/`.
- **[D]** *documented* — stated by the party itself or a citable source; URL given.
- **[I]** *inference* — my reasoning over [M]/[D]. Argue with these.

Raw artefacts (all under `…/scratchpad/search-research/lane5/`):
`domains.txt`, `cc_probe.sh`, `cc_results.tsv`, `wb_probe.sh`, `wb_results.tsv`,
`platform_probe.sh`, `platform.tsv`, `wp_probe.sh`, `wprest.tsv`, `agg.py`,
plus `raw/`, `rawwb/`, `rawhp/` response bodies.

---

## 0. The one-paragraph answer

Nobody in this sector crawls foundation websites at GS's intended scale, and the two
who come closest say so explicitly: **Candid crawls almost nothing** (three streams:
990 filings, voluntary e-reporting, and a nightly *news-article* read — web scraping is
named as a minor "early signal" source), and **Instrumentl does not crawl either — it
pays humans** to watch a few hundred sources. The measured web-archive record says
archive fallback is a **real but partial** lane: 43/45 sampled foundation domains
appear in Common Crawl and 44/45 in the Wayback Machine, but the *depth* collapses at
the small end (median 43 CC pages for small foundations vs 1000+ for large), and the
freshest capture for a small foundation is typically months old. The two most
consequential measured findings are structural: **Cloudflare's managed robots.txt is
now shipping CCBot/GPTBot/ClaudeBot blocks onto small community-foundation sites that
never chose them**, and **68% of the small-foundation sample runs WordPress**, 16 of
those 17 sites serving an open, unauthenticated `wp-json` REST API — a cheap, high-yield lane GS is not using.

---

## 1. Systems table — who gathers what, and how

| System | What it holds | Does it crawl foundation sites? | How "how to apply" content arrives | Published bot identity / ethics | Evidence |
|---|---|---|---|---|---|
| **Candid** (Foundation Directory / FDO) | 17M+ grants back to 1956; ~80k US foundations | **Barely.** Three named streams: (1) 990 tax filings, (2) voluntary e-reporting by >1,000 foundations, (3) nightly read of ~300k media articles + social, yielding ~1,000 sector news items/day. Web-scraping is described as a *minor* source used "to find early signals of giving trends before 990s are released" | Funder-supplied (e-reporting) + editorial. Not crawled at scale | **None found.** `candid.org/robots.txt` is `User-agent: * / Disallow:` (fully open) — they publish no crawler identity or bot page | [D] [candid.org/blogs/how-does-candid-collect-data-about-grants](https://candid.org/blogs/how-does-candid-collect-data-about-grants/), [5-misconceptions](https://candid.org/blogs/5-misconceptions-myths-candid-grants-data/); [M] robots.txt fetch |
| **Grantmakers.io** | Searchable IRS 990-PF e-file corpus, free forever | **No.** 100% IRS 990-PF XML from the public AWS-hosted IRS dataset, refreshed on the IRS's ~monthly cadence by automated fetch/parse/publish scripts | Not held. Grant *descriptions* come from 990-PF Part XV | Open source (Node+Mongo scripts released; now a Svelte/Cloudflare/Algolia monorepo). robots.txt only blocks `/cdn-cgi/` | [D] [github.com/grantmakers/grantmakers-next](https://github.com/grantmakers/grantmakers-next), [grantmakers.io/about/the-dataset](https://www.grantmakers.io/about/the-dataset/); [M] robots.txt |
| **Instrumentl** | ~$1B in "active" grants, foundation + gov | **No — humans.** "Hybrid approach that combines automated sourcing with a dedicated human review team… proactively monitors hundreds of grant sources and individual foundation websites"; 250+ new opportunities/week added by in-house staff; listings refreshed every 30 days | **Manual editorial extraction** from funder sites. This is the direct competitor's actual moat: labour, not crawling | robots.txt **blocks 18 named AI/data crawlers** (`anthropic-ai`, `CCBot`, `ClaudeBot`, `GPTBot`, `PerplexityBot`, `Diffbot`, `img2dataset`…) from `/grants`, `/foundations`, `/990-report`; `Crawl-delay: 10` for everyone else | [D] vendor/market descriptions; [M] full robots.txt captured in `lane5/` notes |
| **GrantWatch** | Aggregated grant listings, paywalled detail | Not disclosed; listing-shaped | Editorial | robots.txt is conventional (blocks `/admin/`, `/cgi/`, print endpoints); no AI-bot block, no bot page | [M] robots.txt |
| **Cause IQ** | Nonprofit profiles incl. grantmakers | **No web crawl of foundation sites.** "over a dozen" sources: OCR'd paper 990s, XML e-file, IRS extracts + BMF, 990-EZ/PF/N, A-133 single audits, DOL Form 5500, USASpending, College Scorecard, plus **manual research** | Manual research + **LLM synthesis**: "utilizes various LLM models from OpenAI or Mistral AI to synthesize disparate data points to create descriptions" for thin orgs | No bot page. **Their own site is Cloudflare-challenged — even `/robots.txt` returned a 403 JS challenge to a declared bot UA** | [D] [causeiq.com/help/reports-and-data/what-are-your-data-sources](https://www.causeiq.com/help/reports-and-data/what-are-your-data-sources/); [M] robots.txt 403 |
| **ProPublica Nonprofit Explorer** | 990 filings + org profiles, free API | **No.** IRS e-file + BMF | n/a | robots.txt **disallows exactly the bulk paths**: `/nonprofits/search*`, `/nonprofits/full_text_search*`, `/nonprofits/display_990*`, `/nonprofits/download-filing*`, `/nonprofits/download-xml*`. Sitemap offered for org pages. The intent is clear: use the API, do not crawl the app | [M] `projects.propublica.org/robots.txt` |
| **Open990** | Was: free 990 analytics | **Defunct as a hosted service.** `open990.org` now CNAMEs to `open990.github.io`; HTTPS fails with a GitHub Pages certificate-name mismatch | n/a | n/a — **do not build on it** | [M] DNS + TLS probe |
| **CitizenAudit** | 990 full-text search (OCR) | Filing-based, OCR-heavy | n/a | Old stack (jQuery 1.11, Bootstrap 3.3); no robots.txt served at apex | [M] fetch |
| **GivingTuesday Data Commons** | Open 990 clearinghouse + giving-behaviour data | **No.** Partnership (GivingTuesday, Aspen PSI, Charity Navigator, CitizenAudit, Urban Institute). Scripts download from IRS, clean, export CSV/Stata/SPSS; **Master Concordance File** maps 990 XML → columns; Data Lake on AWS + an MVP EIN API | n/a | Open methods by charter | [D] [990data.givingtuesday.org](https://990data.givingtuesday.org/), [data.givingtuesday.org/datasets](https://data.givingtuesday.org/datasets/), [Aspen announcement](https://www.aspeninstitute.org/news/open-form-990-data-clearinghouse/) |
| **Open States** | Bills/votes/people, 50 states + DC + PR | Yes — 50+ hand-written Python scrapers; new work in `spatula` | n/a | **GPL-3.0** (`openstates-scrapers`), MIT (`openstates-core`). Rate limit via `-r` req/min, `--retries`, `--retry_wait_seconds`, `--fastmode` cache. **No documented UA identity or crawler ethics statement.** Very active (pushed 2026-09-04, 912★) | [M] GitHub API; [D] [docs.openstates.org/contributing/scrapers](https://docs.openstates.org/contributing/scrapers/) |
| **City Scrapers** (City Bureau / Documenters) | Public-meeting records from local gov sites | Yes — Scrapy, one spider per body | n/a | **MIT**, 378★, `city-scrapers` pushed 2026-05-13, `city-scrapers-core` 2026-08-07. Ships `LegistarSpider` + `TribeSpider` vendor base classes, `ValidationPipeline` (JSON-Schema), `DiffPipeline`, and a `status` extension that renders a running/failing badge | [M] GitHub API + source read; [D] [github.com/City-Bureau/city-scrapers](https://github.com/City-Bureau/city-scrapers) |
| **Simpler.Grants.gov** (HHS) | Next-gen federal opportunity data | n/a — API-first replacement for grants.gov | REST API + replica DB + ETL from legacy grants.gov | Fully open source, public wiki | [D] [github.com/HHS/simpler-grants-gov](https://github.com/HHS/simpler-grants-gov), [wiki.simpler.grants.gov/product/api](https://wiki.simpler.grants.gov/product/api) |
| **USAspending** | Federal awards incl. grants | n/a | REST API + `/v2/bulk_download/awards/` | `fedspendingtransparency/usaspending-api`, open | [D] [github.com/fedspendingtransparency/usaspending-api](https://github.com/fedspendingtransparency/usaspending-api) |
| **Archive-It / Internet Archive** | Curated institutional web archives | Yes — Heritrix + Umbra (Standard) or Brozzler (browser) | n/a | Documented trap taxonomy, scope rules, robots handling. Since 2017 IA's archival crawls **do not honour robots.txt** by policy | [D] Archive-It Help Center (below); [D] [blog.archive.org 2017 robots policy](https://blog.archive.org/2017/04/17/robots-txt-meant-for-search-engines-dont-work-well-for-web-archives/) |
| **Common Crawl** | Open monthly web crawl + CDX index | Yes, general web | n/a | `CCBot/2.0 (https://commoncrawl.org/faq/)`, **dedicated IP ranges with reverse DNS**, ranges published as JSON at `index.commoncrawl.org/ccbot.json`, honours `User-agent: CCBot / Disallow: /` | [D] [commoncrawl.org/ccbot](https://commoncrawl.org/ccbot) |

**The headline [I]:** GS's competitors are not out-crawling it. Candid, Cause IQ,
Grantmakers.io and GivingTuesday are all **filing-first**; Instrumentl is
**human-first**. Nobody has a systematic, current, machine-read corpus of what
foundation *websites* say about applying. That is the gap GS is aimed at, and this
research found no evidence anyone else has closed it.

---

## 2. MEASURED — Common Crawl and Wayback coverage of 45 US foundation domains

### 2.1 Method (reproducible; exact queries)

**Sample construction.** 45 domains in three buckets, chosen to span the size range GS
actually crawls:

- **large (15)** — nationally known private foundations: gatesfoundation, macfound,
  hewlett, kresge, mott, fordfoundation, rwjf, packard, rockefellerfoundation, carnegie,
  kauffman, luminafoundation, wkkf, sloan, mellon.
- **mid (5)** — large community foundations: siliconvalleycf, cct (Chicago Community
  Trust), nycommunitytrust, oregoncf, seattlefoundation.
- **small (25)** — *county* community foundations drawn from a **public list**: the
  Independent Colleges of Indiana roster of Indiana community foundations
  (<https://www.icindiana.org/our-programs/lecsp/indiana-community-foundations/>), which
  names 93 foundations with websites. Indiana is the right tail to sample: it has more
  community foundations than any state (94, one per county), and they are exactly the
  shoestring grantmakers GS's users apply to. Domains sharing a host (multi-county
  foundations on `communityfoundationalliance.org`, `nicf.org`, `wvcf.com`,
  `cfpartner.org`) were de-duplicated to one each.

Full list: `lane5/domains.txt`.

**Common Crawl query** — the CDX index, three most recent monthly crawls, one request
per domain per crawl, `sleep 1.1` between requests, declared User-Agent
`GrantSpiderResearch/1.0 (one-off coverage measurement; bot@aigranthelper.com)`:

```
https://index.commoncrawl.org/{CRAWL}-index?url={DOMAIN}%2F*&output=json&limit=1000
```
with `{CRAWL}` ∈ `CC-MAIN-2026-34` (Aug 2026), `CC-MAIN-2026-30` (Jul 2026),
`CC-MAIN-2026-25` (Jun 2026) — crawl ids and date ranges read from
`https://index.commoncrawl.org/collinfo.json`. Records counted by `"urlkey"` occurrences.
**135 requests total, all HTTP 200, zero rate-limiting.** Script: `lane5/cc_probe.sh`.

**Wayback query** — two requests per domain, `sleep 1.1` between:

```
https://archive.org/wayback/available?url={DOMAIN}
https://web.archive.org/cdx/search/cdx?url={DOMAIN}&matchType=domain&from=2024
    &collapse=urlkey&fl=original,timestamp&limit=3000&filter=statuscode:200
```
90 requests. Script: `lane5/wb_probe.sh`.

**Honest caveats on my own measurement** *(these are defects I found and fixed, not
polish)*:
1. `limit=1000` (CC) and `limit=3000` (Wayback) are **caps, not counts** — cells showing
   `1000+`/`3000+` mean "at least", and 10 of 15 large foundations hit the CC cap.
2. **One request hit a Wayback `429 Too Many Requests`** (`henrycountycf.org`) and my
   first script recorded the error page's text as data. Detected by scanning every raw
   body for `<html>`, re-probed at slower pacing, corrected in place (1500 distinct URLs,
   last capture 2026-06-14). The lesson generalises: **a CDX count taken without
   asserting HTTP 200 on the body will silently count an error page.**
3. Common Crawl's own engineers say there is **no production way to measure what
   fraction of a site is crawled** — page counts are a floor, and the crawler
   deliberately revisits fast-changing pages more and slow pages less, so a low count
   conflates "not crawled" with "crawled once and judged static"
   ([commoncrawl.org/blog/measuring-crawled-coverage-of-a-website-in-common-crawl](https://commoncrawl.org/blog/measuring-crawled-coverage-of-a-website-in-common-crawl)). **[D]**

### 2.2 Per-domain results **[M]**

| # | bucket | domain | CC 2026-34 | CC 2026-30 | CC 2026-25 | CC best | WB distinct URLs (2024+) | WB last capture | platform | HTTP to our bot |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | large | `gatesfoundation.org` | **1000+** | **1000+** | **1000+** | **1000+** | 3000+ | 2026-08-27 | unknown | 200 |
| 2 | large | `macfound.org` | 830 | **1000+** | 855 | **1000+** | 3000+ | 2026-09-05 | unknown | 200 |
| 3 | large | `hewlett.org` | 14 | 11 | 12 | 14 | 3000+ | 2026-08-09 | wordpress | 200 |
| 4 | large | `kresge.org` | 563 | 843 | 526 | 843 | 3000+ | 2026-09-03 | wordpress | 200 |
| 5 | large | `mott.org` | **1000+** | **1000+** | 0 | **1000+** | 3000+ | 2026-08-22 | wordpress | 200 |
| 6 | large | `fordfoundation.org` | **1000+** | **1000+** | **1000+** | **1000+** | 3000+ | 2026-09-01 | wordpress | 200 |
| 7 | large | `rwjf.org` | **1000+** | **1000+** | 896 | **1000+** | 3000+ | 2026-09-03 | unknown?aem | 200 |
| 8 | large | `packard.org` | 713 | 799 | 779 | 799 | 3000+ | 2026-07-18 | wordpress | 200 |
| 9 | large | `rockefellerfoundation.org` | **1000+** | **1000+** | **1000+** | **1000+** | 3000+ | 2026-08-25 | wordpress | 200 |
| 10 | large | `carnegie.org` | **1000+** | **1000+** | 648 | **1000+** | 3000+ | 2026-09-06 | wordpress | 200 |
| 11 | large | `kauffman.org` | 473 | 692 | 460 | 692 | 3000+ | 2026-09-03 | wordpress | 200 |
| 12 | large | `luminafoundation.org` | 0 | **1000+** | 408 | **1000+** | 3000+ | 2026-09-04 | wordpress | 200 |
| 13 | large | `wkkf.org` | **1000+** | **1000+** | 817 | **1000+** | 3000+ | 2026-09-04 | wordpress?aem | 200 |
| 14 | large | `sloan.org` | 6 | 6 | 43 | 43 | 3000+ | 2026-08-29 | unknown | 403 |
| 15 | large | `mellon.org` | **1000+** | **1000+** | **1000+** | **1000+** | 3000+ | 2026-08-25 | unknown+next | 200 |
| 16 | mid | `siliconvalleycf.org` | 36 | 23 | 18 | 36 | 958 | 2025-10-30 | unknown?aem | 200 |
| 17 | mid | `cct.org` | 0 | 12 | 8 | 12 | 3000+ | 2026-04-21 | unknown | 403 |
| 18 | mid | `nycommunitytrust.org` | 19 | 19 | 20 | 20 | 2212 | 2026-07-27 | unknown | 200 |
| 19 | mid | `oregoncf.org` | 243 | 233 | 256 | 256 | 3000+ | 2026-09-02 | unknown | 200 |
| 20 | mid | `seattlefoundation.org` | 127 | 154 | 183 | 183 | 3000+ | 2026-08-23 | wordpress | 200 |
| 21 | small | `adamscountyfoundation.org` | 0 | 58 | 27 | 58 | 514 | 2026-07-17 | wix?aem | 200 |
| 22 | small | `bentoncf.org` | 6 | 6 | 4 | 6 | 237 | 2025-03-16 | wordpress | 200 |
| 23 | small | `blackfordcofoundation.org` | 13 | 46 | 21 | 46 | 333 | 2026-04-23 | wordpress | 200 |
| 24 | small | `browncountygives.org` | 20 | 19 | 19 | 20 | 737 | 2026-06-08 | wordpress | 200 |
| 25 | small | `casscountycf.org` | 9 | 11 | 15 | 15 | 58 | 2026-02-18 | wix | 200 |
| 26 | small | `cf-cc.org` | 4 | 0 | 0 | 4 | 307 | 2026-01-04 | duda | 200 |
| 27 | small | `daviesscountycf.org` | 0 | 0 | 0 | 0 | 16 | 2025-09-17 | wordpress | 200 |
| 28 | small | `dearborncf.org` | 0 | 135 | 105 | 135 | 540 | 2026-05-21 | wordpress | 200 |
| 29 | small | `dccfound.org` | 96 | 76 | 111 | 111 | 424 | 2026-06-06 | wix | 200 |
| 30 | small | `cfdekalb.org` | 22 | 43 | 13 | 43 | 368 | 2026-08-10 | wordpress | 200 |
| 31 | small | `greenecountyfoundation.org` | 63 | 100 | 123 | 123 | 931 | 2026-07-28 | wordpress | 200 |
| 32 | small | `hccfindiana.org` | 0 | 0 | 0 | 0 | 1732 | 2026-08-11 | unknown | 200 |
| 33 | small | `henrycountycf.org` | 345 | 429 | 88 | 429 | 1500 | 2026-06-14 | wordpress | 200 |
| 34 | small | `huntingtonccf.org` | 78 | 33 | 19 | 78 | 3000+ | 2026-08-13 | wordpress | 200 |
| 35 | small | `jasperfdn.org` | 4 | 4 | 4 | 4 | 4 | 2025-07-08 | wordpress | 200 |
| 36 | small | `jenningsfoundation.net` | 0 | 2 | 0 | 2 | 0 | — | unknown | 200 |
| 37 | small | `kcfoundation.org` | 125 | 158 | 420 | 420 | 3000+ | 2026-07-26 | wordpress | 200 |
| 38 | small | `lccf.net` | 146 | 153 | 123 | 153 | 1305 | 2026-07-24 | wordpress | 200 |
| 39 | small | `marshallcountycf.org` | 2 | 0 | 2 | 2 | 947 | 2026-01-30 | wordpress | 200 |
| 40 | small | `mccf-in.org` | 0 | 12 | 18 | 18 | 226 | 2026-06-14 | unknown | 200 |
| 41 | small | `occfrisingsun.com` | 15 | 17 | 16 | 17 | 422 | 2026-02-18 | wordpress | 200 |
| 42 | small | `owencountycf.org` | 49 | 26 | 64 | 64 | 248 | 2026-04-19 | wix | 200 |
| 43 | small | `parkeccf.org` | 90 | 119 | 118 | 119 | 1070 | 2026-06-09 | wordpress | 200 |
| 44 | small | `cfopc.org` | 14 | 5 | 8 | 14 | 424 | 2025-10-10 | wordpress | 200 |
| 45 | small | `randolphcountyfoundation.org` | 310 | 334 | 327 | 334 | 1724 | 2026-07-28 | wordpress | 200 |

### 2.3 Summary — is archive fallback realistic for small foundation sites? **[M]**

| Bucket | n | In CC (any of 3 crawls) | In the **latest** CC crawl | Absent from all 3 | Median CC pages | Wayback: any 2024+ capture | Wayback: captured in 2026 | Median distinct Wayback URLs |
|---|---|---|---|---|---|---|---|---|
| large | 15 | **15 (100%)** | 14 (93%) | 0 | **1000+** | 15 (100%) | **15 (100%)** | 3000+ |
| mid (big community fdns) | 5 | 5 (100%) | 4 (80%) | 0 | 36 | 5 (100%) | 4 (80%) | 3000+ |
| small (county community fdns) | 25 | **23 (92%)** | 19 (76%) | 2 | **43** | **24 (96%)** | 20 (80%) | **424** |
| **all** | **45** | **43 (96%)** | 37 (82%) | 2 | — | **44 (98%)** | 39 (87%) | — |

**Presence is high; depth is not.** [M] Every large foundation is in Common Crawl at the
1000-record probe cap. The small foundations are *present* 92% of the time but with a
median of **43 pages** — and 10 of 25 have **fewer than 25 pages** in their best crawl
(`jenningsfoundation.net` = 2, `marshallcountycf.org` = 2, `cf-cc.org` = 4,
`jasperfdn.org` = 4, `bentoncf.org` = 6). A grant-application page is a *single deep
page*; at 2–20 pages of coverage the odds that Common Crawl happens to hold the
"Grants / How to Apply" page rather than the homepage and a few nav targets are poor.

**Wayback is the better archive lane for the tail.** [M] 24/25 small foundations have
2024+ captures with a median of 424 distinct URLs — an order of magnitude deeper than
Common Crawl for the same sites, and 20/25 have a 2026 capture. But freshness is
uneven: `bentoncf.org` last captured 2025-03-16, `jasperfdn.org` 2025-07-08,
`daviesscountycf.org` 2025-09-17, `cfopc.org` 2025-10-10. **[I] For a "current grant
deadlines" product, a 12-to-18-month-old snapshot is not a fallback — it is a wrong
answer with a confident face.** Archive fallback should be gated on capture recency and
the served page must carry the capture date.

**Two sites are invisible to Common Crawl entirely** [M] — `daviesscountycf.org` (0
records in all three crawls; it is Cloudflare-fronted) and `hccfindiana.org` (0 in CC,
yet 1,732 distinct URLs in Wayback). **[I] Common Crawl absence is not evidence a site
is dead**; it is often evidence the site blocks CCBot or was never seeded.

### 2.4 The hewlett.org finding: robots.txt causes archive absence **[M]**

`hewlett.org` — a top-20 US foundation with a large, content-rich WordPress site
(50 KB of homepage text, 3000+ Wayback URLs) — has **11–14 pages** in each of the last
three Common Crawls. The cause is in its `robots.txt`, which I fetched directly:

- a **65-user-agent AI/data-crawler blocklist** including `CCBot`, `GPTBot`, `ClaudeBot`,
  `anthropic-ai`, `PerplexityBot`, `Google-Extended`, `Diffbot`, `FirecrawlAgent`, **and
  `Scrapy`** — `Disallow: /` with a hand-maintained allow-list of about a dozen specific
  marketing URLs;
- and for `User-agent: *` — i.e. **for GrantSpider** — `Disallow: /grants/` and
  `Disallow: /*?*`.

**[I] Three consequences GS must absorb:**
1. Common Crawl honours `CCBot / Disallow: /` **[D]** ([commoncrawl.org/ccbot](https://commoncrawl.org/ccbot)), so
   *the archive fallback fails on precisely the sites that block bots* — the correlation
   is negative, not neutral. Archive fallback is a lane for **JS-rendered** sites, not
   for **bot-blocked** sites.
2. A major funder forbids all crawlers from `/grants/`, the exact path GS wants. GS's
   rule (never circumvent) means this content is unobtainable by crawl and must come
   from filings, e-reporting, or a human. **This is a data-source design constraint, not
   a bug to route around.**
3. `Disallow: /*?*` forbids **any URL with a query string** — which includes
   `/wp-json/wp/v2/pages?per_page=1`. A WordPress-REST lane must therefore evaluate
   robots against the *full query-bearing URL*, not the path.

### 2.5 The Cloudflare managed-robots finding — the tail is being enclosed **[M]**

`rushcountyfoundation.org`, a single-county Indiana community foundation on WordPress,
serves a robots.txt that begins with Cloudflare's **Content Signals Policy** preamble
(`search` / `ai-input` / `ai-train` signals) and a block marked
`# END Cloudflare Managed Content` disallowing `CCBot`, `ClaudeBot`, `GPTBot`,
`Bytespider`, `Google-Extended`, `meta-externalagent`, and
`CloudflareBrowserRenderingCrawler` — followed by the site's own two-line Yoast rules.

**[I] This is the important structural trend in this research.** A three-person county
foundation did not sit down and decide to exclude Common Crawl; its host flipped a
default. 16 of 45 sampled domains are Cloudflare-fronted **[M]**. As that default
propagates, **Common Crawl coverage of the small-foundation tail will decay**, and any
GS plan that treats CC as a durable fallback is planning against a shrinking asset.
Wayback is more robust here — the Internet Archive has not honoured robots.txt for
archival crawls since 2017 **[D]**
([blog.archive.org](https://blog.archive.org/2017/04/17/robots-txt-meant-for-search-engines-dont-work-well-for-web-archives/)).

---

## 3. MEASURED — Web-platform composition of the foundation web, and the size of each fetch lane

### 3.1 Method **[M]**

One `GET https://{domain}/` per domain (redirects followed), declared UA, 1.2 s pacing,
45 domains. Fingerprints from response headers + body markers: `wp-content`/`wp-json`
(WordPress), `static.parastorage.com`/`X-Wix-*` (Wix), `squarespace`, `weebly`,
`irp.cdn-website.com` (Duda), `blackbaud`, `__NEXT_DATA__`/`/_next/static` (Next.js),
`__NUXT__`, `drupal-settings-json`, `/etc.clientlibs/` (Adobe AEM). "Likely JS-only" =
under 1,500 bytes of text after stripping `<script>` blocks and tags — a deliberately
conservative threshold. Script: `lane5/platform_probe.sh`; raw: `lane5/platform.tsv`.

### 3.2 Platform census **[M]**

| Platform | large (15) | mid (5) | small (25) | total (45) |
|---|---|---|---|---|
| **WordPress** | 10 (incl. 1 with AEM markers) | 1 | **17** | **28 (62%)** |
| **Wix** | 0 | 0 | **4** | 4 (9%) |
| Duda | 0 | 0 | 1 | 1 (2%) |
| Next.js (JS-rendered) | 1 (`mellon.org`, on Netlify) | 0 | 0 | 1 (2%) |
| Adobe AEM / enterprise | 1 (`rwjf.org`) | 1 (`siliconvalleycf.org`) | 0 | 2 (4%) |
| unidentified | 3 | 3 | 3 | 9 (20%) |

**Small foundations are 68% WordPress and 20% hosted site-builder (Wix/Duda).** [M]
Squarespace, Weebly, Blackbaud, Neon One, Bloomerang and NationBuilder did **not** appear
at all in this 45-domain sample — **[I] a useful negative: the donor-CRM vendors sell
donation pages, not the foundation's *public grantmaking* site.** For contrast, the
general-web baseline **[D]** (W3Techs via secondary reporting, Oct 2025) is WordPress
~43% of all sites / ~61% of CMS sites, Wix ~4.3%, Squarespace ~2.5%. **[I] Small
foundations over-index on WordPress relative to the web at large — plausibly because
they are built once by a local web shop or a board member and then left alone.**

### 3.3 The JS-only lane is small, and it is *not* in the tail **[M]**

Only **4 of 45** domains returned under 1,500 bytes of text: `sloan.org` (403),
`cct.org` (403), `nycommunitytrust.org` (291 bytes), `mellon.org` (Next.js, 1,366 bytes).
**Zero small foundations were JS-only.** Even the Wix sites returned very large HTML
bodies (`casscountycf.org` 621 KB, `dccfound.org` 515 KB, `owencountycf.org` 489 KB) —
**[I] Wix server-renders enough content that a text extractor gets real prose, though the
markup is hostile and Archive-It names Wix URL tokens as a crawler-trap class (§5.1).**

### 3.4 Bot-blocking rate against a declared, honest bot **[M]**

43/45 domains returned 200 to `GrantSpiderResearch/1.0`. **2 returned 403** — `sloan.org`
and `cct.org`, both Cloudflare-fronted, both returning a 513-byte challenge stub. A third
(`cfopc.org`) returned **403 on `/robots.txt`** while serving its homepage 200 — **[I] a
nasty edge case: a robots gate that fails *open* on a 403 will crawl a site whose policy
it never read, and one that fails *closed* will skip a site that is perfectly willing.
GS's gate currently fails open on robots fetch errors; this case argues for
distinguishing 403-challenge from 5xx and recording the distinction rather than
collapsing both to "no robots."**

**[I] ~4–7% hard bot-blocking of declared crawlers** on this sample. Materially lower
than the anxiety in the brief suggests, and concentrated in **large/mid** foundations,
not the tail.

### 3.5 The WordPress REST API lane — measured **[M]**

For all 28 WordPress-fingerprinted domains I requested `/wp-json/`,
`/wp-json/wp/v2/pages?per_page=1` and `/wp-json/wp/v2/posts?per_page=1`, reading the
`X-WP-Total` header. Script: `lane5/wprest_census.sh`; raw: `lane5/wprest_final.tsv`.

| Result | count |
|---|---|
| WordPress-fingerprinted domains probed | **28** |
| `/wp-json/` returns 200 | **27 (96%)** |
| `wp/v2/pages` returns 200 (open, unauthenticated) | **24 (86%)** |
| `wp/v2/pages` returns 401 (REST locked down) | 4 (`kresge.org`, `fordfoundation.org`, `luminafoundation.org`, `cfdekalb.org`) |
| **small-foundation WordPress sites with an open `wp/v2/pages`** | **16 of 17 (94%)** |
| Total pages enumerable across the open sites (`X-WP-Total`) | **1,412 pages + 3,507 posts** |

Examples: `henrycountycf.org` 120 pages / 602 posts; `parkeccf.org` 77 / 38;
`randolphcountyfoundation.org` 68 / 132; `dearborncf.org` 76 / 228; `kcfoundation.org`
55 / 209; `hewlett.org` 57 / 866.

**[I] This is the most actionable finding in the report.** For 16 of 17 small WordPress
foundations, GS can obtain a **complete, paginated, machine-readable inventory of every
page with its rendered content, its permalink and its `modified` timestamp in two HTTP
requests** — replacing robots + sitemap-walk + N page fetches + trafilatura, and handing
GS the change-rate signal it has never had (brief §6: "no ETag/If-Modified-Since use
known", "recrawl scheduling is ad hoc"). The `modified` field *is* a change-rate model.

**Caveats [M]/[I]:** (a) 4 sites return 401 — fall through to HTML, do not retry;
(b) `hewlett.org`'s robots `Disallow: /*?*` forbids the `?per_page=` form for
`User-agent: *`, so **the robots check must be run against the full query-bearing URL**,
and a `per_page`-free path form used where possible; (c) `X-WP-Total` counts *published*
objects, so it is a coverage denominator GS can assert against — a sitemap that yields
far fewer URLs than `X-WP-Total` is a measurable sitemap defect.

---

## 4. Civic-tech and government scrapers — what is actually reusable

### 4.1 City Scrapers (City Bureau / Documenters) — **the closest architectural analogue to GS** **[M]/[D]**

MIT-licensed, Scrapy-based, 378★, `city-scrapers` last pushed 2026-05-13,
`city-scrapers-core` 2026-08-07 **[M via GitHub API]**. Four patterns are directly
transferable, and one of them answers a live GS question.

**(a) Vendor base-spiders, not per-site spiders.** `city_scrapers_core/spiders/` holds
exactly three things: `spider.py` (the base), `legistar.py`, and `tribe.py`. Legistar is
the dominant municipal agenda vendor; Tribe is The Events Calendar WordPress plugin. A
new city body becomes a ~30-line subclass. **[I] This is the shape GS#2471 wants for
grant-portal vendors** (Submittable, Foundant, Fluxx, SmartSimple, WizeHive): one
`SubmittableSpider`-equivalent amortised across thousands of foundations, rather than a
generic crawler that treats every portal as a novel site.

**(b) A JS-looking portal handled with pure HTTP.** Legistar is ASP.NET WebForms — it
looks browser-only. `LegistarSpider.parse()` does **not** use a browser: it calls
`_parse_secrets(response)` to lift `__VIEWSTATE`/`__EVENTVALIDATION`, then issues a
`POST` with `__EVENTTARGET: ctl00$ContentPlaceHolder1$lstYears` and
`ctl00_..._lstYears_ClientState: {"value":"<year>"}` to walk years, and a second
postback to page. **[I] Directly relevant to GS's "JS-heavy vendor portals" pain
(brief §7): a large share of "JS-heavy" gov portals are postback or XHR-backed, and the
fix is form-state replay or hitting the JSON endpoint, not a headless browser.** GS
deprecated Playwright; this is the evidence that the deprecation is survivable.

**(c) Scraper health is a first-class pipeline stage.** `pipelines/validation.py` is a
`ValidationPipeline` that validates every item against a Draft-7 JSON schema, counts
errors per field across the run, and emits a validation report at `close_spider`, gated
by a `CITY_SCRAPERS_ENFORCE_VALIDATION` setting. `pipelines/diff.py` handles change
detection against previously-scraped items. `extensions/status.py` tracks
`running`/`failing` per spider and renders an SVG status badge. **[I] GS has per-host
metrics on its list; this is the cheap version — a schema assertion on extracted output
plus a per-source running/failing flag catches "the site redesigned and we now extract
nothing" which a fetch-level 200 will never catch.** This is the same defect class as
the estate's false-green rule: a 200 with empty extraction is a silent failure.

**(d) Community maintenance model.** Open States says it plainly: "Scrapers do break."
Neither project automates recovery; both make breakage *visible* and rely on people.
**[I] For a two-person shop the transferable half is the visibility, not the volunteers.**

### 4.2 Open States **[M]/[D]**

912★, pushed 2026-09-04 — the most actively maintained scraper corpus in US civic tech.
50+ state modules; newer work uses `spatula` in `scrapers_next/`. Rate limiting is a CLI
concern (`-r` requests/minute, `--retries`, `--retry_wait_seconds`, `--fastmode` to use
cache and disable throttling in dev).

**Two flags for GS:**
- **`openstates-scrapers` is GPL-3.0** **[M via GitHub API]** while `openstates-core` is
  MIT. **[I] Lifting scraper code from `openstates-scrapers` into GS would raise a
  copyleft question for a commercial SaaS. Read it for technique; do not vendor it.**
- The contributing docs contain **no user-agent, identity, or crawler-ethics guidance
  at all** **[D]**. **[I] GS's declared-bot posture (GS#2586) is already more
  responsible than the leading open civic-tech scraper. That is a marketable fact for
  the bot page, and a reason not to assume the sector has a norm GS is failing.**

### 4.3 Government portals — prefer the documented API every time **[D]**

| Portal type | Reusable open component | License / status |
|---|---|---|
| Socrata | `sodapy` — Python client for the Socrata Open Data API | open; the canonical client |
| CKAN | `ckanapi` — official CKAN action-API wrapper; CKAN powers `catalog.data.gov`, `open.canada.ca/data`, HDX | open |
| grants.gov (federal) | **`HHS/simpler-grants-gov`** — API-first successor; replica DB + ETL from legacy grants.gov + documented REST search; public wiki | US Gov open source |
| USAspending | `fedspendingtransparency/usaspending-api` + `/v2/bulk_download/awards/` | open |
| Legistar (municipal) | `City-Bureau/city-scrapers-core` `LegistarSpider` | MIT |
| **AmpliFund / Bonfire / BidNet** | **Nothing open found.** Only commercial Apify actors (`jungle_synthesizer/bidnetdirect-government-bids-scraper`, `parseforge/governmentbids-scraper`); `dobtco/openrfps-scrapers` is old and narrow | — |

**[I] The gap is real and unsurprising:** state grant/procurement portals are vendor SaaS
with no open-data mandate, so no civic-tech community formed around them. GS's
hand-written connectors are not a failure to find prior art — there is none. The
leverage is to write them as **vendor base-classes** (§4.1a), because AmpliFund and
Submittable instances are near-identical across states, and to check for a JSON/XHR
endpoint before assuming a browser is needed (§4.1b).

---

## 5. Archive-It / Heritrix / Internet Archive — the crawl-operations doctrine

*(Note: `support.archive-it.org` returns a Cloudflare JS challenge (403) to a declared
bot UA. **[M]** I read these articles through the Wayback Machine — the archive fallback
pattern GS is planning, exercised on the archive's own documentation. The irony is
instructive: the Cloudflare challenge is the dominant failure mode, and Wayback is the
working answer to it.)*

### 5.1 Crawler traps — the documented taxonomy **[D]**

From [How to identify and avoid crawler traps](https://support.archive-it.org/hc/en-us/articles/208332943)
(updated 2025-11-01):

> "A crawler trap is a set of web pages that create an infinite number of documents
> (URLs) for our crawler to find… Crawls have maximum time limits that will stop them
> after a certain length of time. These traps can still archive quite a lot of content
> prior to the time limit, so avoiding traps is a key part of effectively managing your
> time and your data budgets."

**Detection signal:** the **Hosts report** — "especially high numbers of *Queued*
documents from any particular host." The operator clicks through to the queued-URL list
and looks for a pattern.

**The named trap classes**, with GS relevance:
| Trap class | Example shape | GS relevance |
|---|---|---|
| **Long messy strings** | `/-4RKgHfoN-6E11VCLhJOgPe79POuU2ZXhnTVbnUg_Zs.eyJpbnN0YW5jZUlkIjoi…` | **Explicitly identified as "indicative of a site created using the Wix platform."** Archive-It maintains a separate *Archiving Wix Sites* article. **4 of 25 small foundations in my sample are Wix [M]** |
| **Repeating directories** | `/media/media/page/sites/css/html-reset.css` | classic relative-link bug; Heritrix `PathologicalPathDecideRule` |
| **Extra directories** | `/media/feed/pae/sites/all/themes/dev/custom/sites/all/themes/…` | `TooManyPathSegmentsDecideRule` |
| **Calendars** | `/calendar/events?&page=1&mini=2015-09&mode=week&date=2021-12-04` | infinite forward/backward date generation; Archive-It ships a regex to exclude all calendar content |

Heritrix's own rules: `PathologicalPathDecideRule`, `TooManyPathSegmentsDecideRule`,
`TooManyHopsDecideRule` (hop distance from seed) **[D]**
([crawler.archive.org user manual](http://crawler.archive.org/articles/user_manual.pdf)).

**[I] Map to GS's actual trap incidents.** GS's Liferay layout-permutation and per-show
sitemap traps (GS#1545, GS#1771) are the "long messy strings" and "calendar" classes.
GS's mitigation was a **time deadline threaded through recursion** — which is the same
control Archive-It relies on ("crawls have maximum time limits"), and Archive-It is
explicit that **a deadline is damage control, not a fix**: the trap still consumes the
budget up to the limit. The missing controls GS does not have are (a) **the Hosts report
equivalent** — a per-host queued-URL count that a human can eyeball — and (b) a
**named, versioned exclusion pattern list** (repeating/extra path segments, calendar
query params, Wix token paths) applied at frontier-admission time.

### 5.2 Scope, politeness, robots — the operator's contract **[D]**

From [Archive-It Crawling Technology](https://support.archive-it.org/hc/en-us/articles/115001081186):

- **Standard crawl = Heritrix + Umbra.** Heritrix crawls all seeds *simultaneously*,
  cycling through hosts — so "crawls of hundreds of seeds can be slower than crawls of
  fewer seeds." **[I] Exactly GS's `asyncio.Semaphore(24)` cross-domain model, and
  the same reason GS's throughput lever is cross-domain concurrency, not per-host rate.**
- **Umbra is the key architectural idea.** Umbra sends *only the seed/initial pages* to a
  browser, in a **separate process**, purely so client-side script executes and
  "previously unavailable URLs can be detected **for Heritrix to crawl**." Heritrix still
  does all fetching, WARC writing, dedup, scope rules and reports. **[I] This is the
  answer to GS's no-headless-browsers constraint (Playwright deprecated 2026-05-11, the
  reserved `GrantDiscoveryBot-Render/1.0` identity unused): a browser used only as a
  *URL-discovery oracle* on a handful of entry pages per site is a different cost
  profile from a browser used as the fetch path. It is bounded, cacheable, and runs
  out-of-band — it need not sit in the 12-hour work window at all.** Brozzler (full
  browser records every interaction) is the expensive option Archive-It reserves for
  genuinely dynamic/multimedia content.
- **Robots is honoured by the crawler and named as a first-class reason for capture
  failure**, alongside IP-range blocks and rate-limit directives. Heritrix's
  preconditions include having fetched robots.txt for the URI **[D]**.
- **Failure honesty:** Archive-It lists SSL-certificate problems and server errors as
  distinct causes of non-capture. **[I] Reinforces GS's own hard-won lesson that
  "blocked" is not a data class — Archive-It's operator UI separates *scoped out*,
  *robots-excluded*, *queued* and *failed*, and GS's `mine_urls` should too.**
- **Internet Archive's Wayback crawls do not honour robots.txt** for archival purposes
  (2017 policy) **[D]** — the reason §2.3 shows Wayback covering small sites far more
  deeply than Common Crawl.

### 5.3 Are there Archive-It collections targeting US foundations? **[D], partial**

Yes, but they are **institutional self-archives and Candid's own material, not a
sector-wide crawl**:
- **Candid** (Foundation Center + GuideStar) maintains an Archive-It account; its
  archived properties include **GlassPockets**, the philanthropic-transparency initiative
  (launched 2010, roots to 1956), and **IssueLab**, an aggregated collection of
  foundation reports/impact studies/datasets. See
  [ff2023.archive.org/home/candid](https://ff2023.archive.org/home/candid) (the page
  returned no text to a scripted fetch **[M]**; content confirmed via search results).
- The **Rockefeller Archive Center** holds the largest philanthropic records collection
  in the world, including Foundation Center's own records, and partners with Candid on
  preserving nonprofit knowledge ([candid.org/blogs/issue-lab-rockefeller-archive-center](https://candid.org/blogs/issue-lab-rockefeller-archive-center/)).
- **Advancing Foundation Archives** ([archivingphilanthropy.org](https://www.archivingphilanthropy.org/resources/))
  is a sector project about foundations archiving *themselves*.

**[I] There is no curated web archive of US foundation grant pages.** The general Wayback
Machine is the only broad capture, and §2.3 measures what it holds. Nobody has done for
foundation websites what Archive-It curators do for government transitions.

---

## 6. Ethics and law — what a 2026 bot policy should say

### 6.1 Where US law stands **[D]**

- **CFAA does not reach public-page scraping.** *hiQ Labs v. LinkedIn*, 9th Cir., 2019,
  reaffirmed April 2022 after remand from *Van Buren*: accessing a public website is not
  "without authorization." EFF: using automated scripts to access publicly available
  data is not hacking, and neither is violating a site's terms of use
  ([eff.org/deeplinks/2022/04/scraping-public-websites-still-isnt-crime-court-appeals-declares](https://www.eff.org/deeplinks/2022/04/scraping-public-websites-still-isnt-crime-court-appeals-declares)).
- **Contract survives.** In November 2022 LinkedIn won summary judgment on **breach of
  contract** — hiQ had *accepted* LinkedIn's user agreement. The six-year case then
  settled confidentially. Scraping public data is not a crime; scraping in violation of
  terms **you agreed to** is a contract breach
  ([Jenner & Block client alert](https://www.jenner.com/en/news-insights/publications/client-alert-data-scraping-in-hiq-v-linkedin-the-ninth-circuit-reaffirms-narrow-interpretation-of-cfaa),
  [zwillgen.com](https://www.zwillgen.com/alternative-data/hiq-v-linkedin-wrapped-up-web-scraping-lessons-learned/)).
- ***Meta v. Bright Data* (2024)** declined to block logged-out scraping of public
  Facebook/Instagram pages — same line, reinforced.

**[I] The operative rule for GS: never create the contract.** Do not click through,
register for, or authenticate to a foundation's or portal's site; do not accept terms.
An unauthenticated GET of a public page is on the safest ground US law currently offers.
The moment a connector logs into AmpliFund or Submittable, the analysis changes from
CFAA (favourable) to contract (unfavourable). *This is not legal advice; it is the shape
of the risk.*

### 6.2 Research-ethics frameworks worth citing on the bot page **[D]**

- **The Menlo Report** (DHS, 2012) — the adopted ethical framework for network
  measurement: respect for persons, beneficence, justice, respect for law and public
  interest ([caida.org PDF](https://www.caida.org/catalog/papers/2012_menlo_report_actual_formatted/menlo_report_actual_formatted.pdf)).
- **Brown, Gruen, Maldoff, Messing, Sanderson & Zimmer (2025)**, "Web scraping for
  research: legal, ethical, institutional, and scientific considerations," *Big Data &
  Society* ([journals.sagepub.com/doi/10.1177/20539517251381686](https://journals.sagepub.com/doi/10.1177/20539517251381686))
  — transparency, data minimisation, privacy risk assessment.
- **Thelwall & Stuart**, "Web crawling ethics revisited: cost, privacy, and denial of
  service" (*JASIST*) — the foundational cost-to-the-publisher argument.
- **Navigating the Ethics of Internet Measurement** (arXiv 2511.10408, 2025) — current
  survey; notes nearly all measurement researchers apply rate limits as the primary
  ethical control.

### 6.3 What GS's published bot policy should say **[I]**

GS's identity work (declared UA, `From:` header, bot page, published IPs, planned rDNS,
Cloudflare Verified Bots, Web Bot Auth) is already above the sector norm. The measured
gaps against best practice:

1. **Publish the IP list as machine-readable JSON at a stable URL and ship rDNS**, as
   Common Crawl does (`index.commoncrawl.org/ccbot.json`, `*.crawl.commoncrawl.org`
   PTR) **[D]**. A prose list on a bot page cannot be used by an ops team writing an
   allow-rule at 2am; a JSON file can. rDNS is what makes the allow-rule *safe* — CC
   explicitly warns that crawlers falsely identify as CCBot.
2. **State the crawl budget numerically** — "no more than one request per 5 seconds per
   host, at most N pages per site per month" — because that is the promise a webmaster
   can verify from their own logs.
3. **State the purpose and the beneficiary**: surfacing public grant information for
   small nonprofits. Foundations exist to be found by grantseekers; GS is closer to a
   search engine than to a data broker, and the bot page should make that argument
   because it is true and because it is the argument that gets an allow-rule written.
4. **State what GS will never do**: no authentication, no terms acceptance, no
   circumvention of a technical block, no ignoring robots, no PII harvesting. GS already
   holds this rule internally; publishing it is what makes it a *credential*.
5. **Offer a removal path** — a named address and an SLA. The Internet Archive does this
   (`info@archive.org`) and it is the single cheapest way to convert a complaint into a
   configuration change instead of a blocklist entry.
6. **[I] Do not claim archive fallback is "non-invasive" without qualification.** If a
   site blocks CCBot and GS serves Common Crawl content anyway, the *publisher's
   expressed preference* has been routed around even though no technical control was
   circumvented. §2.4 shows this is not hypothetical. The defensible line: **use archives
   for sites GS cannot *render*, not for sites that have told crawlers to go away.**
   Record which of the two reasons applied on every archive-sourced row.
---

## 7. Ranked transferable lessons for GrantSpider

Ranked by *value ÷ cost to GS specifically*, given: shoestring budget, two people, one
box, no headless browser, no LLM on the crawl path, 12-hour work window.

---

### 1. Build the WordPress REST lane. It is the single highest-yield thing in this report. **[M]**
**Evidence:** 21/28 WordPress foundation sites answer `/wp-json/` with 200; ~4 in 5 serve
an unauthenticated `wp/v2/pages` collection with an `X-WP-Total` header. **[I] Cost:** a
few days for a connector that, per site, replaces a robots fetch + sitemap walk + N page
fetches + trafilatura with **two requests and a JSON parse** — clean text in
`content.rendered`, a `link` per page, and a `modified` timestamp that is a *free
change-rate signal* GS currently lacks entirely. Guardrails: honour robots against the
**query-bearing URL** (§2.4); treat `401` as "site disabled the API" and fall through to
HTML; the `?per_page=` query string may itself be `Disallow`ed.

### 2. Adopt Archive-It's Umbra shape rather than reviving Playwright as a fetcher. **[D]/[I]**
A browser used **only to discover URLs from a handful of entry pages, in a separate
out-of-band process**, feeding the normal httpx fetch path, is a categorically different
cost from a browser in the fetch loop. It is bounded (N pages/site, not all pages), it
runs outside the 12-hour window, and it leaves the fetch path, identity, robots gate and
rate limiter untouched. **[M] The lane is small:** only 4/45 sampled sites are plausibly
JS-only (`sloan.org`, `mellon.org`, `cct.org`, `nycommunitytrust.org`) — 9%, all
mid-or-large. **[I] Do not build render routing for the small-foundation tail; it does
not need it.** GS#1102's classifier having zero callers (GS#2472) is arguably correct
prioritisation, not a defect.

### 3. Make archive fallback recency-gated and provenance-stamped, and prefer Wayback over Common Crawl for small sites. **[M]**
Wayback holds ~10× the distinct URLs of Common Crawl for the same small foundations
(median 424 vs 43) and, unlike CC, does not honour robots for archival crawls. But 5/25
small foundations were last captured in 2025. **[I] Rules:** (a) never serve archived
grant content without the capture date on the record and on the page; (b) refuse archive
fallback past a max-age (90 days for deadline-bearing content is a defensible start);
(c) record **why** the archive was used — `render_failed` vs `bot_blocked` — because
only the first is ethically clean (§6.3.6).

### 4. Treat Common Crawl as a *decaying* asset, and never as evidence of a site's state. **[M]**
Cloudflare's managed robots.txt is now shipping `CCBot`/`GPTBot`/`ClaudeBot` blocks onto
county community foundations that never asked for them (`rushcountyfoundation.org`), and
16/45 sampled domains are Cloudflare-fronted. `hewlett.org` — a huge, healthy site — has
14 pages in CC because it blocks CCBot. `hccfindiana.org` has 0 CC pages and 1,732
Wayback URLs. **[I] Any GS logic of the form "absent from CC ⇒ site is dead/thin" is
wrong today and will get more wrong.** Use CC for URL *discovery* hints only, never for
liveness or completeness.

### 5. Copy the vendor base-spider pattern for grant portals (GS#2471). **[M]/[D]**
`city-scrapers-core` ships three spiders — a base, `LegistarSpider`, `TribeSpider` — and
every municipality is a thin subclass. **[I] GS should have `SubmittableConnector`,
`FoundantConnector`, `FluxxConnector` etc. as base classes with per-foundation
configuration, not a generic crawler pointed at portal URLs.** The economics are the same
as City Bureau's: one vendor integration amortised over thousands of sites is the only
version a two-person shop can maintain.

### 6. Assume "JS-heavy" gov portals are postback/XHR before assuming they need a browser. **[M]**
`LegistarSpider` walks an ASP.NET WebForms portal with pure HTTP by lifting `__VIEWSTATE`
and POSTing `__EVENTTARGET`. **[I] Before writing off AmpliFund/Bonfire/BidNet as
browser-only, check for (a) a JSON/XHR endpoint the page calls, (b) form-state replay,
(c) an `__NEXT_DATA__`-style embedded state blob.** GS's own embedded-state lane
(GS#1102) is the right instinct; extend it to form-state replay.

### 7. Add a Hosts-report equivalent and a named trap-exclusion list. **[D]/[I]**
Archive-It's operator control for traps is not a timeout — it is a **per-host queued-URL
count** a human eyeballs, plus curated exclusion regexes for the four named trap classes
(long opaque tokens/Wix, repeating directories, extra directories, calendars). GS has the
timeout (GS#1771) but not the visibility or the pattern list. **[I] A per-host
`sitemap_candidate_queue` depth metric with an alert threshold, plus a versioned
`TRAP_PATTERNS` list applied at frontier admission, is a day of work and would have
caught GS#1545 before it froze the daemon.** Note the Wix warning is directly on-target:
4/25 small foundations are Wix, and Archive-It names Wix URL tokens as a trap class.

### 8. Add a schema-validation stage on extracted output, not just fetch status. **[D]/[I]**
`city-scrapers-core`'s `ValidationPipeline` validates every item against a JSON schema,
counts per-field errors across the run, and reports at spider close; `extensions/status.py`
flags a source `running`/`failing`. **[I] GS's `markdown_b2_key` proves bytes were
stored, not that anything useful was extracted.** A 200 + empty/boilerplate markdown is
the estate's canonical false green. A per-source "fields extracted / items validated"
counter with a running-vs-failing flag makes site redesigns visible the week they happen.

### 9. Stop planning around a competitor crawl advantage that does not exist. **[D]**
Candid is filing + e-reporting + **news-article reading** (~300k articles nightly), with
web scraping named as a minor early-signal source. Cause IQ is a dozen filing-derived
sources plus **manual research** plus **LLM-synthesised descriptions** for thin orgs.
Instrumentl is **250+ opportunities/week added by in-house staff**. **[I] Two strategic
reads:** (a) GS's crawl-derived corpus of *what foundation sites actually say about
applying* is genuinely differentiated — nobody else has it; (b) **Candid's news-article
stream is the cheap capability GS is missing.** A nightly read of philanthropy trade
press for grant announcements is a far cheaper freshness signal than re-crawling 300k
sites, and it is how the market leader gets ahead of the 18-month 990 lag.

### 10. Publish machine-readable identity, not prose. **[D]**
Common Crawl's model is the one to copy exactly: a fixed UA string with a URL in it,
dedicated IP ranges, **reverse DNS under a crawler-specific domain**, and the ranges
published as **JSON at a stable URL** (`index.commoncrawl.org/ccbot.json`), plus an
explicit warning that impostors exist and rDNS is how to tell. **[I] GS's planned rDNS
should be prioritised above Web Bot Auth** — rDNS is deployable today and is what an
ops team can actually verify; Web Bot Auth is an IETF draft with thin adoption.

### 11. Never let a CDX/API count be taken without asserting HTTP 200 on the body. **[M]**
My own first-pass Wayback probe counted a `429 Too Many Requests` HTML page as data rows.
**[I] GS's Common Crawl CDX-index integration is exposed to exactly this**: an
`index.commoncrawl.org` 503 or a Wayback 429 will parse as "zero captures" or, worse, as
rows. Assert the status code *and* assert the body parses as the expected shape before
recording a count. This is the estate's `rc=0 is not a pass` rule in a new costume.

### 12. Do not authenticate. Ever. **[D]/[I]**
*hiQ* leaves public-page scraping outside the CFAA, but LinkedIn still **won on breach of
contract** because hiQ had accepted the terms. **[I] The moment a GS connector logs into
a portal, GS trades a favourable legal posture for an unfavourable one.** Bake this into
the connector base class as a structural constraint, not a policy document: no cookie
jar, no credential store, no login flow on the crawl path.

### 13. Do not vendor `openstates-scrapers`. **[M]**
It is **GPL-3.0**. `openstates-core` and the whole City Scrapers family are MIT and safe.
Read the GPL code for technique; do not copy it into a commercial SaaS.

### 14. Do not build on Open990. **[M]**
`open990.org` now CNAMEs to GitHub Pages and fails TLS with a certificate-name mismatch.
The hosted service is gone. The live free 990 sources are the IRS AWS dataset directly
(as Grantmakers.io uses), ProPublica's API, and the GivingTuesday Data Commons data lake
+ Master Concordance File.

### 15. Respect ProPublica's robots.txt — it is telling you to use the API. **[M]**
`projects.propublica.org/robots.txt` disallows `/nonprofits/search*`,
`/nonprofits/full_text_search*`, `/nonprofits/display_990*`, `/nonprofits/download-xml*`
— every bulk path — while offering a sitemap for org pages. **[I] The intent is legible
and the API is free; a GS connector that crawls those paths is both rude and redundant.**

---

## 8. Loose ends and things I could not measure

- **Instrumentl's actual pipeline** is not published beyond marketing copy; "hybrid
  automated + human review" is their word, not an audited fact. **[D, self-reported]**
- **Candid's scraping volume** is described qualitatively ("only a small number of
  grants are web-scraped"). No figure published. **[D, self-reported]**
- **`ff2023.archive.org/home/candid`** returned no extractable text to a scripted fetch
  **[M]**; the Candid Archive-It holdings are confirmed only via search-result summaries,
  so treat the GlassPockets/IssueLab detail as **[D, second-hand]**.
- **No nonprofit-specific CMS survey** was found in public literature; §3's platform
  numbers are my own 45-domain census **[M]**, not a published study. The general-web
  W3Techs baseline is **[D]** and is included only for contrast.
- **Common Crawl page counts are floors**, capped at my `limit=1000`; and CC's own
  engineers say no production method exists to compute true site coverage **[D]**.
- **AmpliFund / Bonfire / BidNet**: I found no open-source connector. Absence of evidence
  after a focused search, not proof of absence.
- **Archive-It collection search** (`/explore`) is `Disallow`ed in their robots.txt and I
  did not crawl it; §5.3 rests on public search results and Candid's own blog.

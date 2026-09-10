# CRAWL LANE 3 — fetching JS-rendered content without a browser, archive fallbacks,
# extraction, PDFs, dedup, recrawl scheduling

Research for GrantSpider epics **#1102** (render-class fetch routing), **#2469** (PDF gap),
**#2471** (grant-portal vendor gap), **#2472** (classifier has no callers).

**Every claim is tagged.** `[MEASURED]` = I ran the probe in this session, numbers reproducible
from the scripts left in this scratchpad. `[DOC]` = stated in vendor/project documentation or a
paper. `[INFER]` = my reasoning from the above. `[WEAK]` = third-party blog/marketing claim I
could not verify at source.

---

## 0. The headline, before the detail

I sampled **220 random `foundations.website` rows from GS's own production corpus**
(`db scratch`, read-only) and fetched every homepage twice — once with a browser UA, once with
GS's declared `GrantDiscoveryBot/1.0`. The result contradicts the premise the render-routing
epic was scoped on.

| Outcome on 220 real foundation hosts | Count | Share | `[MEASURED]` |
|---|---|---|---|
| HTTP 200 | 183 | **83.2%** | ✅ |
| HTTP 403 (blocked) | 28 | **12.7%** | ✅ |
| Connection failure (DNS/TLS/timeout) | 9 | 4.1% | ✅ |
| Of the 183 × 200s: trafilatura yields **< 200 chars** | 10 | **5.5%** | ✅ |
| Of the 183 × 200s: any SPA framework signal at all | 6 | **3.3%** | ✅ |
| Of the 183 × 200s: SPA signal **and** empty text | **1** | **0.5%** | ✅ |

**The JS-rendering problem, on GS's actual corpus, is one host in two hundred.** The blocked
problem is **twenty-eight in two hundred** — roughly **25× larger**. `[MEASURED]`

And the block is not about the bot identity. All 28 hosts that 403'd a Chrome UA **also 403'd**
`GrantDiscoveryBot/1.0`; conversely 179/183 hosts that served a Chrome UA (97.8%) also served
the declared bot. `[MEASURED]` Declaring honestly costs GS ~2% of reach. The 12.7% is blocking
on TLS/JA3 fingerprint, ASN/datacenter-IP reputation, or a WAF challenge — not on the UA string.
`[INFER]`

Meanwhile **45.9% of the whole sample is reachable through a clean structured API** that needs
no HTML parsing, no sitemap walk, and carries a server-generated change timestamp. `[MEASURED]`
That is the actual prize in #1102, and it is not what the epic is currently pointed at.

---

## 1. Detecting render class from one plain GET

### 1.1 What the corpus actually looks like

Platform fingerprints on the 183 reachable hosts. Detection was a small regex table over the raw
HTML (markers listed in `render_probe.py`). `[MEASURED]`

| Platform | Hosts | % of 200s | Structured lane available? |
|---|---|---|---|
| WordPress | 72 | **39.3%** | `/wp-json/wp/v2/` — **87.5% answer** |
| Wix | 21 | 11.5% | server-rendered; `/sitemap.xml` **100%** |
| Squarespace | 17 | 9.3% | `?format=json` **100%** |
| Drupal | 7 | 3.8% | JSON:API *if* enabled (usually not) |
| Weebly | 5 | 2.7% | none; server-rendered |
| GoDaddy Website Builder | 3 | 1.6% | none; server-rendered |
| Duda | 3 | 1.6% | none; server-rendered |
| HubSpot CMS | 3 | 1.6% | none; server-rendered |
| Joomla | 2 | 1.1% | none |
| Webflow | 1 | 0.5% | none; server-rendered |
| **Next.js** | 4 | 2.2% | `__NEXT_DATA__` / `/_next/data/` |
| **Nuxt** | 1 | 0.5% | `window.__NUXT__` |
| Bare React root, no framework marker | 1 | 0.5% | none — needs archive/render |
| **No platform fingerprint at all** | 51 | **27.9%** | direct HTML only |

`<meta name="generator">` alone identified only 101/183 (55%); the remaining platforms were only
visible via asset-path and inline-script markers. `[MEASURED]` **A generator-tag-only classifier
misses 45% of the platforms it could have routed.** `[INFER]`

### 1.2 SPA-shell signals worth implementing

Ranked by what actually appeared, plus the standard set. `[DOC]` for the payload shapes,
`[MEASURED]` for prevalence.

| Signal | Regex | Payload you get for free |
|---|---|---|
| Next.js | `__NEXT_DATA__` or `/_next/static` | `<script id="__NEXT_DATA__" type="application/json">` — full page props. Also `/_next/data/<buildId>/<route>.json` |
| Nuxt | `window.__NUXT__` or `/_nuxt/` | inline JS object (Nuxt 2) or `<script type="application/json" id="__NUXT_DATA__">` (Nuxt 3, devalue-encoded — **not plain JSON**) |
| Apollo | `__APOLLO_STATE__` | normalized GraphQL cache — the whole query result set |
| Generic SSR store | `__INITIAL_STATE__`, `__PRELOADED_STATE__` | Redux/Vuex hydration payload |
| Gatsby | `window.___gatsby`, `page-data.json` | `/page-data/<route>/page-data.json` |
| Astro | `<astro-island`, `astro-island` | islands only — the rest is already static HTML |
| SvelteKit | `__sveltekit` | `__sveltekit_<hash>.data` |
| Remix | `__remixContext` | loader data inline |
| Empty root | `<div id="(root\|app\|__next)"></div>` | nothing — this is the true headless case |

The **empty-root check is the one that matters**, because a `__NEXT_DATA__` marker on a page that
already rendered 1,600 chars of text (which is what `adoptapet.com` and `astmh.org` did in my
sample) needs no special handling at all. `[MEASURED]` Route on **text yield**, not on framework
presence.

### 1.3 Platform fingerprinting via the Wappalyzer-derived datasets

Wappalyzer took its GPL-3.0 fingerprint database private in **August 2023** and deleted the public
repo. `[WEAK]` Community forks carry it forward:

| Project | License | Notes |
|---|---|---|
| [`enthec/webappanalyzer`](https://github.com/enthec/webappanalyzer) | **GPL-3.0** `[DOC]` — verified on the repo page | The most-cited data continuation. Matches on headers, DOM selectors, JS globals, meta, cookies, DNS, CSS, URL, and SSL issuer `[DOC]` |
| [`tunetheweb/wappalyzer`](https://github.com/tunetheweb/wappalyzer) | MIT `[WEAK]` | Used by HTTP Archive |
| [`projectdiscovery/wappalyzergo`](https://github.com/projectdiscovery/wappalyzergo) | MIT `[WEAK]` | Go; hand-rolled HTML parse for speed; ~251 fingerprints bundled `[WEAK]` |
| WhatWeb | GPL-2.0 | Ruby, security-oriented, heavyweight for this |

**Recommendation: do not adopt any of them.** `[INFER]` The GPL-3.0 on the enthec data is a real
question for a closed backend, and the whole ruleset is ~2,500 technologies to solve a problem my
measurement shows is **ten regexes wide**: WordPress, Wix, Squarespace, Drupal, Weebly, Duda,
GoDaddy, HubSpot, Webflow, Joomla covers 72.1% of reachable hosts. `[MEASURED]` The forks also
inherit Wappalyzer's pre-2023 blind spots wholesale. `[WEAK]`

### 1.4 Prevalence claims in the wild — treat with suspicion

The widely-repeated "over 70% of the modern web is client-side rendered" figure `[WEAK]` is
marketing copy and is **flatly wrong for this corpus**: 3.3% carry any SPA framework signal and
0.5% fail to render text without JS. `[MEASURED]` W3Techs' WordPress figure (40.7% of all sites,
58.9% of the CMS market, Sept 2026) `[WEAK]` happens to line up well with my 39.3% — that
agreement is worth noting, because the foundation web is a *small-org* web and small orgs are
exactly WordPress/Wix/Squarespace's demographic. `[INFER]`

---

## 2. Embedded-state and platform-API extraction without headless

### 2.1 WordPress REST — the single biggest win available `[MEASURED]`

I probed `/wp-json/wp/v2/pages?per_page=1` on all 72 WordPress-signalled hosts:

| Outcome | Hosts | Share |
|---|---|---|
| **200 + valid JSON + ≥1 page object** | **64** | **88.9%** |
| 401/403 (REST disabled or firewalled) | 5 | 6.9% |
| 404 | 1 | 1.4% |
| non-JSON / error | 2 | 2.8% |

Second pass, with `_fields=id,link,modified_gmt,title,content`:

- 63/72 hosts answered. `[MEASURED]`
- **63/63 objects carried `modified_gmt`** — a *server-generated* modification timestamp. `[MEASURED]`
- `X-WP-Total` header gave the page count on every responding host: **min 1, median 26, max 956,
  sum 3,782 across 63 sites**. `[MEASURED]`

What this buys, all in one paginated call per site:
- Complete page enumeration without a sitemap walk (and therefore **immune to the Liferay-style
  sitemap traps that froze the Dagster daemon in GS#1545**) `[INFER]`
- `content.rendered` — the body HTML, already isolated from nav/footer/sidebar chrome, so
  trafilatura's boilerplate job becomes trivial `[INFER]`
- `modified_gmt` per page — **the recrawl signal § 7 is otherwise missing**, and unlike sitemap
  `lastmod` it is written by the CMS, not by the site author `[INFER]`
- Also available: `/wp-json/wp/v2/posts`, `/media` (finds PDFs directly), `/categories`,
  and `/wp-json/` itself as a capability discovery document `[DOC]`

Cost: ~26 median pages/site at `per_page=100` is **one request per site** for the index. `[INFER]`

### 2.2 Squarespace `?format=json` `[MEASURED]`

**17/17 Squarespace hosts (100%) returned `200 application/json`.** Median body 20 KB, max 121 KB.
Top-level keys: `mainContent`, `website`, `websiteSettings`, `collection`, `shoppingCart`,
`shareButtons`, `localizedStrings`, `template`, `pagePreviewContext`, …

`mainContent` and `collection` carry the page body and, on collection pages, the item list with
per-item timestamps. `[INFER]` Also 17/17 served `/sitemap.xml`. `[MEASURED]`

**Caveat, and it is a real one:** Squarespace's own developer docs say
"[using `?format=json-pretty` is not static and should not be used as an alternative to our
APIs](https://developers.squarespace.com/view-json-data)". `[DOC]` It is an undocumented
debugging surface, not a contract — treat it as a best-effort lane with an HTML fallback, and
expect it to break without notice. `[INFER]` Squarespace's *documented* Commerce API rate limit is
300 req/min. `[DOC]`

### 2.3 Wix — already solved, no special lane needed `[MEASURED]`

**21/21 Wix hosts served `/sitemap.xml`.** Wix has server-rendered initial page loads since 2020
`[WEAK]`, and my extraction confirms it: none of the 21 Wix hosts landed in the low-yield bucket.
`[MEASURED]` **Wix needs nothing beyond the existing sitemap + direct-HTML path.** The 21 hosts do
carry a large `wix-warmup-data` JSON blob, but it is redundant with the rendered HTML. `[INFER]`

### 2.4 The rest

- **Webflow / Duda / GoDaddy / Weebly / HubSpot CMS** — all server-rendered, no JSON lane, no
  action needed. 15 hosts, 8.2%. `[MEASURED]`
- **Drupal** — JSON:API exists but is off by default and almost never exposed on small sites.
  7 hosts (3.8%); the one Drupal host in my low-yield bucket
  (`meyerhoffcharitablefunds.org`, 162 chars) is a genuine thin homepage, not a render failure.
  `[MEASURED]` Not worth a lane.
- **RSS/Atom** — worth a cheap probe (`/feed`, `/rss`, `<link rel="alternate">`) for the news/
  announcement stream where new grant programs get announced. Cost is one HEAD per site. `[INFER]`
- **Sitemap `lastmod`** — see § 7; do not trust it.

---

## 3. Archive fallbacks

### 3.1 API table

| API | Auth | Documented limit | Observed latency `[MEASURED]` | Body access | License/cost |
|---|---|---|---|---|---|
| **Wayback CDX** `https://web.archive.org/cdx/search/cdx` | none | Unpublished. Community consensus ~1 req/s; the `wayback` Python client **lowered its default to 24 req/min to match observed hard limits** `[DOC]` | **2.3 s – 42.4 s per query**, median ~33 s | metadata only | free |
| **Wayback Availability** `https://archive.org/wayback/available` | none | none stated `[DOC]` | 0.7–4.3 s | metadata only | free |
| **Wayback `id_` raw** `web.archive.org/web/<ts>id_/<url>` | none | as CDX | **4/4 success**, median 5.2 s, max 12.3 s | **original bytes, no IA toolbar** ✅ | free |
| **SPN2** (Save Page Now) | **IA S3 keys required** | not publicly documented; rate-limited per account `[WEAK]` | — | writes, not reads | free |
| **CC index** `index.commoncrawl.org/CC-MAIN-YYYY-WW-index` | none | "pause between calls, avoid parallel requests from one IP, avoid proxy networks" `[DOC]` | **0.2–2.2 s** ✅ | metadata + `filename`/`offset`/`length` | free |
| **CC WARC range read** `data.commoncrawl.org/<filename>` + `Range:` | none | as above | **0.3–0.5 s** ✅ | **full response record** ✅ | free over HTTPS; S3 in `us-east-1` also free-at-source |

### 3.2 The CC WARC range read works, end to end `[MEASURED]`

Verified live against three foundation domains. The exact recipe:

```
GET https://index.commoncrawl.org/CC-MAIN-2026-34-index?url=*.fordfoundation.org&output=json
  -> {"filename": "crawl-data/.../warc.gz", "offset": "681625685", "length": "31701", ...}
GET https://data.commoncrawl.org/<filename>   Range: bytes=681625685-681657385
  -> HTTP 206, Content-Range: bytes 681625685-681657385/955461449
  -> gzip-decompress -> WARC/1.0 response record -> HTTP headers + body
```

Ford: 31,701 compressed → 187,210 decompressed bytes in **0.3 s**. `[MEASURED]` Each record is an
independently-gzipped member, so a plain `gzip.GzipFile` over the range bytes works — no `warcio`
strictly required, though `warcio` (Apache-2.0) is the right thing for parsing the record properly.
`[INFER]` **`data.commoncrawl.org` returns `Content-Range`, `Content-Length` and `ETag`, so range
reads are a supported access mode, not a trick.** `[MEASURED]` + `[DOC]`

### 3.3 …but Common Crawl barely covers the corpus GS cares about `[MEASURED]`

This is the finding that should change the epic's archive plan. I queried CC-MAIN-2026-34 for 16
small/mid US foundation domains, and re-checked the misses against CC-MAIN-2026-21:

| Domain | Records in 2026-34 | of which HTTP 200 |
|---|---|---|
| wallacefoundation.org | 443 | 284 |
| stlgives.org | 150 | 146 |
| clevelandfoundation.org | 101 | 49 |
| mardag.org | 13 | 12 |
| bushfoundation.org | 7 | 7 |
| rrf.org | 6 | **0** (all HTTP 406 — CC was blocked) |
| mccunefoundation.org | 2 | **0** (HTTP 202 — challenge page) |
| cfgreateratlanta.org | 16 | **0** (all HTTP 400) |
| fdnweb.org | 14 | **0** (301 → `candid.org/retired-resource`) |
| bhhsfoundation.org | **0** | — |
| otto-bremer.org | **0** | — |
| chestnuthillfoundation.org | **0** | — |
| tccf.org | **0** | — |
| fbheron.org | **0** (2 in 2026-21) | — |
| jrmcdonaldfoundation.org | **0** | — |
| hyamsfoundation.org | **0** | — |

**7/16 have zero captures across two monthly indexes. Only 5/16 have any HTTP-200 HTML.**
`[MEASURED]` Even the biggest names top out around 400 URLs — CC-MAIN-2026-34 samples the web
broadly, not any given site deeply. `[INFER]`

By contrast, Wayback CDX found captures for **5 of the 6 CC-missed domains I re-checked**, and
`showNumPages` reported multi-page 5-year capture history for `hyamsfoundation.org` (3) and
`mardag.org` (3). `[MEASURED]`

**Conclusion: for the long-tail philanthropic web, Wayback is the archive fallback and Common
Crawl is not.** `[INFER]` CC's real value to GS is elsewhere — bulk host/domain enumeration
(the [host- and domain-level web graphs](https://commoncrawl.org/blog/host--and-domain-level-web-graphs-november-december-2025-and-january-2026): 279.4M host nodes / 122.3M domain nodes as of the
Nov 2025–Jan 2026 graphs `[DOC]`) — which is Lane 1's discovery problem, not this lane's.

### 3.4 Two operational traps

1. **The Availability API is flaky and must not be used as the coverage test.** In this one
   session it returned a valid snapshot for `macfound.org`, then 40 minutes later returned
   `NO SNAPSHOT` for the same domain. `[MEASURED]` The CDX API is authoritative; Availability is a
   convenience endpoint. `[INFER]`
2. **Wayback CDX latency is the throughput ceiling, not the rate limit.** Median ~33 s per query
   `[MEASURED]`, against a client-side budget of ~1 req/s and a documented 429 policy where
   "if a client ignores 429s for more than a minute the IP is firewalled for an hour, doubling on
   each repeat" `[WEAK]`. **At one static egress IP, an archive fallback that touches Wayback
   cannot be a per-page lane — it must be a batched, low-volume, last-resort lane** for the ~13%
   of blocked hosts only. `[INFER]`

### 3.5 Client libraries

| Library | License | Notes |
|---|---|---|
| [`cdx_toolkit`](https://github.com/commoncrawl/cdx_toolkit) | **Apache-2.0** `[DOC]` | Official CC Foundation repo. Unifies CC + IA behind one interface, knits monthly CC indices into a virtual index. **"Polite to CDX servers by being single-threaded and serial."** Defaults: 1,000-record cap on `.get()`, 1-year CC lookback. `[DOC]` 287 commits, 211 stars. |
| [`warcio`](https://github.com/webrecorder/warcio) | Apache-2.0 | The right WARC record parser; streaming, no full-file load |
| [`wayback`](https://wayback.readthedocs.io) (edgi-govdata-archiving) | BSD-3 | Speaks CDX **and** Memento. Notably it **reduced its default search rate to 24 req/min** to match IA's real limits — a useful calibration datum `[DOC]` |

**Recommendation:** `cdx_toolkit` is the right dependency for the archive lane. Its
single-threaded-and-serial politeness is exactly GS's constraint, and it is Apache-2.0 from the
CC Foundation itself. `[INFER]`

---

## 4. HTML → text/markdown extraction quality

### 4.1 Two independent benchmarks, and they disagree in an instructive way

**Trafilatura's own evaluation** (990 docs, 2,951 text / 2,966 boilerplate segments,
Python 3.13, updated 2026-08-04) — news/blog articles, ~20-30% non-English `[DOC]`:

| Library | Version | Prec | Rec | Acc | **F1** | Rel. time |
|---|---|---|---|---|---|---|
| **trafilatura (standard)** | 2.2.0 | 0.906 | 0.943 | 0.923 | **0.924** | 3.2× |
| trafilatura (precision) | 2.2.0 | 0.925 | 0.915 | 0.921 | 0.920 | 3.2× |
| trafilatura (fast) | 2.2.0 | 0.907 | 0.930 | 0.917 | 0.918 | 2.2× |
| magic-html | 0.1.8 | 0.887 | 0.891 | 0.889 | 0.889 | 3.5× |
| **jusText** | 3.0.2 | 0.864 | 0.859 | 0.862 | 0.862 | 2.3× |
| news-please | 1.6.16 | 0.932 | 0.758 | 0.852 | 0.836 | 20.5× |
| **readability-lxml** | 0.8.4.1 | 0.898 | 0.764 | 0.839 | 0.826 | 2.6× |
| **resiliparse** | 1.0.9 | 0.705 | 0.955 | 0.778 | 0.811 | **0.3×** |
| goose3 | 3.1.22 | 0.936 | 0.714 | 0.833 | 0.810 | 10.2× |
| **boilerpy3** | 1.0.7 | 0.818 | 0.796 | 0.810 | 0.807 | 1.6× |
| newspaper4k | 0.9.6 | 0.878 | 0.736 | 0.817 | 0.801 | 6.6× |
| inscriptis | 2.7.4 | 0.534 | 0.991 | 0.564 | 0.694 | 1.1× |
| **html2text** | 2025.4.15 | 0.525 | 0.900 | 0.544 | 0.663 | 2.8× |
| *Raw HTML (no extraction)* | — | 0.528 | 0.906 | 0.549 | 0.667 | 0.03× |

**[WCXB](https://webcontentextraction.org/)** (2,008 annotated pages, 1,613 domains, seven page
types — articles, service pages, products, collections, forums, listings, documentation;
CC-BY-4.0, updated April 2026, [DOI 10.5281/zenodo.19316874](https://doi.org/10.5281/zenodo.19316874)) `[DOC]`:

| Rank | System | Type | **F1** | Prec | Rec | ms/page |
|---|---|---|---|---|---|---|
| 1 | [rs-trafilatura](https://github.com/Murrough-Foley/rs-trafilatura) | Rule+ML (Rust) | **0.859** | 0.863 | 0.890 | **44** |
| 2 | MinerU-HTML (0.6B) | Neural | 0.827 | 0.845 | 0.840 | 1,570 |
| 3 | Resiliparse | Rule | 0.797 | 0.783 | 0.863 | **28** |
| 4 | **Trafilatura** | Rule | 0.791 | 0.852 | 0.793 | 97 |
| 5 | dom-smoothie | Rule | 0.762 | 0.806 | 0.768 | 26 |
| 6 | ReaderLM-v2 (1.5B) | Neural | 0.741 | 0.741 | 0.790 | 10,410 |
| 8 | Newspaper4k | Rule | 0.720 | 0.838 | 0.683 | 1,825 |
| 10 | jusText | Rule | 0.707 | 0.771 | 0.695 | — |
| 11 | BoilerPy3 | Rule | 0.687 | 0.795 | 0.661 | — |
| 12 | Readability | Rule | 0.674 | 0.684 | 0.712 | 785 |
| 13 | Goose3 | Rule | 0.651 | 0.845 | 0.593 | — |

**Read the disagreement, not the ranks.** Trafilatura scores 0.924 on its own article corpus but
0.791 on WCXB's seven-type corpus. `[DOC]` The gap is the price of leaving article-shaped pages —
and **grant guidelines pages are not article-shaped**: they are WCXB's "service page" and
"documentation" types. `[INFER]` Every one of these tools was tuned on news.

Resiliparse's WCXB profile is the useful warning: it wins on recall (0.863) by admitting far more
boilerplate — 22.8% boilerplate in output vs trafilatura's 6.6% `[WEAK]`. For a downstream that
feeds LLM enrichment prose, boilerplate is worse than a missing paragraph. `[INFER]`

### 4.2 Library table

| Library | License | Latest | Speed | Quality evidence | Verdict for GS |
|---|---|---|---|---|---|
| **trafilatura** | **Apache-2.0** | 2.2.0 (2.1.0 installed in GS) | 97 ms/page (WCXB) | F1 0.924 own / 0.791 WCXB | **Keep.** Best precision/recall balance; already the incumbent |
| resiliparse | Apache-2.0 `[DOC]` | 1.0.9 | **28 ms/page — 3.5× trafilatura** | F1 0.797 WCXB, 0.811 traf-bench | Only if throughput becomes the bind; costs precision |
| rs-trafilatura | **MIT OR Apache-2.0** `[DOC]` | 24 commits, 57★ — **immature** | 46–71 files/s | **F1 0.859 WCXB #1; 0.966 ScrapingHub** `[DOC]` | Watch. No PyPI bindings `[DOC]`; adding a Rust build to a Railway container for +0.07 F1 is not worth it yet |
| readability-lxml | Apache-2.0 | 0.8.4.1 | 785 ms/page | F1 0.826 / 0.674 | No |
| jusText | BSD-2 | 3.0.2 | — | F1 0.862 / 0.707 | No |
| boilerpy3 | Apache-2.0 | 1.0.7 | — | F1 0.807 / 0.687; **errors on malformed HTML** `[DOC]` | No |
| html2text | GPL-3.0 ⚠️ | 2025.4.15 | — | **F1 0.663 — below raw HTML at 0.667** `[DOC]` | **No.** GPL *and* worse than doing nothing |
| markdownify | MIT | — | fast | not benchmarked; it is a converter, not an extractor | Useful only *after* an extractor has isolated content |
| Docling | **MIT** `[DOC]` | 2.70.x | 40–80 s/multi-page doc on CPU `[WEAK]` | strong on doc structure | See § 5 — PDF tool, not an HTML lane |
| MinerU-HTML / ReaderLM-v2 | — | — | 1.6 s / 10.4 s per page | F1 0.827 / 0.741 | **No.** Violates the no-LLM-on-the-crawl-path ruling and is 16–100× slower |

### 4.3 Failure modes specific to grant-guidelines pages `[INFER]`

- **Tables.** `include_tables=True` is on by default `[DOC]`, but trafilatura flattens tables into
  markdown pipe rows with no column-header binding. Award-range and deadline tables — exactly the
  data AG needs — come out as ambiguous prose. **Mitigation:** when a page's HTML contains a
  `<table>`, keep the raw table HTML in a side field alongside the markdown, so a later structured
  pass can re-read it without a refetch.
- **Definition lists and nested `<ol>` eligibility criteria** frequently get collapsed to a single
  paragraph, losing the enumeration that makes eligibility machine-readable.
- **Accordion/tab guidelines.** Common on foundation sites; content is in the DOM but
  `display:none`. Trafilatura keeps it (it does not compute styles) — this is a *benefit* here and
  a reason not to switch to a renderer.
- **The content is in a linked PDF.** 15.8% of homepages link a PDF `[MEASURED]`; on "how to
  apply" pages the rate will be materially higher `[INFER]`. This is § 5.
- **Thin homepages are not extraction failures.** My p10 of 274 chars and median of 1,011 chars
  `[MEASURED]` reflects real small-foundation homepages that genuinely say very little. Do not
  build a "low yield ⇒ re-fetch via archive" rule on a character threshold alone; pair it with
  the empty-root/SPA signal. `[INFER]`

---

## 5. PDF extraction on CPU — and a live licensing problem

### 5.1 ⚠️ PyMuPDF is AGPL-3.0 and is already a direct, load-bearing GS dependency

This is a finding, not a recommendation. `pyproject.toml` lines 103–104 declare:

```
"pymupdf>=1.27,<2",
"pymupdf4llm>=0.0.17",
```

and `pymupdf` is imported in **at least six production modules**, not the dormant one: `[MEASURED]`

```
src/grantspider/services/pdf_extractor.py          (zero production callers - tests only)
src/grantspider/services/irs_990pf_schedules.py
src/grantspider/services/irs_990pf_statements.py
src/grantspider/services/irs_990pf_schedule_b.py
src/grantspider/connectors/irs_blank_forms.py
src/grantspider/connectors/hydration/doe_osti.py   (via pymupdf4llm)
```

PyMuPDF is **AGPL-3.0 or a paid Artifex commercial licence**. `[DOC]` AGPL §13's network clause
reaches software that users interact with remotely. GS is a closed backend whose output feeds AI
Grant Helper, a paid SaaS. Whether that constitutes "interacting with the modified version over a
network" is a legal question I am not qualified to settle — **but it is a question that is
currently unasked and unrecorded, and the 990-PF schedule assembly work has made GS materially
more dependent on it, not less.** `[INFER]`

**This belongs in front of Nathan as its own issue**, with three options: (a) buy the Artifex
commercial licence, (b) confirm with counsel that a non-network-facing batch backend is outside
§13, (c) migrate the PDF layer to `pypdf` (BSD) + `pdfplumber` (MIT). Option (c) is not free —
`irs_990pf_schedule_b.py` uses PyMuPDF's *writing* API (`pymupdf.open()`, `get_text_length`,
form assembly), which pypdf/pdfplumber cannot replace.

### 5.2 Measured: the PDF gap (#2469) is cheap to close and needs no OCR `[MEASURED]`

I harvested `.pdf` hrefs from the 183 reachable homepages and parsed the first 40 distinct ones:

| Measurement | Result |
|---|---|
| Homepages linking ≥1 PDF | **29/183 = 15.8%** |
| PDFs fetched and parsed successfully | 32 (1 × 404) |
| **With a real text layer** | **31/32 = 96.9%** |
| Likely scanned / image-only (<80 chars/page) | **1/32 = 3.1%** |
| Throughput | **331 pages in 2.31 s = 144 pages/sec, single CPU core** |
| Chars/page | min 2, **median 1,986**, max 20,574 |

**Foundation guidelines PDFs are born-digital and need no OCR.** `[MEASURED]` This is the opposite
of scanned paper 990s, where OCR is unavoidable — the two PDF populations must be routed
differently and must not share a policy. `[INFER]`

At 144 pages/sec, extracting the PDFs behind 15.8% of ~100k reachable foundation sites is a
rounding error against the crawl's own cost. `[INFER]` **#2469's blocker was never compute.**

### 5.3 PDF library table

| Library | License | CPU speed | Tables | OCR | Verdict |
|---|---|---|---|---|---|
| **PyMuPDF** | **AGPL-3.0 / commercial** ⚠️ | **144 pg/s `[MEASURED]`**; 10–50× pypdf `[WEAK]` | good | no (needs Tesseract) | Incumbent — **see § 5.1** |
| pypdf | **BSD-3** | slow | weak | no | Safe fallback for plain text |
| pdfplumber | **MIT** | slowest tier | **best table detection**; char-level layout | no | The MIT answer for table-heavy guidelines |
| pdfminer.six | MIT | slowest `[WEAK]` | char positions, fonts | no | pdfplumber's engine; use pdfplumber |
| pdftotext / poppler | **GPL-2.0/3.0** ⚠️ | very fast | `-layout` only | no | Same class of licence problem as PyMuPDF |
| **Docling** | **MIT** `[DOC]` | 40–80 s/multi-page doc on CPU `[WEAK]`; 0.49 s/pg on an L4 GPU `[WEAK]` | strong (layout models) | yes, extensive | **3,000–6,000× slower than PyMuPDF on CPU.** Ships a VLM path (Granite-Docling-258M, Apache-2.0). No — violates the no-model-on-crawl-path posture |
| marker | **Apache-2.0 code + modified RAIL-M weights** — free under **$5M funding/revenue**, paid above `[DOC]` | 23.7 pg/s CPU no-OCR `[DOC]` | good | yes | **The revenue trigger is a landmine for a growing SaaS.** No |
| unstructured | Apache-2.0 | moderate | moderate | yes | Heavy dependency tree for no gain here |

**Recommendation:** keep the fast path on whatever survives § 5.1; route the ~3% scanned-suspect
documents (detected by the **<80 chars/page** heuristic, which correctly isolated 1/32 in my
sample `[MEASURED]`) to a deferred OCR queue rather than blocking the pipeline on them. `[INFER]`

---

## 6. Near-duplicate and boilerplate detection at ~1M pages

- **SimHash** — 64-bit fingerprint, Hamming-distance ≤3 for near-dup. At 1M docs the index is
  8 MB. Built for cosine similarity. `[DOC]`
- **MinHash + LSH** (`datasketch`, MIT) — approximates Jaccard. `num_perm` controls the
  precision/memory tradeoff **linearly**: memory, serialized size, and whole-signature work all
  grow with `num_perm`. `[DOC]` At `num_perm=128` (4 bytes each) that is ~512 B/doc = **~512 MB
  for 1M docs in RAM.** `[INFER]` `datasketch` also ships `MinHashLSH` with Redis/Cassandra
  backends, so the index need not live in the Dagster container. `[DOC]`
- Scale reference points: a 5B-document corpus needed ~23 TB of signature storage `[WEAK]`; a 100M
  text-document corpus was found to be 22% near-duplicate `[WEAK]`. Both are far above GS's scale
  and only confirm that 1M is comfortable. `[INFER]`
- ["In Defense of MinHash Over SimHash"](https://arxiv.org/pdf/1407.4416) argues MinHash dominates
  for the resemblance regime; SimHash is popular mostly because researchers default to cosine.
  `[DOC]`

**Recommendation for GS, in cost order:** `[INFER]`

1. **Exact hash after extraction, not before.** GS already writes hash-addressed B2 objects, but
   the hash is presumably over the markdown. Hashing the *extracted text* (post-trafilatura,
   post-normalization) already collapses the biggest duplicate class — the same guidelines page
   reachable at three URLs — at zero extra cost. Verify what the existing hash covers before
   building anything.
2. **Per-host template detection by shingle frequency.** With a median of 26 pages/site
   `[MEASURED]`, any line appearing on >70% of a host's pages is chrome. This is a per-host
   `Counter`, needs no LSH, and directly attacks the aggregator-chrome problem. It also
   **degrades gracefully on the 1-page sites** (min `X-WP-Total` was 1 `[MEASURED]`) where it
   simply does nothing.
3. **MinHash/LSH only for cross-host duplication** — the aggregator/directory pages
   (`usgrantsdatabase.com`, `kycompanydir.com`, `georgiacompanyregistry.com`,
   `cacompanyregistry.com`, `grantsonar.com`, `mapquest.com` all appeared in my random sample
   `[MEASURED]`) that syndicate identical EIN-keyed boilerplate across thousands of hosts. This is
   the one job exact hashing cannot do, because each page differs by the EIN.

**Do not build (3) before (1) and (2).** `[INFER]`

---

## 7. Recrawl scheduling

### 7.1 Conditional requests — measured on this corpus `[MEASURED]`

| Header on the 183 reachable foundation homepages | Count | Share |
|---|---|---|
| `ETag` | 66 | 36.1% |
| `Last-Modified` | 47 | 25.7% |
| **Either one** | **97** | **53.0%** |
| Neither | 86 | 47.0% |

(For context, HTTP Archive's 2021 Web Almanac found ~84–91% ETag adoption across all resource
types `[WEAK]` — but that figure is dominated by CDN-served static assets, not CMS-rendered HTML
documents, which is why my HTML-only number is roughly half of it. `[INFER]`)

**53% conditional-request support means a validator-based recrawl saves at most half the
bandwidth, and zero of the connections.** `[INFER]` It is worth implementing — a 304 is cheap and
correct — but it cannot be the scheduling mechanism, because for 47% of hosts there is nothing to
condition on.

### 7.2 Sitemap `lastmod` is not trustworthy

Google's stated position, via Gary Illyes: trust in `lastmod` is **binary** — Google checks the
dates against the pages, and a site with a history of inaccurate `lastmod` has the tag ignored
entirely. `[WEAK]` In July 2026 Illyes told a site emitting wrong dates it was "probably better
off without the lastmods." `[WEAK]`

The mechanism matters more than the quote: **sitemap `lastmod` is written by the site author or
the SEO plugin, and on WordPress the most popular plugins stamp it on republish, on cache flush,
or on a schedule — not on content change.** `[INFER]` This is precisely why § 2.1's
`modified_gmt` is different in kind: it comes from the `wp_posts` table, not from a generator.

### 7.3 Change-rate estimation

- **Cho & Garcia-Molina, "Effective Page Refresh Policies for Web Crawlers"** (ACM TODS 2003,
  [PDF](http://oak.cs.ucla.edu/~cho/papers/cho-tods03.pdf)) — models page change as a **Poisson
  process**, verified against 270 sites, and shows that the *uniform* refresh policy beats the
  *proportional* one (refreshing frequently-changing pages more often is **worse** than refreshing
  everything equally, because the fast-changing pages are unwinnable). `[DOC]` **This is the
  counter-intuitive result that matters for GS.**
- Google's own ["Risk and optimality in estimating refresh rates"](https://research.google.com/pubs/archive/34570.pdf) handles the practical case where pages
  enter the set continuously and estimation must start immediately, using MLE on the change rate.
  `[DOC]`

### 7.4 How the production crawlers actually do it

- **StormCrawler `AdaptiveScheduler`** — extends `DefaultScheduler`; compares an **MD5 signature**
  of the fetched content against the last fetch. Changed ⇒ interval shrinks toward the minimum;
  unchanged ⇒ grows toward the maximum. Defaults: **min 60 min, max 20,160 min (14 days)**,
  increment/decrement factors both 0.5. `[DOC]`
- **Nutch `AdaptiveFetchSchedule`** — same idea; `MimeAdaptiveFetchSchedule` lets the INC/DEC
  factors vary **per MIME type**, for corpora mixing HTML and PDFs. `[DOC]` Directly relevant:
  a foundation's guidelines PDF and its news page change on completely different clocks. `[INFER]`
- **Heritrix** — archival crawler; scheduling is job-scoped, not adaptive-per-URL. Not a model
  for GS. `[INFER]`

### 7.5 A policy for a corpus that changes yearly `[INFER]`

GS's corpus has an unusual property that all four references above lack: **a known annual cycle.**
Foundation guidelines change at the grant cycle, and 990-PF filings arrive on a fiscal schedule.
Recommended policy, cheapest lever first:

1. **Route by change signal, not by uniform interval.**
   - WordPress (≈39% of reachable hosts): poll
     `/wp-json/wp/v2/pages?orderby=modified&per_page=1&_fields=modified_gmt` — **one request
     tells you whether anything on the entire site changed.** `[MEASURED]`-backed: 63/63 hosts
     carried `modified_gmt`. This is a ~26× reduction in refresh cost for those hosts. `[INFER]`
   - Everything else: conditional GET where a validator exists (53%), signature comparison
     otherwise.
2. **Adaptive interval on a content signature**, StormCrawler's algorithm, but with GS-shaped
   bounds: **min 30 days, max 365 days**, since nothing in this corpus rewards hourly checking.
   Per-MIME factors à la Nutch, so PDFs decay slower than HTML.
3. **Take Cho & Garcia-Molina's uniform-beats-proportional result seriously.** Do not spend the
   crawl budget chasing the handful of foundations that publish weekly; spend it getting one
   fresh copy of the 111k websiteless and never-crawled tail. `[INFER]`
4. **Anchor on the fiscal calendar.** A deadline-bearing page whose stated deadline has passed is
   a *guaranteed* stale page — that is a stronger and cheaper refresh trigger than any change-rate
   model, and GS already extracts deadlines. `[INFER]`

---

## 8. Grant-portal vendors (#2471)

### 8.1 Robots posture — measured, verbatim `[MEASURED]`

| Vendor | Host probed | robots.txt | Verdict |
|---|---|---|---|
| **Submittable (marketing)** | `www.submittable.com` | `User-agent: *` → `Allow: /`; **explicit `Allow: /` for GPTBot, ChatGPT-User, OAI-SearchBot, anthropic-ai, ClaudeBot, GoogleOther, Google-Extended, Googlebot, Applebot, Bingbot, PerplexityBot, ScreamingFrogCrawler**; only `Brightbot` disallowed. Sitemap declared | **Fully open** ✅ |
| **Submittable (app)** | `manager.submittable.com` | `User-agent: *`, **`Crawl-delay: 10`**, disallows only `/user/ /settings/ /account/ /payment/ /paypal/ /signup/…` — **`/opportunities/` and `/api/` are NOT disallowed** | **Open, with a 10 s delay** ✅ |
| **Foundant** | `www.grantinterface.com` | **`Disallow: /`** (whole file is 27 bytes) | **Closed** ❌ |
| **SmartSimple (applicant portal)** | `webportalapp.com` | **`Disallow: /`** | **Closed** ❌ |
| **CyberGrants** | `www.cybergrants.com` | **`Disallow: /`** | **Closed** ❌ |
| **Fluxx** | `www.fluxx.io` | HubSpot-default; allows all but preview paths | Open, but marketing only |
| **SmartSimple (corp)** | `www.smartsimple.com` | HubSpot-default; open | Marketing only |
| **Blackbaud** | `www.blackbaud.com` | open except `/wp-content/uploads/*.pdf` | Marketing only |
| **Benevity** | `causes.benevity.org` | **`Disallow: /` for GPTBot, ChatGPT-User, ChatGPT, Google-Extended, Claude-Web, ClaudeBot, anthropic-ai** | AI-crawler-hostile ❌ |
| **WizeHive** | `www.wizehive.com` | **301s to `www.submittable.com`** — WizeHive appears to have been absorbed into Submittable | n/a |
| **GrantRequest** | `www.grantrequest.com` | HTTP 503 challenge page on robots.txt itself | Unreadable ❌ |

### 8.2 🎯 Submittable Discover exposes a public, unauthenticated JSON API `[MEASURED]`

I found it by grepping Submittable's own 5.4 MB submitter bundle
(`d370dzetq30w6k.cloudfront.net/submitter_js.*.bundle.js`) for API paths, then calling it with no
credentials:

```
GET https://manager.submittable.com/api/opportunities/?page=1&pageSize=5
    Accept: application/json
    X-Requested-With: XMLHttpRequest

HTTP 200  application/json
{"total":1948,"page":1,"hasMore":true,"items":[
  {"id":296173,"guid":"755376f1-…","name":"…","expiration":"2026-09-07T16:00:00Z",
   "organization":{"id":20117,"guid":"…","name":"Black Horse Review",
                   "websiteUrl":"https://blackhorsereview.com", …}, …}]}
```

**`"total": 1948` live opportunities**, each carrying `name`, `expiration` (the deadline),
and a nested `organization` with `name` and **`websiteUrl`**. `[MEASURED]`

Adjacent endpoints discovered in the same bundle: `/api/opportunities/?`,
`/api/opportunities/labels`, `/api/opportunities/tags`, `/api/opportunities/currency`,
`/api/organizations/`, `/api/categories/currency`. `[MEASURED]`

Why this matters beyond opportunities: `organization.websiteUrl` is an **authoritative
funder-name → domain mapping published by the funder itself**, which is exactly the input the
website-resolution provider chain (GS#1789, #2160, #2229, #2548) is starving for. `[INFER]`

Caveats, stated plainly: this is an undocumented internal XHR endpoint, not a contract; it can
change or start requiring auth without notice. `[INFER]` Its robots posture permits it and the
`Crawl-delay: 10` is honourable at 1,948 records ÷ 100/page ≈ 20 requests ≈ 200 s for a full
sweep. `[MEASURED]` + `[INFER]` The rendered page at
`manager.submittable.com/opportunities/discover/<id>` is a pure JS shell — **160 characters of
visible text** `[MEASURED]` — so the API is the only viable route, and `www.submittable.com/discover`
is likewise a Webflow marketing shell with 832 chars and no listings `[MEASURED]`.

### 8.3 Vendor prevalence on foundation sites is very low — measured, and I got it wrong once

First pass reported 18.6% of homepages carrying a vendor marker. **That number was wrong**: my
`reviewr` pattern was an unanchored substring matching Wix's own
`DisableLivePreviewRefreshes` / `previewRegion` and JSON-LD `reviewRating`. I re-ran with
domain-anchored patterns:

| Marker on 182 foundation homepages | Hosts | Share `[MEASURED]` |
|---|---|---|
| Any marker (incl. generic form tools) | 16 | 8.8% |
| **A grant-portal vendor specifically** | **2** | **1.1%** |
| — Fluxx | 2 | 1.1% |
| — Submittable / Foundant / SmartSimple / Blackbaud / CyberGrants / Benevity / WizeHive | **0** | **0%** |
| Google Forms | 7 | 3.8% |
| JotForm | 4 | 2.2% |
| Formstack | 2 | 1.1% |
| Wufoo / Typeform | 2 | 1.1% |

**Caveats, both of which cut the same way and neither of which rescues the number:** homepages
under-represent portal links (they live on "how to apply" pages), and the random sample contains
many mis-resolved non-grantmakers (§ 9). `[INFER]` Even generously doubled or tripled, vendor-link
prevalence on foundation sites is single-digit percent.

**Conclusion: #2471 is scoped backwards.** Following vendor links *out* from foundation sites
reaches ~1–3% of the corpus through portals that mostly answer `Disallow: /`. Crawling the
*vendor's own public marketplace* reaches 1,948 opportunities in ~20 requests. `[INFER]`

### 8.4 The rest of the vendors

Fluxx, SmartSimple, Blackbaud Grantmaking, CyberGrants and Benevity all put the grantee portal
behind registration `[WEAK]`, and three of them say `Disallow: /`. There is no public listing
surface and **no open-source connector for any of them that I could find.** `[INFER]` The correct
GS behaviour is to *detect and record* the portal vendor and URL as a funder attribute — useful
signal for AG's users ("this funder applies through Foundant") — and **never fetch it**. `[INFER]`
That is a cheap regex on already-fetched HTML, not a crawl lane.

---

## 9. Incidental finding, outside this lane but urgent

The 220-row random sample of `foundations.website` is visibly polluted. Among 220 rows
`[MEASURED]`:

```
https://www.mapquest.com/us/indiana/helen-k-higgins-tr-agency-006196-791050765
https://apps.ilsos.gov/businessentitysearch/
https://www.kycompanydir.com/companies/kirchdorfer-foundation-inc/
https://www.cacompanyregistry.com/companies/cynthia-and-merrill-magowan-family-foundation-inc/
https://www.georgiacompanyregistry.com/companies/charles-loridans-foundation-inc/
https://www.usgrantsdatabase.com/foundations/spotswood-charitable-foundation-inc-0099
https://grantsonar.com/funders/ray-and-elsie-catena-family-foundation-inc-82084ce3-…
```

plus swim clubs, pet rescues, a town government, a Bible publisher and `dmv.nv.gov`. This is
GS#2160 / #2229 / #2548, and it is large enough to bias every measurement in this report
downward — including my own vendor-prevalence number. **It also means any render-routing or
archive-fallback budget spent per-host is partly spent on hosts that are the wrong org.**
`[INFER]` Sizing it properly is Lane 1's job; flagging it is mine.

---

## 10. Ranked recommendations

### For #1102 — render-class fetch routing

The epic's three planned lanes (direct HTML / embedded-state / archive) are the right *shape* but
the wrong *weights*. Reordered by measured yield:

| # | Action | Reach `[MEASURED]` | Cost | Why |
|---|---|---|---|---|
| **1** | **WordPress `/wp-json/wp/v2/` lane** | **28.6% of all sampled hosts** (39.3% WP × 87.5% answer) | ~1 day | Full page enumeration + clean body HTML + `modified_gmt` in one call. Sidesteps sitemap traps entirely. Also solves half of § 7 |
| **2** | **Squarespace `?format=json` lane** | 7.7% | ~2 hours | 17/17 success. Undocumented, so ship with an HTML fallback |
| **3** | **Route on text yield, not framework signal** | fixes the 3.3% SPA cohort correctly | ~2 hours | 5 of the 6 SPA-signalled hosts already render fine. Framework-presence routing would waste budget on all 6 |
| **4** | **Wire the existing classifier (#2472)** | — | ~1 day | `fetch_strategy_classifier.py` is referenced only by itself and `models/mine_url.py`. Verified this session `[MEASURED]` |
| **5** | **Reclassify the 12.7% blocked cohort honestly** | **12.7% — the biggest single loss** | ~1 day | 403 to *both* UAs. Not a render problem, not a data class. Needs its own verdict state and its own remedy (§ archive) |
| **6** | **Embedded-state (`__NEXT_DATA__` etc.) extraction** | **0.5%** | ~2 days | **Deprioritize.** One host in 220. Build it when the classifier says it is worth building |
| **7** | Wix / Webflow / Duda / GoDaddy / Weebly special handling | 0% gain | — | **Do not build.** All server-render; the existing direct path already works. 21/21 Wix served sitemaps |

**The one-line summary for the epic: the biggest render-routing win is not rendering. It is
noticing that 46% of the corpus has a JSON API and 13% is blocked.**

### For #2469 — the PDF gap

| # | Action | Why |
|---|---|---|
| **1** | **Raise § 5.1 (PyMuPDF AGPL) with Nathan as a separate issue before writing any new PDF code** | Six production modules already depend on it. Expanding PDF work expands the exposure. This is a decision only he can make |
| **2** | Wire `pdf_extractor.py` to a caller — it currently has **zero** outside its own test `[MEASURED]` | The service exists; the gap is integration, not implementation |
| 3 | Remove the PDF exclusion for `text/pdf` on foundation hosts | 15.8% of homepages link one |
| 4 | **Skip OCR entirely for foundation-site PDFs**; queue the <80-chars/page minority separately | 31/32 have a text layer. OCR is a 990-scan problem, not a guidelines problem |
| 5 | Reuse the existing hash-addressed B2 path for extracted PDF text | No new storage design needed |
| — | Do **not** adopt Docling or marker | Docling is 3,000×+ slower on CPU; marker's RAIL-M weights carry a **$5M revenue trigger** `[DOC]` |

### For #2471 — the vendor gap

| # | Action | Why |
|---|---|---|
| **1** | **Build one connector: Submittable Discover `/api/opportunities/`** | 1,948 live opportunities, public, no auth, robots-permitted, ~20 requests for a full sweep `[MEASURED]` |
| **2** | Harvest `organization.websiteUrl` from that same response into the website-resolution chain | An authoritative funder→domain mapping, free with the data you already fetched `[INFER]` |
| 3 | Detect-and-record vendor + portal URL as a funder attribute from already-fetched HTML | Useful to AG's users; costs one regex; zero extra requests |
| 4 | **Never fetch** Foundant / SmartSimple-webportalapp / CyberGrants | All three answer `Disallow: /` `[MEASURED]` |
| 5 | Treat Benevity as off-limits for the declared bot | Explicitly `Disallow: /` for ClaudeBot and anthropic-ai `[MEASURED]` |
| — | Drop the "follow vendor links out from foundation sites" framing | 1.1% prevalence `[MEASURED]` |

### For the archive lane

| # | Action | Why |
|---|---|---|
| **1** | **Make Wayback the primary archive fallback, not Common Crawl** | CC has **zero** captures for 7/16 long-tail foundations; Wayback had captures for 5/6 of those `[MEASURED]` |
| 2 | Use `web/<ts>id_/<url>` for bodies | 4/4 success, median 5.2 s, no IA toolbar in the bytes `[MEASURED]` |
| 3 | Use CDX, never the Availability API, as the coverage test | Availability gave contradictory answers for the same domain 40 min apart `[MEASURED]` |
| 4 | Budget the archive lane at **~13% of hosts, batched, low-volume** | CDX median latency ~33 s against a ~1 req/s ceiling on one static IP `[MEASURED]` + `[WEAK]` |
| 5 | Adopt `cdx_toolkit` (Apache-2.0) rather than hand-rolling | Single-threaded-and-serial by design — matches GS's politeness posture exactly `[DOC]` |
| 6 | Keep the CC **WARC range read** — it works and is fast (0.3–0.5 s) — but scope it to the big-foundation minority | Verified end to end this session `[MEASURED]` |

### For extraction and dedup

| # | Action | Why |
|---|---|---|
| 1 | **Keep trafilatura.** Do not switch | Best precision/recall balance in both benchmarks; incumbent; Apache-2.0 |
| 2 | Preserve raw `<table>` HTML alongside markdown | Award ranges and deadlines are in tables, and every extractor flattens them |
| 3 | Confirm what the existing B2 content hash covers; if it is pre-extraction, add a post-extraction text hash | Free; collapses the largest duplicate class |
| 4 | Per-host shingle-frequency template detection before any LSH | Median 26 pages/site makes this trivial `[MEASURED]` |
| 5 | MinHash/LSH (`datasketch`, MIT) **only** for cross-host aggregator boilerplate | ~512 MB at 1M docs, `num_perm=128` `[INFER]` |
| — | Do not adopt html2text | GPL-3.0 **and** F1 0.663, below the 0.667 of doing nothing `[DOC]` |
| — | Watch rs-trafilatura; do not adopt yet | Best-in-class F1 but 24 commits and no Python bindings `[DOC]` |

---

## Appendix — probe scripts and raw data

All in this scratchpad directory, re-runnable:

| File | What it measures |
|---|---|
| `cc_probe.py` | CC index coverage + WARC byte-range body fetch |
| `probe2.py` / `probe3.py` | CC depth and status breakdown on small foundations |
| `render_probe.py` → `render_probe.ndjson` | 220 foundation homepages: status, platform, trafilatura yield, validators |
| `ua_wp_probe.py` | bot-UA vs browser-UA block rate; wp-json availability |
| `wp2.py` | wp-json payload shape, `X-WP-Total`, `modified_gmt` |
| `sqsp.py` | Squarespace `?format=json`, Wix sitemaps |
| `vendor_probe.py` / `vendor2.py` / `vendor3.py` | vendor robots.txt, render class, Submittable API discovery |
| `vendorlink2.py` | corrected vendor-link prevalence |
| `pdfprobe.py` | PDF prevalence, text-layer rate, CPU pages/sec |

**Sampling caveats.** One random draw of 220 rows from `foundations.website`, homepages only,
single fetch per host, one point in time (2026-09-07). Deep pages are plausibly more JS-heavy than
homepages `[INFER]`. The sample includes mis-resolved non-grantmakers (§ 9), which biases platform
mix toward general small-org web. Sampling error on a 220-row draw is roughly ±3 pp at the 5%
level and ±7 pp at the 40% level `[INFER]` — the WordPress share is 39.3% ± ~7, the SPA share
3.3% ± ~2.4. **None of the conclusions turn on a margin that narrow**: the SPA cohort would have
to be off by a factor of five to rival the blocked cohort.

## Sources

- [WCXB — Web Content Extraction Benchmark](https://webcontentextraction.org/) · [arXiv 2605.21097](https://arxiv.org/html/2605.21097)
- [Trafilatura — Benchmarks and evaluation](https://trafilatura.readthedocs.io/en/latest/evaluation.html) · [Troubleshooting](https://trafilatura.readthedocs.io/en/latest/troubleshooting.html) · [Core functions](https://trafilatura.readthedocs.io/en/latest/corefunctions.html)
- [rs-trafilatura](https://github.com/Murrough-Foley/rs-trafilatura) · [Resiliparse](https://github.com/chatnoir-eu/chatnoir-resiliparse) · [Resiliparse HTML2Text docs](https://resiliparse.chatnoir.eu/en/stable/man/extract/html2text.html)
- [An Empirical Comparison of Web Content Extraction Algorithms (SIGIR 2022)](https://dl.acm.org/doi/pdf/10.1145/3539618.3591920)
- [Common Crawl — collinfo.json](https://index.commoncrawl.org/collinfo.json) · [Terms of Use](https://commoncrawl.org/terms-of-use) · [FAQ](https://commoncrawl.org/faq) · [Host- and domain-level web graphs, Nov 2025–Jan 2026](https://commoncrawl.org/blog/host--and-domain-level-web-graphs-november-december-2025-and-january-2026) · [Build on Common Crawl from the browser](https://commoncrawl.org/blog/you-can-now-build-directly-on-common-crawl-from-the-browser)
- [cdx_toolkit](https://github.com/commoncrawl/cdx_toolkit) · [warcio](https://github.com/webrecorder/warcio) · [wayback (Python) usage](https://wayback.readthedocs.io/en/latest/usage.html) · [wayback issue #137 — rate limit reduced to 24/min](https://github.com/edgi-govdata-archiving/wayback/issues/137)
- [Wayback Machine APIs](https://archive.org/help/wayback_api.php) · [Wayback CDX Server README](https://github.com/internetarchive/wayback/blob/master/wayback-cdx-server/README.md)
- [PyMuPDF licensing (Artifex, AGPL/commercial)](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) · [Docling](https://github.com/docling-project/docling) · [marker](https://github.com/datalab-to/marker) · [pdfplumber](https://github.com/jsvine/pdfplumber) · [pypdf](https://github.com/py-pdf/pypdf)
- [enthec/webappanalyzer](https://github.com/enthec/webappanalyzer) · [projectdiscovery/wappalyzergo](https://github.com/projectdiscovery/wappalyzergo) · [tunetheweb/wappalyzer](https://github.com/tunetheweb/wappalyzer)
- [datasketch MinHash LSH](https://ekzhu.com/datasketch/lsh.html) · [MinHash](https://ekzhu.com/datasketch/minhash.html) · [In Defense of MinHash Over SimHash](https://arxiv.org/pdf/1407.4416)
- [Cho & Garcia-Molina, Effective Page Refresh Policies (TODS 2003)](http://oak.cs.ucla.edu/~cho/papers/cho-tods03.pdf) · [Google — Risk and optimality in estimating refresh rates](https://research.google.com/pubs/archive/34570.pdf)
- [StormCrawler AdaptiveScheduler](https://stormcrawler.net/docs/api/com/digitalpebble/stormcrawler/persistence/AdaptiveScheduler.html) · [Nutch MimeAdaptiveFetchSchedule](https://nutch.apache.org/apidocs/apidocs-1.7/org/apache/nutch/crawl/MimeAdaptiveFetchSchedule.html) · [Nutch Recrawl wiki](https://wiki.apache.org/nutch/Recrawl)
- [HTTP Archive Web Almanac 2021 — Caching](https://almanac.httparchive.org/en/2021/caching) · [Google on sitemap lastmod trust](https://www.seroundtable.com/google-sitemap-lastmod-binary-trust-37554.html)
- [Squarespace — View JSON data](https://developers.squarespace.com/view-json-data) · [Squarespace URL queries](https://developers.squarespace.com/url-queries) · [Squarespace Commerce API rate limits](https://developers.squarespace.com/commerce-apis/rate-limits)
- [Submittable API docs (v3)](https://submittable-api.submittable.com/docs/v3/index.html) · [Does Submittable have an API?](https://submittable.help/en/articles/905022-does-submittable-have-an-api)
- Live probes, 2026-09-07: `www.submittable.com/robots.txt`, `manager.submittable.com/robots.txt`, `manager.submittable.com/api/opportunities/`, `www.grantinterface.com/robots.txt`, `webportalapp.com/robots.txt`, `www.cybergrants.com/robots.txt`, `causes.benevity.org/robots.txt`, `index.commoncrawl.org`, `data.commoncrawl.org`, `web.archive.org/cdx`, `archive.org/wayback/available`

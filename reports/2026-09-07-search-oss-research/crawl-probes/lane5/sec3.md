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


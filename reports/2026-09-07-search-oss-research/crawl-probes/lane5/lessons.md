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

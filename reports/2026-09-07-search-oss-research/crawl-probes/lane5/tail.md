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

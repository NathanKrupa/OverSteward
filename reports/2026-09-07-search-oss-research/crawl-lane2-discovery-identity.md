# CRAWL LANE 2 — Website discovery without metered search, resolved-site verification, and bot legitimacy in 2026

Research date: **2026-09-07**. Target: GrantSpider (GS), ~111k websiteless US grantmakers (GS#1789),
shoestring budget, one static egress IP, no metered LLM on the crawl path.

**Evidence key**
- **[MEASURED]** — I ran the probe in this session; raw output reproduced.
- **[DOC]** — stated in vendor/standards documentation, URL given.
- **[INFER]** — my reasoning from the above; not independently confirmed.

Probe scripts left at `scratchpad/search-research/cc_probe.py` and `wd_probe.py`.

---

## 0. Headline findings (read these even if nothing else)

1. **Brave's free tier is gone.** The current Brave Search API page lists only "$5 in free" monthly
   credits at **$5 per 1,000 requests** — ~1,000 queries/month, then the card is billed. GS's plan of
   "DDG first, Brave after" now means Brave can clear ~1,000 of 111k orgs per month (≈9 years), or
   cost **≈$555** as a one-shot. **[DOC]** https://brave.com/search/api/
2. **DDG's robots position is better than assumed, its ToS position is worse.** `html.duckduckgo.com/robots.txt`
   is `Allow: /` — the host GS actually scrapes does *not* disallow it. But `duckduckgo.com/robots.txt`
   carries `Disallow: /html` and `Disallow: /lite`, and DDG's ToS prohibits automated non-personal use.
   So GS is robots-clean on the literal host and ToS-non-compliant regardless. **[MEASURED]**
3. **The cheapest large win is a domain-existence oracle, not a search engine.** Name→domain guessing is
   only expensive because every guess costs a DNS/HTTP probe. An offline registered-domain universe
   (ICANN CZDS `.org`/`.com` zone files, free with approval; or Common Crawl's 3.46 GB domain-ranks file,
   free with no approval) turns "guess and probe" into a set-membership test costing **zero requests**.
   Probe only the survivors. **[MEASURED]** the CC file exists and is parseable; **[INFER]** the yield.
4. **Wikidata is high-precision, ~0.4%-recall for this corpus.** Measured below. It is already
   exhausted; do not expect more from it.
5. **schema.org `NonprofitOrganization` is not a usable verification signal.** schema.org's own
   `nonprofitStatus` page reports usage of **1K–10K domains** in Google's web index (May 2026). Against
   ~300k foundations, that is noise. **[DOC]** https://schema.org/nonprofitStatus
6. **GS's identity is further along than the brief says.** `bot.aigranthelper.com` is live (HTTP 200),
   publishes `ips.json` in Google/Cloudflare prefix format, and **forward-confirmed reverse DNS already
   works**: `5.78.196.28` → `crawl-1.aigranthelper.com` → `5.78.196.28`. **[MEASURED]** The brief calls
   rDNS "planned"; it is done. The remaining gap is Web Bot Auth: both candidate well-known paths 404.
7. **Web Bot Auth is now a chartered IETF WG, not one person's draft.** `draft-ietf-webbotauth-httpsig-protocol-00`,
   dated **2026-09-01**. Cloudflare *prioritises* signature-based applications for Verified Bots.
   **[DOC]** https://datatracker.ietf.org/group/webbotauth/documents/

---

## 1. Summary table — discovery sources

| Source | Coverage for 111k US grantmakers | Cost | Etiquette / limits | Fit for GS |
|---|---|---|---|---|
| **IRS 990/990-PF `WebsiteAddressTxt`** | 990-PF *does* have the field (Part VII-A Line 13, conditional on the public-inspection answer) — GS already reads it; the 111k are the residue **[DOC]** | free | bulk XML | **exhausted** — it is the definition of the gap |
| **Wikidata P856 via EIN (P1297)** | 17,221 entities carry an EIN; 15,050 (87%) of those have P856. US "foundation" (Q157031): **1,070 total, 504 with P856** **[MEASURED]** | free | 60 s CPU / 60 s per UA+IP; 429 then ban; UA policy enforced **[DOC]** | **exhausted** — ~0.4% of corpus |
| **Wikipedia external links** | subset of Wikidata's | free | same WMF etiquette | exhausted |
| **ICANN CZDS zone files (.org, .com)** | complete registered-domain universe → *candidate filter*, not an answer | free, **approval required** (~weeks; >90% of zones typically approved) **[DOC]** | per-registry ToS; lawful-use agreement | **HIGH — top recommendation** |
| **Common Crawl domain-ranks file** | 3.46 GB gz, one row per registered domain, reversed-host + harmonic/PageRank **[MEASURED]** | free, no approval | plain S3/CloudFront GET | **HIGH** — CZDS substitute available *today* |
| **Common Crawl CDX API** | 15/15 large foundations HIT; 1 small returned "No captures"; **2/20 queries failed with 503/504 at 1 req / 6 s** **[MEASURED]** | free | "heavily rate limited"; 503 = slow down; block = wait 24 h **[DOC]** | **verification only, never bulk** |
| **Common Crawl columnar index (Parquet)** | ~300 GB/crawl, `url_host_registered_domain`, `fetch_status`, `content_languages` **[DOC]** | free data; your compute/egress | "if a machine is waiting, query Parquet" **[DOC]** | medium — good for "is this host crawlable/alive" at bulk |
| **Common Crawl `cc-host-index`** | ~7 GB/crawl, **one row per host**, robots_2xx/4xx/5xx, fetch_2xx/4xx/5xx, hcrank10, prank10 **[DOC]** | free | S3/DuckDB | **HIGH for pre-screening** — tells you a host's robots and fetch behaviour before you spend a request |
| **Common Crawl → domain→org signal** | **none** — CC index stores URLs and HTTP metadata, no page text or org names | — | — | **NO — rule out**; WAT/WET name-scanning is petabyte-scale |
| **Certificate Transparency (crt.sh `O=`)** | Kresge → only `mail.kresge.org` (an OV cert); Surdna → **0**; one query 502'd **[MEASURED]** | free | fragile, frequent 5xx | **LOW recall** — most nonprofits use DV (Let's Encrypt) certs with no Organization field. Cheap long-shot only |
| **ProPublica Nonprofit Explorer API** | **no `website` field at all** — org keys are BMF-derived (name/address/city/state/ntee_code/…) **[MEASURED]** | free, no key | be polite | **discovery: NO. Verification: YES** (authoritative name + address per EIN) |
| **GivingTuesday 990 Data Commons** | 990/990PF/990EZ research extracts + no-auth API by EIN; Data Lake on AWS **[DOC]** | free | — | medium — a cleaner 990 pipeline than raw XML; same underlying field |
| **Candid / GuideStar** | proprietary website field, best-in-class | **~$3,499/yr** **[DOC, secondary]** | — | out of budget |
| **Charity Navigator API** | ratings/flags, limited universe | paid | — | low fit |
| **DuckDuckGo HTML scrape** | current GS workhorse | free | **ToS prohibits automated non-personal use**; 403s on detection; host robots is `Allow: /` **[MEASURED]** | works, but legally exposed — see §5 |
| **Brave Search API** | ~1,000 q/mo free credits, then **$5/1,000** **[DOC]** | ≈$555 for 111k | 50 qps | **downgraded** — no longer a bulk lane |
| **Mojeek Web Search API** | Startup **£2 CPM**, 5 qps, 100k/day **[DOC]** | ≈**£222 (~$280)** for 111k | independent index, ToS-clean for API use | **best paid option** — cheaper than Brave, no ToS grey area |
| **Marginalia API** | `public` key shared rate limit, 503 when hit; non-commercial key CC-BY-NC-SA; metered commercial key **[DOC]** | ~free | tiny index | low — index too small |
| **SearXNG self-hosted** | meta-layer over the same engines | "free" | **relocates the ToS problem, does not solve it**; from one IP most engines CAPTCHA; Brave/Startpage self-suspend; Google unparseable **[DOC]** | **NO** — GS has exactly one static IP, the worst case for SearXNG |

---

## 2. Summary table — legitimacy mechanisms

| Mechanism | Standard / authority | Status 2026 | GS status | Effort |
|---|---|---|---|---|
| **robots.txt compliance** | RFC 9309 | stable; being *updated* by `draft-ietf-aipref-attach` | honoured, but **fails open on fetch error — violates RFC 9309** (see §6) | small fix |
| **Stable UA + `From:`** | convention | universal | done (`GrantDiscoveryBot/1.0 (+https://bot.aigranthelper.com)`) | done |
| **Public bot info page** | Cloudflare policy expectation | required in practice | **live, HTTP 200** **[MEASURED]** | done |
| **Published IP list (JSON)** | Google/Cloudflare convention | the norm | **live** at `/ips.json`, Google prefix schema **[MEASURED]** | done |
| **Forward-confirmed rDNS** | Google/CC norm | the norm | **working today** — `5.78.196.28` ↔ `crawl-1.aigranthelper.com` **[MEASURED]** | **done (brief is stale)** |
| **Cloudflare Verified Bots** | Cloudflare | dashboard application; category taxonomy published | **not submitted** | 1 form + a category decision |
| **Web Bot Auth (HTTP Message Signatures)** | RFC 9421 + `draft-ietf-webbotauth-httpsig-protocol-00` (2026-09-01) | **chartered IETF WG**; Cloudflare, Akamai, Stytch verify today | **absent** — both well-known paths 404 **[MEASURED]** | Ed25519 keypair + a static JSON file + request signing |
| **`cf-mitigated: challenge` header** | Cloudflare | documented detection contract | not used | trivial, high value (§9) |
| **AIPREF / Content-Signals** | `draft-ietf-aipref-vocab-06`, `draft-ietf-aipref-attach-00` (2026-08-25) | Standards Track, in flight | not read | read-only; matters for positioning |

---

## 3. Common Crawl as a discovery source

### 3.1 What CC actually offers

- **CDX API** — `https://index.commoncrawl.org/CC-MAIN-2026-34-index?url=<host>/*&output=json`. 127 collections
  as of today, newest `CC-MAIN-2026-34`. **[MEASURED]**
- **Columnar index** — `s3://commoncrawl/cc-index/table/cc-main/warc/`, Parquet, partitioned by
  `crawl=` and `subset=`, ~300 GB per monthly crawl. Columns include `url_host_registered_domain`,
  `url_host_tld`, `fetch_status`, `content_languages`, `content_mime_type`, `warc_filename`,
  `warc_record_offset`, `warc_record_length`. Queryable with DuckDB, Athena, Spark, Polars.
  **[DOC]** https://commoncrawl.org/columnar-index — schema at https://github.com/commoncrawl/cc-index-table
- **`cc-host-index`** — the underused one. **One row per host**, ~7 GB/crawl Parquet, joining columnar
  index + web graph + crawler logs. Columns: `robots_200/3xx/4xx/5xx/gone/notModified/redirPerm/redirTemp`,
  `fetch_200/3xx/4xx/5xx/…`, `hcrank10`, `prank10`, `fetch_200_lote_pct`, `nutch_fetched`,
  `nutch_unfetched`, median/avg compressed record size.
  **[DOC]** https://github.com/commoncrawl/cc-host-index
- **Web graph / domain ranks** — e.g.
  `https://data.commoncrawl.org/projects/hyperlinkgraph/cc-main-2025-jun-jul-aug/domain/cc-main-2025-jun-jul-aug-domain-ranks.txt.gz`,
  **3,457,867,197 bytes** (3.46 GB gz), TSV with header
  `#harmonicc_pos  #harmonicc_val  #pr_pos  #pr_val  #host_rev  #n_hosts`, hosts stored reversed
  (`com.googleapis`). **[MEASURED]** Tools: https://github.com/commoncrawl/cc-webgraph

### 3.2 Measured coverage of foundation domains

Query: `CC-MAIN-2026-34`, `url=<domain>/*`, `limit=5`, one request per **6 seconds**, identifying UA.

```
gatesfoundation.org   HIT 5      surdna.org            HIT 5
fordfoundation.org    HIT 5      mott.org              HIT 5
rwjf.org              HIT 5      joycefdn.org          HIT 2
macfound.org          HIT 5      wkkf.org              HIT 5
hewlett.org           HIT 5      bushfoundation.org    HIT 5
mellon.org            HIT 5      hlsmithfoundation.org HTTP404 "No Captures found"
kresge.org            HIT 5      mardag.org            HTTP503  <-- rate limit
packard.org           HIT 5      cbrf.org              HIT 5
kauffman.org          HIT 5      weingartfnd.org       HIT 5
knightfoundation.org  HIT 5      stuartfoundation.org  HTTP504  <-- gateway timeout
```

**Read this two ways.**
- Coverage of *known-good* foundation domains is excellent: 17/17 that returned an answer were HITs.
  **[MEASURED]** So CC is a good oracle for "does this candidate domain exist and get crawled".
- The API is **not usable at 111k scale**: 2 of 20 queries failed at one request per six seconds.
  CC's own FAQ says the endpoint is "frequently abused and therefore heavily rate limited", 503 means
  slow down, and a blocked IP waits **24 hours** — a catastrophe for a single-static-IP crawler.
  **[DOC]** https://commoncrawl.org/faq

### 3.3 Does CC host a domain→org signal?

**No. [DOC/INFER]** The CDX and columnar indexes carry URLs, HTTP status, MIME, language and WARC
offsets — no titles, no page text, no organisation names. Getting "which domain belongs to org X" out
of CC requires scanning WET (extracted text) or WAT (metadata incl. `<title>`) across a whole crawl —
hundreds of TB of egress. **Rule it out for GS.** The web graph gives *link* structure, so it can
answer "which domains do known philanthropy hubs link to", which is a different and much weaker
question. **[INFER]**

### 3.4 Etiquette summary

CC's stated rule is the one to quote in GS's design doc: *"if a person is waiting for the answer, query
the API. If a machine is, query Parquet."* Plus `cc-downloader` as the sanctioned bulk client, HTTPS
only, and back off hard on 503. **[DOC]** https://commoncrawl.org/faq

---

## 4. Wikidata / Wikipedia

### 4.1 Measured P856 coverage (SPARQL, `query.wikidata.org`, 2026-09-07)

| Population | Entities | With P856 | Rate |
|---|---:|---:|---:|
| `wdt:P31/wdt:P279* wd:Q157031` (foundation) + `P17 = US` | **1,070** | **504** | 47% |
| `wdt:P31/wdt:P279* wd:Q163740` (nonprofit org) + `P17 = US` | **58,743** | **38,113** | 65% |
| Any entity with `P1297` (IRS EIN) | **17,221** | **15,050** | **87%** |

**[MEASURED]** — script at `scratchpad/search-research/wd_probe.py`.

**Interpretation.** `P1297` (EIN) is the join key GS wants: where it exists, a website exists 87% of the
time. But it exists for only 17,221 entities across all of Wikidata, against a ~300k-foundation corpus.
And the "US foundation" class itself holds only 1,070 items. **Wikidata's ceiling for GS is low
four figures, and GS has already run this provider. [INFER]** Do not fund further work here.

### 4.2 SPARQL etiquette (binding, not advisory)

- One client (UA + IP) gets **60 s of processing per 60 s**; over it → HTTP **429**; ignoring 429 → ban.
- 60 s query timeout on the public endpoint.
- **User-Agent policy is enforced** — a non-compliant UA can be blocked outright. GS's
  `GrantDiscoveryBot/1.0 (+https://bot.aigranthelper.com)` with a contact satisfies it.
- **[DOC]** https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/query_limits and
  https://wikitech.wikimedia.org/wiki/Wikidata_Query_Service/Technical_interactions

---

## 5. Name → domain resolution

### 5.1 The shape that actually works on a shoestring

The literature offers no drop-in "company name → domain" OSS library. What exists is components:

- **Fuzzy matching** — `rapidfuzz` (3.14.6, released 2026-08-30, actively maintained; C++ core)
  https://github.com/rapidfuzz/RapidFuzz ; `dedupe`, `zingg`, `dirty-cat` for record linkage.
  Survey list: https://github.com/J535D165/data-matching-software **[DOC]**
- **OpenSanctions `nomenklatura`** — a real enrichment *framework*: an `Enricher` ABC with `match()` →
  candidates and `expand()` → confirmed match + related entities, plus a `Resolver` that holds
  same/not-same/undecided judgements as a graph and computes connected components. Enrichers exist for
  Wikidata, OpenCorporates, Nominatim, yente, Aleph.
  https://github.com/opensanctions/nomenklatura , https://www.opensanctions.org/docs/enrichment/
  **[DOC]**
  **Fit:** the *Resolver* pattern — a durable, auditable table of "EIN X ↔ domain Y: yes / no / undecided",
  with provenance — is exactly what GS is missing (GS#2160, #2229, #2548 are all "a wrong answer got
  written and nothing recorded why"). Adopting the *pattern* is cheap; adopting the *library* pulls in
  FollowTheMoney's whole ontology and is probably not worth it. **[INFER]**
- **Clearbit-style OSS equivalents:** none of consequence. Clearbit's Name-to-Domain API was
  discontinued after the HubSpot acquisition; the "alternatives" in search results are all commercial.
  **[INFER — absence of evidence, searched and found nothing credible]**

### 5.2 The recommended pipeline (the domain-existence oracle)

```
foundation name + city + state
  → normalize   (strip "The", "Foundation", "Fund", "Trust", "Charitable", "Inc",
                 punctuation, ampersands; also produce an initialism)
  → generate    ~10-30 candidates × {.org, .com, .net}
                 e.g. "The Weingart Foundation" →
                 weingart.org, weingartfoundation.org, weingartfnd.org, weingartfdn.org, twf.org …
  → FILTER      against the offline registered-domain set   [ZERO network requests]
  → probe       DNS A/AAAA, then a single HTTPS GET, only on survivors
  → verify      §6 gate
  → resolve     write judgement + provenance, never a bare URL
```

The filter step is the whole point. Without it, 111k orgs × 20 candidates = **2.2M probes** at 5 s/host,
which is arithmetically impossible for GS. With it, **[INFER]** only a low-single-digit percentage of
candidates survive, and GS pays 5 s/host on a tractable set.

**Where to get the domain set:**
1. **ICANN CZDS** — free, requires an application per TLD, judged by each registry (Verisign for
   `.com`/`.net`, PIR for `.org`). Approval measured in weeks; >90% of requested zones typically approved.
   https://czds.icann.org/ , https://www.icann.org/resources/pages/czds-2014-03-03-en ;
   client: https://github.com/acidvegas/czds **[DOC]** Whether a two-person LLC clears PIR's bar for
   `.org` is **[INFER]** — likely yes with a specific, honest research purpose stated.
2. **Common Crawl domain ranks** — 3.46 GB gz, **available today, no approval**, and it comes with a
   popularity signal you can use to rank candidates. It is a *crawled-domain* set, not a *registered-domain*
   set, so it under-covers tiny dark sites — but a foundation site nobody links to is also one GS gains
   little from. **[MEASURED existence / INFER coverage]**

Start with #2 this week; file #1 in parallel because approval is slow.

### 5.3 IRS / sector data quality

- **990-PF does carry a website field**: Part VII-A Line 13, XML `WebsiteAddressTxt`, XPath
  `/IRS990PF/StatementsRegardingActyGrp/WebsiteAddressTxt` — but it is conditional on the
  public-inspection answer and effectively optional.
  http://www.irsx.info/metadata/parts/pf_part_viia.html **[DOC]**
- **No published study gives a fill rate.** I searched; the Nonprofit Open Data Collective's issue
  tracker (https://nonprofit-open-data-collective.github.io/irs-990-data-issue-tracker/) is the right
  venue and does not carry the number. **GS can and should measure its own fill rate from its own
  corpus** — it is a one-line SQL over `foundations`, and it is the honest denominator for the whole
  discovery epic. **[INFER: measurable in-house]**
- **ProPublica Nonprofit Explorer** — free, no key. Measured org keys for EIN 131684331:
  `accounting_period, activity_codes, address, affiliation_code, asset_amount, asset_code, careofname,
  city, classification_codes, ein, foundation_code, have_extracts, have_pdfs, income_amount, name,
  ntee_code, organization_code, revenue_amount, ruling_date, state, subsection_code, tax_period, zipcode`
  — **no `website`**. **[MEASURED]** https://projects.propublica.org/nonprofits/api
- **GivingTuesday 990 Data Commons** — research-ready 990/990-PF/990-EZ extracts, an AWS Data Lake, and
  an open no-auth API keyed by EIN. https://990data.givingtuesday.org/ **[DOC]** Worth evaluating as a
  cleaner replacement for GS's raw-XML path; it does not add a new website source.
- **Candid/GuideStar** ~$3,499/yr — out of budget. **Charity Navigator** — narrow universe, low fit.

---

## 6. Verifying the resolved site is the right org

### 6.1 What GS is defending against

GS#2160 / #2229 / #2548: an aggregator listing or another org's site wins over "no website". The rule
that fixes this is architectural, not heuristic:

> **A resolution must clear a positive-evidence gate. "No website" is the correct answer and must be
> reachable. A candidate that fails the gate is recorded as `rejected` with its reason, never silently
> dropped and never written as the answer.**

### 6.2 Cheap signals, ranked by measured usefulness

| Signal | Strength | Cost | Notes |
|---|---|---|---|
| **EIN string on page** (`\b\d{2}-?\d{7}\b` matching the org's EIN) | **decisive when present** | 1 fetch of `/`, `/about`, `/contact`, `/financials` | nonprofits print their EIN for donors' tax receipts. Highest-precision signal available |
| **Registrable domain ≠ known aggregator** | decisive negative | free | see §6.3 |
| **Normalized name token overlap** (title / `<h1>` / footer / `og:site_name` vs foundation name) | strong | free from the page already fetched | use `rapidfuzz.token_set_ratio` with a tuned floor |
| **City/state correspondence** (BMF address vs page address or `postal-code` microdata) | strong | free | ProPublica gives you the authoritative address per EIN for free |
| **Link to the org's own 990 PDF** or to `projects.propublica.org/nonprofits/organizations/<EIN>` | strong | free | many foundations link their own filings |
| **`mailto:` / contact domain == site domain** | moderate | free | |
| **schema.org `NonprofitOrganization` / `nonprofitStatus`** | **weak — do not rely on it** | free | schema.org reports `nonprofitStatus` usage at **1K–10K domains** (May 2026) **[DOC]** https://schema.org/nonprofitStatus |
| **WHOIS registrant org** | weak | rate-limited | GDPR/registrar redaction has gutted this **[INFER]** |
| **Certificate Transparency `O=` field** | **weak — measured** | free | Kresge → only `mail.kresge.org`; Surdna → 0 **[MEASURED]**. DV certs carry no `O=` |

**[INFER]** A defensible gate: accept only if **(EIN match)** OR **(name similarity ≥ threshold AND
city/state match)**. Anything else → `unverified`, which is not a website.

### 6.3 Detecting directory / aggregator listings

Two layers, both needed:

1. **A registrable-domain deny-list** — the cheapest control in the whole system, and the one GS is
   missing. Seed it with: `grantwatch.com`, `causeiq.com`, `projects.propublica.org`, `guidestar.org`,
   `candid.org`, `charitynavigator.org`, `taxexemptworld.com`, `nonprofitfacts.com`, `990finder.foundationcenter.org`,
   `grantmakers.io`, `instrumentl.com`, `foundationsearch.com`, `greatnonprofits.org`, `idealist.org`,
   `bizapedia.com`, `buzzfile.com`, `manta.com`, `dnb.com`, `zoominfo.com`, `opencorporates.com`,
   `linkedin.com`, `facebook.com`, `x.com`, `instagram.com`, `yelp.com`, `mapquest.com`, `sites.google.com`,
   plus donation/portal platforms (`givebutter.com`, `classy.org`, `networkforgood.com`, `submittable.com`,
   `foundant.com`, `fluxx.io`, `smartsimple.com`, `blackbaud.com`, `wizehive.com`, `benevity.com`) —
   GS already refuses to *follow* the portal vendors (GS#2471); the same list must also refuse to
   *resolve to* them. **[INFER — list assembled from domain knowledge, each host is real]**
2. **A structural test that catches unlisted aggregators.** An aggregator's page for org X is one row in
   a template: the same registrable domain resolves as the "website" for *many* different EINs. So:
   **if a candidate registrable domain is already the resolved website for ≥ N other foundations
   (N ≈ 3), reject it and add it to the deny-list automatically.** This is a single `GROUP BY` over GS's
   own `foundations` table, it needs no new data, and it generalises to aggregators nobody has heard of.
   **[INFER — this is my recommendation, not something I found published]**

Also reject: bare social-profile URLs, `Wayback` URLs, `sites.google.com/...` sub-paths, and any
resolution whose path is deeper than `/` unless the host itself verified.

### 6.4 Open-source implementations

There is no off-the-shelf "is this website this nonprofit" checker. The nearest reusable pieces are
`nomenklatura`'s match/expand/Resolver structure (§5.1) and `rapidfuzz` for the scoring. **[INFER]**

---

## 7. Free search alternatives — honest position

| Option | Reality in 2026 |
|---|---|
| **DDG HTML scrape (status quo)** | **[MEASURED]** `html.duckduckgo.com/robots.txt` = `Allow: /` — the host GS uses does not forbid crawling. `duckduckgo.com/robots.txt` = `Disallow: /html`, `Disallow: /lite`. **[DOC]** DDG's ToS prohibits automated, non-personal use and DDG serves 403 on detection. **Honest statement: GS is robots-compliant on the literal host it queries and in breach of DDG's contractual terms.** That is a business decision, not a technical one. Sending it under a *bare browser UA* (GS#2589) is the part that is hardest to defend, because it contradicts GS's own published identity policy — a crawler that declares itself everywhere except where declaring would get it blocked is not an honestly-identifying crawler. **Fix that first, regardless of the ToS question.** |
| **SearXNG self-hosted** | Does not create search capacity; it multiplexes the *same* engines from *your* IP. GS has exactly **one static egress IP**, which is the worst configuration for SearXNG. Documented failure modes: JSON API off by default, most engines CAPTCHA from a single IP, Brave and Startpage self-suspend on overuse, Google's results are now JS-rendered and unparseable. **[DOC]** https://apiserpent.com/blog/searxng-self-hosted-serp-api-tested — **Recommend against.** |
| **Brave Search API** | **$5 per 1,000 requests**, "$5 in free" monthly credits, 50 qps. **[DOC]** https://brave.com/search/api/ — ≈$555 for the 111k. No longer the free fallback the pipeline assumes. |
| **Mojeek Web Search API** | **£2 CPM** Startup (5 qps, 100k/day), £3 CPM Business. **[DOC]** https://www.mojeek.com/services/search/web-search-api/ — ≈**£222 / $280** for 111k, independent index, explicitly permits ML/LLM use, and — unlike DDG — is a *licensed* API with no ToS grey area. Note Mojeek's own ToS forbids scraping its SERP while permitting robots-compliant crawling. **Best paid option by a wide margin.** |
| **Marginalia** | `public` key has a shared rate limit and 503s; non-commercial key is CC-BY-NC-SA; index is tiny and idiosyncratic. **[DOC]** https://api.marginalia.nu/ — not viable at 111k. |
| **Bing / Google** | Bing's Search API was retired for new customers; Google CSE is capped and expensive. **[INFER]** Neither is a shoestring lane. |

**Verdict:** there is no free, ToS-clean, 111k-scale search. The choice is between (a) spending ~$280
once at Mojeek, and (b) not using search at all — which is what §5.2's domain oracle makes possible.
Do (b) first; it costs nothing and will resolve the easy majority. Spend Mojeek money on the residue.

---

## 8. Bot legitimacy

### 8.1 robots.txt libraries (measured from PyPI)

| Library | Latest | Released | License | Verdict |
|---|---|---|---|---|
| **`protego`** | 0.6.2 | **2026-06-25** | BSD | **Use this.** Scrapy's parser. Wildcards, `$`, longest-match ordering, `Sitemap`, **`Crawl-delay`**, `Request-rate`. |
| `robotspy` | 0.13.0 | 2026-03-01 | MIT | Maintained, RFC 9309-focused, but **deliberately omits `Crawl-delay`** — GS needs it |
| `reppy` | 0.4.14 | **2019-09-16** | MIT | **Unmaintained (7 years).** Do not adopt |
| `robotexclusionrulesparser` | 1.7.1 | **2016-08-12** | BSD | **Dead (10 years).** Do not adopt |
| `urllib.robotparser` | stdlib | — | PSF | Gaps: no `$` anchor, weak wildcard handling, no longest-match specificity, no sitemap extraction. **Insufficient** |

**[MEASURED]** — PyPI JSON API, this session.

### 8.2 RFC 9309 semantics GS must implement (quoted)

- **5xx / network error:** *"If the robots.txt file is unreachable due to server or network errors, this
  means the robots.txt file is undefined and the crawler MUST assume complete disallow."* Relief only
  after a long period: *"If the robots.txt file is undefined for a reasonably long period of time (for
  example, 30 days), crawlers MAY assume that the robots.txt file is unavailable."*
- **4xx:** *"If a server status code indicates that the robots.txt file is unavailable to the crawler,
  then the crawler MAY access any resources on the server."*
- **3xx:** follow **at least five** consecutive redirects, even across authorities; beyond five, MAY treat
  as unavailable.
- **Caching:** *"Crawlers SHOULD NOT use the cached version for more than 24 hours, unless the robots.txt
  file is unreachable."*
- **Matching:** `*` = 0+ chars, `$` = end-of-pattern, `#` = comment. *"The most specific match found MUST
  be used. The most specific match is the match that has the most octets."*
- **Size:** *"The parsing limit MUST be at least 500 kibibytes."*
- **`Crawl-delay` is not in RFC 9309 at all** — it is convention. GS's 5 s floor is therefore a
  self-imposed courtesy above the standard, which is the right posture.

**[DOC]** https://www.rfc-editor.org/rfc/rfc9309.html

> **GS defect:** the brief states GS's robots gate **fails open on fetch errors**. RFC 9309 requires the
> opposite for 5xx/network errors. This is a real compliance bug and it is precisely the kind of thing
> Cloudflare's Verified Bots policy lists as disqualifying behaviour. **The correct behaviour is a
> three-way outcome — `allow` (4xx), `disallow` (5xx/timeout, for up to 30 days), `honour rules` (2xx) —
> not a boolean.** Note this makes "could not look" distinguishable from "may crawl", which is the same
> discipline the estate already applies to sweep exit codes.

### 8.3 Cloudflare Verified Bots

**Policy — two bars [DOC]** https://developers.cloudflare.com/bots/concepts/bot/verified-bots/policy/
1. *"it declares who it is deterministically, through a cryptographic Web Bot Auth signature, a published
   IP list with a stable user-agent, or reverse DNS."*
2. *"it obeys `robots.txt` and crawl directives, maintains reasonable request rates, and has not been
   observed evading website owner preferences or attacking sites."*

**Disqualifying:** IPs not solely used by the verified service; compromised IPs; unpatched vulnerabilities;
IP blocks added without onboarding notice; *"the disclosed purpose of the service does not reflect on the
traffic"*; an AI Crawler that ignores `crawl-delay`.

**GS meets bar 1 today** (published IP list + stable UA + working FCrDNS, all **[MEASURED]**).
**GS does not currently meet bar 2** because of the fail-open robots gate (§8.2) and the browser-shaped
UA used against state procurement portals (GS#2584) — the latter is exactly *"evading website owner
preferences"* as written, and it is on the same egress IP the allowlist declares. **[INFER, but the policy
text is unambiguous]** Fix both before applying; an application that is later revoked is worse than none.

**Category (§ this is the positioning question).** Cloudflare's taxonomy **[DOC]**
https://developers.cloudflare.com/bots/reference/verified-bot-categories : Academic Research,
Accessibility, Advertising & Marketing, **Aggregator**, AI Assistant, **AI Crawler**, AI Search, Archiver,
Feed Fetcher, Monitoring & Analytics, Page Preview, Search Engine Crawler, Search Engine Optimization,
Security, Social Media Marketing, Webhooks, Other.

> **Recommendation: apply as `Aggregator`** — *"Collects content from various online sources and
> consolidates it"* — which is literally what GS does, and which sits on the *permitted* side of every
> AI-blocking default. Do **not** apply as `AI Crawler` (*"Crawls websites for content used for training
> AI models"*) — GS does not train models, and that category is the one being blocked by default.
> `Academic Research` is defensible but GS is a commercial SaaS input, so `Aggregator` is the honest
> answer and honesty is the whole point of the programme. **[INFER on the choice; categories are DOC]**

### 8.4 Web Bot Auth

- **Chartered IETF WG.** `draft-ietf-webbotauth-httpsig-protocol-00`, **2026-09-01**, 44 pages.
  Related individual drafts: `draft-meunier-webbotauth-registry-03`, `draft-nottingham-webbotauth-use-cases-02`,
  `draft-illyes-webbotauth-cbcp-00` / `-jafar-00`, `draft-rescorla-anonymous-webbotauth-01`,
  `draft-singh-webbotauth-hosted-directories-00`. **[DOC]** https://datatracker.ietf.org/group/webbotauth/documents/
- **Mechanics.** Built on **RFC 9421** HTTP Message Signatures. Request carries `Signature`,
  `Signature-Input` and `Signature-Agent`. `Signature-Input` must include `created`, `expires`,
  `keyid` (*"base64url JWK SHA-256 Thumbprint"*) and `tag="web-bot-auth"`; covered components must include
  at least `"@authority"` or `"@target-uri"`. Ed25519 in practice. Key directory (JWKS) served at
  **`/.well-known/http-message-signatures-directory`** — this is the registered path in the WG draft;
  Cloudflare's older blog says `http-message-signature-key-set`, so **serve both** to be safe. **[DOC]**
- **Adoption.** Cloudflare, Akamai and Stytch verify signatures today. Cloudflare's own Radar URL Scanner
  is registered this way. Cloudflare states *"Bots applying with well-formed Message Signatures will be
  prioritized, and approved more quickly."* **[DOC]** https://blog.cloudflare.com/verified-bots-with-cryptography/
- **Open-source signers:** `cloudflare/web-bot-auth` (Apache-2.0, npm + cargo workspaces),
  `stytchauth/web-bot-auth-example`, `thibmeu/http-message-signatures-directory`, OpenBotAuth
  (proxy verifier, Docker). **[DOC]** No mature *Python* signer surfaced — GS would implement RFC 9421
  Ed25519 signing directly, which is ~60 lines against `cryptography`. **[INFER]**
- **GS gap [MEASURED]:** `https://bot.aigranthelper.com/.well-known/http-message-signatures-directory` → **404**;
  `.../http-message-signature-key-set` → **404**; `/ips.json` → **200**.

### 8.5 How respected crawlers declare identity

| Crawler | Declaration |
|---|---|
| **CCBot** | FCrDNS to `*.crawl.commoncrawl.org` **plus** a published prefix list at `https://index.commoncrawl.org/ccbot.json`. **[MEASURED]** — that file today has `synctoken 20260811134000`, 5 prefixes (1 IPv6 `/56`, 4 IPv4 `/29`–`/30`), and the note *"For verification of IPv4 addresses, FCrDNS is also recommended."* **This is the exact model GS's `ips.json` already copies — GS is in good company.** |
| **Googlebot** | `common-crawlers.json` (formerly `googlebot.json`), `special-crawlers.json`, `user-triggered-fetchers.json` at `developers.google.com/search/apis/ipranges/`, plus FCrDNS to `googlebot.com` / `google.com` / `googleusercontent.com` **[DOC]** |
| **Bingbot / Applebot / PerplexityBot** | published IP lists — but reported **stale by over a year** as of 2026-08-13, versus Google's and OpenAI's refreshed daily **[DOC, secondary]** https://umesh-malik.com/blog/verify-ai-crawler-ips-not-user-agents |
| **ClaudeBot / GPTBot** | published IP ranges + stable UA **[DOC, secondary]** |
| **Archive.org** | Heritrix-family UA with a contact URL; historically honoured `ia_archiver` robots directives (DDG's robots still carries `User-agent: ia_archiver / Disallow: /` **[MEASURED]**) |

**GS's `ips.json` is well-formed and follows the Google/Cloudflare convention, with `rdns`, `operator`
and `purpose` annotations that most operators omit.** The one weakness: a **single `/32`**. Cloudflare's
policy requires IPs *solely* used by the verified service — that is satisfied — but a single IP means one
mistaken rate-limit trip takes the whole crawler down, and it makes the GS#2584 browser-UA traffic
attributable to the declared crawler. **[INFER]**

### 8.6 The 2026 AI-crawler blocking landscape, and how GS avoids being swept up

- **Cloudflare blocks AI crawlers by default for newly created domains** (*"Block on all pages" is now the
  default*), and offers **Pay Per Crawl** (reviving HTTP **402**) in beta. **[DOC]**
  https://developers.cloudflare.com/ai-crawl-control/features/manage-ai-crawlers
- **Content Signals Policy** — Cloudflare prepends a policy block to managed `robots.txt` across
  **3.8M+ domains**, with three signals — `search`, `ai-input`, `ai-train` — defaulting to
  `search=yes, ai-train=no`. It is a *stated preference*, not enforcement. **[DOC]**
  https://blog.cloudflare.com/control-content-use-for-ai-training/
- **IETF AIPREF** — `draft-ietf-aipref-vocab-06` (Proposed Standard track; defines `train-ai` and `search`
  with y/n values) and `draft-ietf-aipref-attach-00` (2026-08-25, Standards Track, **updates RFC 9309** to
  carry usage preferences, and defines a `Content-Usage` HTTP response header as an RFC 9651 structured
  dictionary, e.g. `Content-Usage: train-ai=n`). **[DOC]**
  https://datatracker.ietf.org/wg/aipref/about/ , https://ietf-wg-aipref.github.io/drafts/draft-ietf-aipref-attach.html
- **`ai.txt`** — `draft-car-ai-txt-wellknown-00`, an individual draft, not WG-adopted. **Low priority.**
- **AI Labyrinth** — Cloudflare injects **invisible, `nofollow`** links to trap non-compliant crawlers.
  **[DOC]** https://www.cloudflare.com/learning/ai/how-to-block-ai-crawlers/
  > **Direct risk to GS:** the sitemap path is safe (Labyrinth links are not in sitemaps), but the
  > **homepage shallow-crawl fallback follows links** and could walk straight in — burning the 12-hour
  > window on synthetic pages and looking exactly like a bad actor. **Mitigation: in the shallow-crawl
  > fallback, skip `rel="nofollow"` links and links hidden by inline style/aria — and cap fallback depth
  > hard.** **[INFER, but the mechanism is documented]**

**GS's positioning statement**, which should appear verbatim on `bot.aigranthelper.com`:

> GrantDiscoveryBot is an **aggregator**, not an AI crawler. It fetches publicly posted grant guidelines,
> deadlines and eligibility criteria so that small nonprofits can find funding they qualify for. **It does
> not train models on the content it fetches.** It honours `robots.txt` including `Crawl-delay`, honours
> AIPREF `Content-Usage` and Cloudflare Content-Signal directives where present, waits a minimum of 5
> seconds between requests to any one host, crawls from a single published IP with forward-confirmed
> reverse DNS, and never circumvents a technical block.

**[INFER]** The `ai-train=n` default that Cloudflare pushed to 3.8M domains is *not* a signal GS must
obey — GS does not train — but **stating that GS reads and respects it anyway** is the cheapest possible
credibility purchase, and it distinguishes GS from every crawler that ignores the field.

---

## 9. Honest classification of fetch outcomes

The estate rule *"a skip must not read as a pass"* applies directly: **"blocked", "empty", "down",
"soft-404" and "parked" are five different facts and must never collapse into one verdict class.** The
brief already records that an earlier verdict class mislabelled "blocked" as a data class — this is the
detection contract that prevents a repeat.

| Outcome | Detection signals |
|---|---|
| **BLOCKED (challenge)** | **`cf-mitigated: challenge` response header** — Cloudflare's own documented contract, present *regardless of challenge type*; also body containing `cdn-cgi/challenge-platform` or `cf-turnstile`. Cloudflare explicitly advises detecting the **header, not the status code**, because it may be 403 *or* 503. **[DOC]** https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/ |
| **BLOCKED (WAF/other)** | 403 with `server: AkamaiGHost` / `x-iinfo` (Imperva) / `x-sucuri-id`; 406/429 with a vendor-branded body; body length < ~2 KB with no `<main>`/`<article>` |
| **BLOCKED (paywall)** | **HTTP 402** — new signal in 2026 via Cloudflare Pay Per Crawl. Classify explicitly; it will grow **[DOC]** |
| **EMPTY (SPA shell)** | HTTP 200, `text/html`, `trafilatura` yields < ~200 chars, **and** the body contains a hydration marker (`__NEXT_DATA__`, `__NUXT__`, `window.__APOLLO_STATE__`, `id="root"`/`id="__next"` with no siblings). Distinguish from soft-404 by the presence of the marker |
| **DOWN** | DNS NXDOMAIN / no A record; TCP refused; TLS failure; connect timeout; 5xx persisting across ≥2 attempts ≥1 h apart |
| **SOFT-404** | HTTP 200 whose content matches a control fetch of a **known-bad URL on the same host** (`/<random-uuid>`). This is the technique in `benhoyt/soft404` (https://github.com/benhoyt/soft404) and it needs no model. ML classifiers exist — `dogancanbakir/soft-404` (trained on 198,801 pages / 35,995 domains, https://pypi.org/project/soft-404/) and the Internet Archive's tree-model/BERT `internetarchive/tarb_soft404` — but **the control-fetch heuristic is the right cost/benefit for GS** and costs one extra request per host, once |
| **PARKED** | 200 + very small body + registrar/parking phrases (*"this domain may be for sale"*, *"buy this domain"*, *"parked free courtesy of"*) + NS/A pointing at a known parking provider (Sedo, Afternic, GoDaddy, Bodis, ParkingCrew). References: https://github.com/anirband/Parking , https://medium.com/radius-engineering/parking-lot-identifying-parked-websites-with-machine-learning-b1efbf291cbe **[DOC]** |

**[INFER]** Store the outcome as a typed enum on `mine_urls` / the foundation record, alongside the
evidence that produced it (the header value, the marker string, the control-fetch hash). A verdict
without its evidence cannot be audited later, and GS#2160's class of bug is exactly an unauditable verdict.

---

## 10. Ranked recommendations for GS

### A. Discovery of the 111k websiteless grantmakers

1. **Build the offline domain-existence oracle (highest value, ~2 days, $0).** Download the Common Crawl
   domain-ranks file (3.46 GB gz, no approval), load reversed hosts into a Postgres table or a Bloom
   filter. Generate normalized candidate domains per foundation and filter against it **before any
   network request**. This converts an impossible 2.2M-probe problem into a tractable one and gives you
   a popularity rank to order candidates by. **[MEASURED existence; INFER yield]**
2. **File the ICANN CZDS application for `.org` and `.com` in parallel (day 1, $0, weeks of latency).**
   It supersedes #1 with a true registered-domain universe. Approval is slow, so start now; nothing
   downstream blocks on it. **[DOC]**
3. **Measure the 990/990-PF `WebsiteAddressTxt` fill rate over GS's own corpus (one afternoon).** No
   published study exists. This is the honest denominator for the whole epic and it is one SQL query.
   **[INFER — measurable in-house]**
4. **Stop treating Brave as a bulk lane.** It is now ~1,000 queries/month free, $5/1,000 thereafter.
   Rewrite the provider-chain assumption in the code and the docs, or the pipeline will quietly stall
   or quietly bill. **[DOC]** — *this is the finding most likely to be load-bearing today.*
5. **If a paid search lane is wanted, use Mojeek, not Brave.** £2 CPM ≈ $280 for the whole 111k, an
   independent index, a real licence, no ToS grey area. Spend it on the residue *after* #1. **[DOC]**
6. **Fix the DDG user-agent regardless of the ToS decision (GS#2589).** A crawler that publishes an
   identity policy and then hides behind a browser UA where it matters has no identity policy. Either
   query DDG as GrantDiscoveryBot and accept the 403 rate, or stop querying DDG. **[INFER]**
7. **Do not build SearXNG.** One static IP is the worst possible host for it. **[DOC]**
8. **Rule out Common Crawl for name→domain.** No text, no org names. Keep CC for *verification* and
   *pre-screening* only. **[DOC/INFER]**
9. **Do not fund more Wikidata work.** Measured ceiling is low four figures. **[MEASURED]**
10. **Cheap long-shot, last:** crt.sh `O=` search. Measured recall is poor, but it is free and
    high-precision when it fires. Batch it; never block on it. **[MEASURED]**

### B. A verification gate at resolution time

11. **Make "no website" a first-class, reachable answer, and record rejections with reasons.** Adopt
    `nomenklatura`'s *pattern*: an explicit judgement (`confirmed` / `rejected` / `unverified`) with
    provenance, not a nullable URL column. **[INFER — this is the structural fix for GS#2160/#2229/#2548]**
12. **Ship the aggregator deny-list before anything else in this section (one afternoon).** §6.3 layer 1.
    Cheapest control in the system.
13. **Ship the "one domain, many EINs" auto-detector (§6.3 layer 2).** A `GROUP BY` over GS's existing
    data that catches aggregators nobody listed. Threshold N≈3. **[INFER — my recommendation]**
14. **Gate on positive evidence: EIN-on-page, OR (name similarity AND city/state match).** Use
    `rapidfuzz`; get the authoritative name/address per EIN free from ProPublica. **[MEASURED that
    ProPublica supplies these and not a website]**
15. **Do not build anything on schema.org `NonprofitOrganization`.** 1K–10K domains of adoption. **[DOC]**
16. **Ship the negative fixtures with the gate.** Per estate doctrine, a verification gate that has never
    been seen reject a known-bad resolution is decoration. Use the three real failures (GS#2160, #2229,
    #2548) as the fixture set, and mutate the gate to confirm each fixture goes red.

### C. The identity roadmap

17. **Fix the robots fail-open (small diff, largest legitimacy return).** RFC 9309 requires
    *complete disallow* on 5xx/network error, with relief only after ~30 days; 4xx means allow. Make it a
    three-way outcome so "could not look" is distinguishable from "may crawl". **[DOC]**
18. **Adopt `protego` as the robots parser** (0.6.2, 2026-06-25) — the only maintained option that also
    parses `Crawl-delay`, which GS depends on. Retire any `reppy` (2019) or
    `robotexclusionrulesparser` (2016) usage. **[MEASURED]**
19. **Resolve GS#2584 before applying for Verified Bots.** The browser-shaped UA against state
    procurement portals reads as *"evading website owner preferences"* under Cloudflare's written policy,
    on the same IP the allowlist declares. Either drop it, or move it to a separately-declared identity
    on a separate IP and describe it honestly on the bot page. **[DOC on the policy; INFER on the risk]**
20. **Then apply to Cloudflare Verified Bots as category `Aggregator`.** GS already satisfies the
    deterministic-declaration bar three ways over (published IP list, stable UA, working FCrDNS —
    **all measured live**). **[DOC]**
21. **Ship Web Bot Auth.** Generate an Ed25519 keypair, serve the JWKS at
    **`/.well-known/http-message-signatures-directory`** (and mirror it at `http-message-signature-key-set`
    for Cloudflare's older documented path), sign requests with `Signature` / `Signature-Input`
    (`created`, `expires`, `keyid`, `tag="web-bot-auth"`, covering `@authority`) / `Signature-Agent`.
    Cloudflare *prioritises* signature applications. `cloudflare/web-bot-auth` (Apache-2.0) is the
    reference; expect to write the Python signer yourself (~60 lines on `cryptography`). **[DOC + MEASURED gap]**
22. **Publish the "not an AI crawler" statement (§8.6) and state that GS reads AIPREF `Content-Usage`
    and Cloudflare Content-Signals.** Track `draft-ietf-aipref-attach` — it **updates RFC 9309**, so GS's
    robots parser will need to carry usage preferences within a year. **[DOC]**
23. **Harden the homepage shallow-crawl fallback against AI Labyrinth**: skip `rel="nofollow"` and
    visually-hidden links, cap depth. **[INFER, documented mechanism]**
24. **Add the second egress IP when budget allows.** A single `/32` is a single point of failure for the
    whole corpus and makes every sub-identity's behaviour attributable to the main one. **[INFER]**

---

## Sources

**Common Crawl** — https://commoncrawl.org/columnar-index · https://commoncrawl.org/faq ·
https://commoncrawl.org/url-index · https://commoncrawl.org/cdxj-index ·
https://github.com/commoncrawl/cc-index-table · https://github.com/commoncrawl/cc-host-index ·
https://github.com/commoncrawl/cc-webgraph · https://github.com/commoncrawl/cdx_toolkit ·
https://index.commoncrawl.org/ccbot.json · https://commoncrawl.github.io/cc-webgraph-statistics/

**Wikidata** — https://www.wikidata.org/wiki/Property:P856 ·
https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/query_limits ·
https://wikitech.wikimedia.org/wiki/Wikidata_Query_Service/Technical_interactions

**Nonprofit data** — https://projects.propublica.org/nonprofits/api ·
https://990data.givingtuesday.org/ · https://data.givingtuesday.org/datasets/ ·
http://www.irsx.info/metadata/parts/pf_part_viia.html ·
https://nonprofit-open-data-collective.github.io/irs-990-data-issue-tracker/ ·
https://github.com/Giving-Tuesday/form-990-xml-mapper

**Name→domain / matching** — https://github.com/opensanctions/nomenklatura ·
https://www.opensanctions.org/docs/enrichment/ · https://github.com/rapidfuzz/RapidFuzz ·
https://github.com/J535D165/data-matching-software · https://czds.icann.org/ ·
https://www.icann.org/resources/pages/czds-2014-03-03-en · https://github.com/acidvegas/czds ·
https://schema.org/nonprofitStatus

**Search providers** — https://brave.com/search/api/ ·
https://www.mojeek.com/services/search/web-search-api/ · https://www.mojeek.com/about/terms.html ·
https://api.marginalia.nu/ · https://apiserpent.com/blog/searxng-self-hosted-serp-api-tested ·
https://www.implicator.ai/brave-drops-free-search-api-tier-puts-all-developers-on-metered-billing/

**Robots / standards** — https://www.rfc-editor.org/rfc/rfc9309.html ·
https://pypi.org/project/Protego/ · https://github.com/andreburgaud/robotspy ·
https://github.com/seomoz/reppy · https://github.com/scrapy/scrapy/issues/3969

**Bot identity** — https://developers.cloudflare.com/bots/concepts/bot/verified-bots/policy/ ·
https://developers.cloudflare.com/bots/reference/verified-bot-categories/ ·
https://blog.cloudflare.com/verified-bots-with-cryptography/ ·
https://datatracker.ietf.org/group/webbotauth/documents/ ·
https://datatracker.ietf.org/doc/html/draft-meunier-web-bot-auth-architecture ·
https://github.com/cloudflare/web-bot-auth · https://github.com/stytchauth/web-bot-auth-example ·
https://github.com/thibmeu/http-message-signatures-directory ·
https://developers.google.com/search/apis/ipranges/googlebot.json ·
https://umesh-malik.com/blog/verify-ai-crawler-ips-not-user-agents

**AI-crawler landscape** — https://developers.cloudflare.com/ai-crawl-control/ ·
https://blog.cloudflare.com/control-content-use-for-ai-training/ ·
https://www.cloudflare.com/learning/ai/how-to-block-ai-crawlers/ ·
https://datatracker.ietf.org/wg/aipref/about/ ·
https://ietf-wg-aipref.github.io/drafts/draft-ietf-aipref-attach.html ·
https://www.ietf.org/archive/id/draft-car-ai-txt-wellknown-00.html

**Fetch-outcome classification** —
https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/ ·
https://http.dev/cf-mitigated · https://github.com/benhoyt/soft404 ·
https://github.com/dogancanbakir/soft-404 · https://github.com/internetarchive/tarb_soft404 ·
https://github.com/anirband/Parking

**Wayback** — https://github.com/internetarchive/wayback/blob/master/wayback-cdx-server/README.md ·
https://archive.org/help/wayback_api.php

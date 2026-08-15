ABOUTME: Cross-repo audit of aigranthelper + grantspider and the commercial path to 1,000 paying clients.
ABOUTME: Four-agent technical audit plus market research, with findings corrected against live Railway and production state.

# AI Grant Helper + GrantSpider — Technical Audit & Path to 1,000 Clients

**Date:** 2026-07-29
**Refs audited:** AG `origin/main` 38b76cc / `origin/staging` 47a2d4c · GS `origin/main` 9af061f
**Method:** four independent Fable-model auditors (architecture, data pipeline, commercial readiness, ops/cost) + market research + live verification against Railway and both production environments

---

## Verification log — what changed after checking

The audits were code reads. Several claims were then checked against live
infrastructure. Three were wrong and one grew much larger.

**Corrected — `B2_ENDPOINT_URL` is set** on AG production *and* staging, along
with all six other B2 keys. **Customer document uploads and Studio drafts are
working.** `docs/operations/tenant-db-backup.md` recorded it absent on
2026-06-09 and was never updated after the fix. The runbook's described failure
mode is also wrong: `boto3.client(endpoint_url="")` raises
`ValueError: Invalid endpoint`, it does not silently target AWS S3 — and the
storage factories switch on `B2_ORG_DOCS_BUCKET_NAME` / `B2_STUDIO_BUCKET_NAME`
anyway, not on the endpoint.

**Corrected — AG's local `make verify` gate is green.** The stale
`test_research` database (missing `gov_opportunities.embedding`) breaks
`tests/test_archived_gov_opportunities.py` but does not affect `make verify`.

**Corrected — `ADMINS` was never an environment variable.** It is a Django
setting never assigned in `config/`. Setting a Railway variable would have done
nothing. Fixed in code — **AG #1337**.

**Grew — the cron gap.** See below. This is now the largest finding in the
report and it reorders everything downstream of it.

**Confirmed as audited:** GS enrichment coverage 2.7%; GS has no Sentry (now
fixed, **GS #1960**); `GRANTSPIDER_SMTP_HOST` absent on all four services;
`settings.ADMINS` empty; AG tenant DB backup unscheduled; no `healthcheckPath`
in either repo.

**Also confirmed, in GS's favour:** GS is *not* missing its schedulers. Three
Railway crons exist and are correct (`embedding` daily 05:00, `embedding_gov`
daily 06:00, `embedding_pages` Sunday 07:00 — matching your ruling), all four
services are online, and `dagster-code` being up means the #1829 gRPC cutover
is done. GS's problem is deafness, not idleness.

---

## The cron gap — the finding that reorders the plan

AG production runs **exactly one** Railway cron:

```
Cron jobs
  - render_sitemaps: ● Online · 0 0 * * *
```

The repo ships **26 management commands**. The `Procfile` is a single `web`
process. There is no Celery, APScheduler, django-q, huey, or rq in the
dependency tree, and no GitHub Actions workflow invokes any of them.
**Twenty-five of those commands have never run on a schedule in production.**

| Command | Consequence |
|---|---|
| `send_onboarding_emails` | The drip doesn't end at day 5 — **it never sends at all** |
| `send_deadline_reminders` | Advertised on the landing page as live. Has never fired. |
| `submit_seo_urls` | The IndexNow submitter — never run |
| `monitor_indexation` | GSC sweep — never run, so the indexation trend table is empty |
| `send_renewal_notifications` | Never run |
| `send_weekly_org_digest`, `send_stale_pipeline_digest` | Never run |
| `detect_onboarding_stalls`, `detect_stuck_drafts` | Never run |
| `telemetry_archive_to_b2`, `telemetry_retention` | Never run; `TELEMETRY_B2_BUCKET_NAME` absent |
| `backup_database` | Never run |

Three consequences worth sitting with:

1. **The SEO problem is probably not "Google is slow with a new domain."**
   `submit_seo_urls` and `monitor_indexation` are the engine meant to drive
   indexation and neither has ever executed. The production-deploy checklist
   has both items literally unchecked (`docs/operations/production-deploy.md`
   lines 235-237). **282 indexed pages is what "never pinged anything" looks
   like.** Also `render_sitemaps` runs daily, not the documented `0 */6 * * *`.

2. **Telemetry is destroyed on every deploy.** Railway's filesystem is
   ephemeral, the archive bucket variable is unset, and the archive cron does
   not exist. There is no behavioural history to analyse even if PostHog were
   installed tomorrow.

3. **Building the trial-expiry email before the scheduler produces dead code.**
   Nothing in production can send a scheduled email.

---

# PART I — THE TECHNICAL AUDIT

## Grades

| Dimension | Grade | One-line verdict |
|---|---|---|
| AG architecture & code quality | **B+** | Disciplined and genuinely well-built. Three structural risks, all fixable. |
| GS corpus — "good enough to charge for" | **C+** | IRS spine is a real asset. The web layer you actually sell covers 2.7%. |
| Commercial readiness | **C** | Plumbing works. Nothing at the top of the funnel, and promises the code doesn't keep. |
| Ops resilience & cost | **C+** | Automatable by one person, but "error recorded" ≠ "Nathan told." |

**Overall: B−.** You have built more real software than most funded teams. The engineering is not the problem. Every finding below is either a small gap or a business gap wearing an engineering costume.

---

## The single most important finding

These four audits, run independently, converge on one causal chain:

```
GS has web-enriched only 5,359 of 195,256 eligible grantmakers (2.7%)
        ↓
~131,000 of your 142,737 public foundation pages are thin
        ↓                    ↘
Google indexed 282           the IndexNow submitter and GSC sweep
of 142,737 submitted           have never run — no cron exists
        ↓                    ↙
Zero organic traffic
        ↓
Zero customers
```

*Revised after live verification:* thin pages are one cause; **never having
pinged a search engine is the other, and it is the cheaper of the two to fix.**
Do both — the cron this week, #1929 over the following months.

**GS issue #1929 — the homepage-fallback crawl for the 32,500 grantmakers with no sitemap — is not a data-engineering chore. It is your single largest marketing investment.** 45,699 sites were reached but only ~8,400 yielded a crawlable URL; enrichment converts 63% of sites that do yield content. Closing that leak multiplies sellable coverage roughly 4x, and it is what turns thin pages into pages Google will index.

Treat it as a growth ticket and fund it like one.

---

## AG architecture (B+)

**What's genuinely good — stated plainly so you don't over-correct:** views delegate to services (17,074 service lines vs 8,200 view lines); the LLM layer has a proper retry/error taxonomy, prompt-injection wrapping, and org-scoped rate limits; the Stripe webhook goes through dj-stripe with signature verification *plus* a session re-fetch that defeats forged `client_reference_id`; 3,654 tests across 279 files; the boy-scout ratchet is pointing at the genuinely worst files and is not obstructing delivery (1,300+ merged PRs). Dependency hygiene is better than most commercial shops.

**The three real risks:**

1. **Tenant isolation is convention, not structure.** `apps/core/middleware.py:96-102` says so in its own docstring: isolation is enforced by application-layer `organization=` filters, not RLS — and the `app.current_org` GUC it sets is read by no policy. There are 49 hand-written `organization=` filters in `apps/pipeline/views.py` alone and zero org-scoped model managers. No leak was found in sampled paths, but the guarantee is only as good as every future PR remembering. **The GUC plumbing already exists per-request** — adding RLS policies, or at minimum default org-scoped managers on `FunderRelationship` / `Application` / `Deadline` / `GrantDraft`, converts a per-PR vigilance problem into a schema guarantee. Highest-leverage change in the codebase.

2. **No monthly LLM spend ceiling.** Burst limits exist (30 generations/hour, 60 analyses/hour). Aggregate limits do not. A free-tier org can legally burn 30 × 4,096 output tokens per hour, indefinitely, across N orgs. At $20/mo pricing this is the one line that can make a customer unprofitable. A monthly token counter on `Organization`, checked in the existing decorator stack, is a day of work.

3. **The app graph is a mutual-import tangle** — accounts↔billing, pipeline↔research↔studio, and a `core` app that imports *upward* from `apps.accounts` and `apps.research`. Cycles are broken at runtime by function-level lazy imports, so import order is load-bearing. `apps/billing/webhooks.py:12-16` restructures imports specifically to blind gaudi's cycle detector — that's the one place the ratchet is being gamed rather than maintained.

**Smaller flags:** both `psycopg[binary]` and `psycopg2-binary` are declared; `torch` + `sentence-transformers` are in the *web app's* dependency tree (verify where `sentence_transformers` is imported — if embeddings arrive from GS, that's a large cold-start penalty for nothing); no webhook replay/idempotency test exists — given `stripe<12` already bit you once, that's the most valuable missing test.

---

## GS data pipeline (C+)

**The asset is real:** ~300k foundations, 6.17M grant lines, 97% entity-embedded, monthly IRS refresh, nightly backups with a *monthly restore drill that actually runs*. Freshness discipline and observability are unusually good for a solo project.

**The problems are coverage and cost:**

- **Funnel drop-off (prod-verified 2026-07-24, #1929):** 195,256 eligible → 57,415 with a website (71% lost, #1789) → 45,699 sitemap-attempted → ~8,400 with any crawlable URL (82% of reached sites lost) → 5,359 substantively enriched. **The LLM step is not the bottleneck — it converts 63%. Discovery is.**
- **Two structural leaks:** ~37% of orgs are off-BMF (auto-revoked filers and §4947 trusts are structurally invisible — #1551; the per-EIN escape hatch shipped, the systematic lane for ~16-18k actionable orgs did not), and 32,500 grantmaker sites have no sitemap.
- **Neon is running ~3.8x its target:** ~1,490 CU-h/mo (≈$190/mo est.) against Nathan's stated $50 target. The dominant waste is failed-run wall-clock — July's failed runs (1.33M s) exceeded successful ones (1.30M s). #1846.
- **Silent-rot precedent:** sitemap discovery was dead 2026-05-28 → 07-09 while enumeration masked it. The #1760 fix only covers lanes that produce a run-record; lanes without one still die silently.
- **Unit inconsistency:** `grants.amount` is whole dollars, `scholarships` are cents. A consumer joining the two without reading ABOUTMEs mis-scales by 100x.
- **Cross-repo contract:** shape changes are caught by CI on both sides (good — better than most two-repo shops). *Value-semantics* changes are honor-system — a unit change, enum re-meaning, or population collapse sails through both drift checks. #1679 and #1680 are the fixes and are open.

---

## Commercial readiness (C) — where the money leaks

**Built and sound:** 30-day no-card trial, hosted Stripe checkout, self-serve portal + cancellation with reason capture, webhook plan sync (churn cannot keep access; pay-but-no-access is closed by an optimistic write with the webhook authoritative), a first-run dashboard that solves the empty-state problem, and **time-to-first-value of roughly 5 minutes / 4-6 clicks to scored funder matches.** That activation path is genuinely competitive.

**Then the business breaks in four specific places:**

1. **No trial-expiry conversion path.** The drip is 3 emails ending at day 5. The trial ends at day 30. Nothing emails at T-7, T-1, or T-0. The only in-app countdown is buried on the billing page. **The one moment your entire revenue model depends on happens in silence.** A quiet user in week 2 hears nothing at all — the weekly digest composes from pipeline content a quiet user by definition doesn't have.

2. **The pricing page sells two things the code doesn't do.** "20 AI-assisted applications per month" (`templates/billing/pricing.html:34`) is enforced nowhere — it's actually unlimited. "Add 10 applications for $10, unused credits roll over" (`:88`) has no purchase button, no credit model, no granting webhook; `apps/billing/services.py:42-44` admits it's "a later PR." **A customer who bought a pack would pay $10 and receive a flash message.** That is a refund and a bad review, and it is live right now.

3. **`past_due` instantly downgrades to free** (`apps/billing/webhooks.py:305-309`). One failed card mid-Stripe-retry strips access before dunning could recover it, and there is no in-app dunning email. Recovery is entirely outsourced to Stripe's own retries — which may or may not be configured.

4. **Support and instrumentation are at zero-customer scale.** Four help articles; feedback routes to your inbox; no support address surfaced, no chat, no FAQ. Telemetry events *are* captured per-user and typed — but they land in JSONL on B2, not a queryable analytics store. You cannot today answer "where do people drop off" or "which feature predicts retention" without grepping logs. The dot-plot substrate is ~60% built; the product is 0%.

**Two bugs worth naming:** magic-link TTL is 300s in `apps/accounts/magic_link.py:11` (you ruled 10 minutes), and `magic_link.py:35` on main reads `except BadSignature, SignatureExpired:` — the Python-2 form that PR #542 already fixed and a later commit reintroduced. It works only because of subclassing.

---

## Ops & cost (C+)

**The scary one:** the **AG tenant database backup is not scheduled.** That DB holds every customer account, org, Stripe link, grant draft, and feedback verdict — the only genuinely irreplaceable data you own (the GS corpus is re-derivable at cost; this isn't). The last known restore point is **2026-06-09**.

*Verified correction:* the runbook blames a missing `B2_ENDPOINT_URL`, but that variable **is** set on production and staging — document uploads work fine. The real blocker is narrower and now clear: **there is no cron infrastructure to run `backup_database` on**, plus the pg17 client requirement in the cron container. See the cron-gap section above.

**Alerting dead-ends:**
- ~~AG's CRITICAL email channel is dead~~ — **fixed, AG #1337.** `settings.ADMINS` was never assigned in `config/`, so `apps/core/notifications.py:194` resolved no recipients and logged "no recipients configured; skipping send." Now built from `ADMIN_ALERT_EMAILS` with a non-empty default. Merge and it works.
- ~~**GS has no Sentry at all**~~ — **fixed, GS #1960.** Note the trap that PR exists to avoid: Dagster catches in-op exceptions and converts them to run failures, so `sentry_sdk.init` alone would report daemon boot crashes and stay silent on every asset failure. The PR ships a `run_failure_sensor` alongside the init; that sensor is the only path by which an asset failure leaves the cluster.
- GS's `send_alert` silently no-ops if `GRANTSPIDER_SMTP_HOST` is unset — and it defaults empty.
- Correction to standing memory: the GS daemon-watchdog *does* now self-heal a hung daemon (heartbeat >600s → Railway redeploy). But the watchdog itself is unmonitored, and circuit-breaker/queue-stall escalations only `log.error`.
- Neither repo sets a Railway `healthcheckPath`. A wedged AG web process is caught only by UptimeRobot on `/healthz` — which is your sole 2am pager.

**Rollback does not exist as a documented or exercised procedure.** Roll-forward hotfix only, in both repos.

**Cost shape is genuinely favorable.** Almost everything is flat with customer count: Neon, Railway (~10 services), Cloudflare, GS enrichment, Brave. Only Stripe fees (~3% of MRR), Resend (every magic-link login is an email), Studio LLM calls, and B2 doc storage scale per customer. **At 1,000 customers the flat floor is unchanged and the variable lines stay small — except Studio LLM, which has no per-tenant cap.** That is the same finding as architecture risk #2, arriving from the cost side.

**Toil inventory** (what a solo operator must do or the business decays): weekly promote + back-merge ×2 repos, merging GS pin-bump PRs on AG, ad-hoc tenant backups, in-session enrich drains (which halt on laptop sleep with no notification), Dagster schedule toggles in the UI, monthly DDG 990-PF re-drain, `needs-input` answers. Given your own stated law that recurring manual tasks are designed to fail, **the promote ritual and the backup cron are the two to automate first.**

---

# PART II — THE PATH TO 1,000 CLIENTS

## The market, honestly

**Your ICP is enormous and underserved.** ~88% of US nonprofits spend under $500,000/year; 59% run on budgets under $50,000. In organizations that size, grant writing "falls to whoever has a moment free, usually the executive director wearing their fifteenth hat." That is precisely the person your mission targets and precisely the person the incumbents price out.

**The incumbents are priced for someone else:**

| Product | Price | Notes |
|---|---|---|
| Instrumentl | $179–$999/mo | The category leader. Explicitly not worth it under ~10 serious applications/year. |
| Candid (Foundation Directory) | $100–$219/mo | **Cut from $299 → $100/mo in Jan 2026** when Candid Search merged GuideStar + FDO |
| GrantStation | $199/yr (promo) – $699/yr | Cheap, but a static directory |
| GrantCopilot and similar AI entrants | ~$24/mo | Your actual competitive set |
| **AI Grant Helper** | **$20 / $50 mo** | Priced below everyone |

Two things follow. First, **you are not competing with Instrumentl — you are competing with a spreadsheet and Google.** Your real competitor is inertia. Second, **a wave of $24/mo AI grant tools is arriving**, and the search results for every commercial keyword in this niche are already dominated by their content marketing (grantsights, grantprobe, grantbite, fundrobin, grantcopilot all rank). The land grab is happening now.

## The arithmetic of 1,000 clients

At $20/mo, 1,000 clients = **$20,000 MRR / $240,000 ARR**, minus ~3% Stripe. Against a flat infrastructure floor, that is a genuinely excellent one-person business.

Working backwards, using published benchmarks (opt-in no-card trials convert at 8–22%, median 14%; visitor→trial for high-intent niche B2B runs 2–4%):

| Step | Assumption | Cumulative requirement |
|---|---|---|
| 1,000 *active* subscribers at ~3%/mo churn | — | ~1,500–1,800 gross paid signups over 36 months |
| Trial → paid at 12% | activation-dependent | ~12,500–15,000 trial starts |
| Visitor → trial at 3% | high-intent traffic | **~450,000 cumulative visits** |

Ramping to that over 36 months means roughly **30,000–40,000 organic sessions/month by year three.** Across 142,737 pages that is only ~0.25 visits per page per month — entirely achievable **if the pages are indexed.** Today 282 are.

**So the whole business reduces to one number: indexed pages. And indexed pages reduce to enrichment coverage. Which is why GS #1929 is the growth ticket.**

One more benchmark that should shape everything: **activated trials convert at 35–65%; un-activated trials convert at 2–8%. Activation quality explains 60–75% of trial-to-paid variance.** Your activation path is already good. Your *post*-activation silence is what's killing conversion.

## Pricing — one strategic disagreement

I think **$50/mo for the Consultant tier is a mistake**, and I want to be clear this is not a challenge to the mission.

Your mission is A+ tools for the servants of the poor on shoestring budgets. Grant *consultants* are not that. They are professionals billing $75–150/hour who manage portfolios of client orgs, and $50/mo for unlimited organizations is roughly a third of one billable hour. They will not perceive it as valuable, and — more importantly — **consultants are simultaneously your highest-willingness-to-pay segment and your best distribution channel.** One consultant who adopts you brings 5–15 nonprofits with them and teaches them the tool for free.

My recommendation:
- **Keep Pro at $20** (or lower, or add a genuinely free tier). This is the mission. Subsidize it deliberately and say so out loud — "small nonprofits pay $20 because consultants pay $149" is a *story*, not an apology, and it will earn you goodwill in exactly the communities you need.
- **Raise Consultant to $99–$149/mo** with per-client reporting and white-label exports. Grandfather anyone who signed at $50, forever, and tell them you're doing it.
- **Delete the application-pack SKU and the "20/month" claim** until they exist. Shipping a pricing page that lies is worse than shipping a simpler one.

At a blended mix, 1,000 clients could be $30–40k MRR rather than $20k — which buys the time and tooling to serve them.

## What you need to learn

Ranked by expected return, not by interest. You are a fundraiser and a writer; several of these are closer to skills you already have than they look.

1. **Lifecycle email and activation design.** The highest-ROI skill available to you, by a wide margin. You need to internalize the trial-conversion sequence as a craft: what T-7 says versus T-1, why a win-back at T+3 works, how to write a behavioral trigger rather than a calendar one. *Read: Wes Bush, "Product-Led Growth"; Kathy Sierra, "Badass: Making Users Awesome."*
2. **Technical SEO at scale — specifically crawl budget and thin-content diagnosis.** Not keyword research. You need to understand why Google discovers 109k URLs and indexes 282, how internal-link depth governs crawl allocation, and what makes a programmatic page pass the quality threshold. This is the skill that unlocks your entire acquisition model.
3. **Positioning.** Your headline — "We don't replace grant writers. We make them unstoppable." — is genuinely excellent and rare. But your *category* is ambiguous: are you a funder database, a matching engine, or a writing tool? Ambiguity is the enemy of both search intent and word of mouth. *Read: April Dunford, "Obviously Awesome."*
4. **Funnel and cohort analytics.** Enough to define one activation event, watch a weekly cohort chart, and stop guessing. A weekend of learning, permanently useful.
5. **Customer conversations.** You have zero customers and 14 years of domain intuition, which is a dangerous combination — you will be tempted to build from memory. *Read: Rob Fitzpatrick, "The Mom Test."* Ten real conversations will beat any amount of my analysis.
6. **Support operations and deflection.** Later, but before 200 customers. The skill is writing docs that stop tickets from existing.

## Tools to incorporate

Deliberately cheap. Everything here is free or near-free at your scale.

| Need | Tool | Cost | Why this one |
|---|---|---|---|
| Product analytics, funnels, retention, session replay | **PostHog** (free tier: 1M events/mo) | $0 | Fills your single biggest instrumentation gap. Your telemetry already emits typed per-user events — this gives them a query surface. Session replay alone will teach you more about drop-off than a month of analysis. |
| Lifecycle email | **Resend** (already have) + Django sequences | ~$0 | You already have the substrate in `onboarding_sequence.py`. Do *not* buy Customer.io yet. Extend what exists. |
| Dunning / failed payments | **Stripe Smart Retries + Stripe dunning emails** | $0 | A settings toggle in the Stripe dashboard. Closes an entire funnel leak for free. |
| Search visibility | **Google Search Console + Bing Webmaster + IndexNow** (built) + **Ahrefs Webmaster Tools** (free for verified sites) | $0 | AWT gives you backlink and keyword data free because you own the domain. |
| Support | **support@** + a real FAQ + in-app doc search | $0 | Skip live chat until ~200 customers. Then reassess — Crisp free tier or Chatwoot self-hosted. |
| Onboarding tour | **driver.js** (already your decision) | $0 | MIT-licensed. Shepherd/intro.js are AGPL — stay away. |
| Testimonials / social proof | A form + a public wall page | $0 | You need *any* third-party voice. Right now the only proof on the landing page is your own bio. |
| Error monitoring on GS | **Sentry** (free tier) | $0 | GS currently has none. |
| Uptime | UptimeRobot (have it) | $0 | Add a check for the GS Dagster webserver. |

**Total added monthly cost: approximately zero.** Nothing in your path to 1,000 clients requires spending money you don't have. It requires sequencing.

## The gaps, in the order I'd close them

### Tier 0 — Build the scheduler, then stop the bleeding (2–3 weeks, mostly config)

**0. Stand up AG cron infrastructure.** Nothing else in this tier or the next
works without it. Either one Railway cron service per command group, or a
single daily runner invoking them in sequence. Wire, in order:
`backup_database` (your last restore point is seven weeks old),
`send_onboarding_emails`, `send_deadline_reminders` (you are currently
advertising a feature that has never fired), `submit_seo_urls`,
`monitor_indexation`, and the telemetry archive pair plus
`TELEMETRY_B2_BUCKET_NAME`. Also correct `render_sitemaps` to `0 */6 * * *`.

A day or two of Railway configuration unblocks the drip, the deadline feature,
the SEO engine, your backups, and your analytics **simultaneously**. It is by a
wide margin the highest-leverage work available.

Then:

1. ~~`B2_ENDPOINT_URL`~~ — verified set; uploads work. **Update the stale runbook** so the next reader isn't misled.
2. Merge **AG #1337** (ADMINS) and **GS #1960** (Sentry + run-failure sensor). Both are open, verified, and targeting `staging`.
3. Set `GRANTSPIDER_SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD`. `SMTP_PORT` is already set and the host is not — a half-configured state that silences the hourly DB canary, the monthly restore-drill result, and the `send_alert` half of the new failure sensor.
4. **Delete the application-pack SKU and the "20 applications/month" claim from the pricing page.** Today. It is a live false promise.
5. Enable Stripe Smart Retries; stop downgrading on `past_due` (wait for `unpaid`/`deleted`).
6. Add a per-org monthly LLM budget ceiling.
7. Fix the magic-link TTL (300s → 600s) and the reintroduced Python-2 `except` clause. (GS has a pre-commit hook rejecting exactly that syntax; AG does not — worth porting.)
8. Add a `healthcheckPath` to both repos' Railway config. Neither has one, so a wedged-not-crashed process never self-heals.

### Tier 1 — Make the funnel work and make it visible (4–6 weeks)
9. **Trial-expiry sequence: T-7, T-1, T-0, T+3 win-back, plus a persistent in-app countdown banner.** Single highest-revenue *feature* change — but it is dead code until Tier 0 item 0 exists. Sequence it after the scheduler, not before.
10. Extend the drip from day 5 to day 30 with behavior-triggered emails (viewed matches but saved none; saved funders but started no application).
11. Install PostHog. Define exactly one activation event — I'd propose *"saved a funder from a match result"* — and build one funnel: visit → signup → wizard complete → matches viewed → funder saved → trial converted. **Note:** existing telemetry is wiped on every deploy (ephemeral filesystem, no archive cron), so you are starting behavioural history from zero regardless. Fix the archive cron in Tier 0 or accept that gap knowingly.
12. Structural tenancy (RLS or org-scoped managers) before you have real customer data at volume.

### Tier 2 — Turn on acquisition (3–9 months, the long pole)
13. **GS #1929 homepage-fallback across the 32,500 sitemap-less grantmakers.** ~4x sellable coverage. This is the growth ticket.
14. **GS #1789** Brave drain for the 111,674 websiteless grantmakers.
15. Then execute the existing SEO Sprint 2 plan — it is well-designed and mostly unstarted. **Note: its own hold-gate ("hold all forced-discovery levers until at least 2026-07-23") expired six days ago.** Open it. Also reconcile the doc with live `robots.txt`: the plan claims you allow GPTBot/ClaudeBot/Google-Extended, but the live file blocks them after the 2026-06-01 origin-saturation incident. Blocking training crawlers is your stated policy and correct — but `Google-Extended` also gates Gemini's grounding, and `Crawl-delay: 10` in the wildcard block deserves a second look.
16. **Recruit 15–20 design partners.** Free forever, in exchange for real feedback, a testimonial, and permission for a case study. You have the relationships from 14 years in the sector. This closes the social-proof gap, gives you the customer conversations you need, and costs nothing but attention.
17. **Founder-led content.** You are a writer with a Substack and $15M raised. Long-form, specific, generous writing about grant strategy is a channel the $24/mo AI tools cannot copy, because they don't have a person behind them. This is your genuine unfair advantage and it is currently unused.

### Tier 3 — Scale the motion (9–24 months)
18. **The consultant channel.** Re-price it, then go get it. Every consultant is a distribution node. GPA (2,500+ members, chapters, annual GrantSummit), regional associations like Puget Sound Grantwriters, the large grant-writing Facebook groups, and the established newsletters are where these people already are. Show up as a practitioner, not a vendor.
19. Partnerships: state nonprofit associations, community foundations, and TechSoup listing (they verify nonprofit status for you — that's real distribution).
20. Support deflection: expand help from 4 articles to ~30, driven by actual ticket themes.
21. Referral mechanics, once you have people who like you.

## The honest risks

- **Time.** This is a 24–36 month plan at a sustainable pace. You said a long horizon is fine; I'm holding you to that, because the failure mode here is not slowness — it's a burst of marketing energy in month 2 against an unindexed site, followed by discouragement.
- **The AI-grant-tool land grab.** Competitors are publishing content at volume *now*. Your durable moat is not the AI — it's the corpus plus your practitioner credibility. Lean on both.
- **Candid's price cut** ($299 → $100/mo) compressed the market from above while $24/mo tools compress from below. Your $20 tier is defensible; your $50 consultant tier is stranded in the middle.
- **The 2.7% enrichment coverage is a product-quality risk, not just SEO.** If a user searches for a funder they know and your page is thin, you lose them permanently. Match quality rides on the same data.
- **You are the single point of failure** — for credentials, for support, for promotes, for enrich-drains that halt when your laptop sleeps. Tier 0 and the promote script are what make that survivable.

## What I'd do first, if you only did one thing

**Stand up AG's cron infrastructure.** My original answer here was "ship the
trial-expiry email sequence" — that was wrong, and the live check is what
corrected it. There is nothing in production that can send a scheduled email,
so the sequence would have been dead code the day it merged.

One or two days of Railway configuration simultaneously restores: the
onboarding drip, deadline reminders (a feature you are currently advertising),
the IndexNow/GSC engine that your entire acquisition model depends on, offsite
backups of the only irreplaceable data you own, and the telemetry substrate
every later analytics recommendation assumes.

Then ship the trial-expiry sequence onto it. Then fund GS #1929 like the growth
investment it is.

---

## Shipped during this review

| PR | What |
|---|---|
| [AG #1337](https://github.com/NathanKrupa/aigranthelper/pull/1337) | `ADMINS` populated so CRITICAL alerts have recipients; `test_notifications.py` 9 → 2 gaudi findings |
| [GS #1960](https://github.com/NathanKrupa/grantspider/pull/1960) | Sentry error reporting + Dagster run-failure sensor (your `SENTRY_DSN` was inert until this) |

Both open against `staging`, `make verify` green, suites at 4,019/0 (AG) and
6,945/0 (GS).

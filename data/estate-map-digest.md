<!-- Generated from estate-map.yaml by `scripts/estate_map.py render --write`. Do not edit by hand: a test compares this file with a fresh render. -->

# Estate map — digest

**North star.** Provide A+ grant-writing tools to the servants of the poor: the food pantries, parishes and small charities who work on shoestring budgets and are not grant experts. It is not about the money; it is about the people.

**Products.** `ag` (aigranthelper) serves grant seekers at small nonprofits, the users of aigranthelper.com; `gs` (grantspider) serves AI Grant Helper, as the producer of its funder and grant research; `wp` (wphelper) serves Nathan's WordPress clients, and the estate as its external-connector library; `aa` (ai-assistants) serves The Almoner's content authoring, CRM and WordPress work; `os` (oversteward) serves Nathan and every estate session, as the control plane; `gaudi` (gaudi) serves every gated estate repo as its architecture linter, and the public as open source; `fiscus` (fiscus) serves the estate's own learning: observation, reviews and kaizen; `exchequer` (exchequer) serves Nathan's books: billing pulls, ledgers and the monthly close

## Capabilities (`id` · status · purpose)

- `ag.research` · live · Research reads: the read-only mirror of GS's research schema and the plumbing every research read goes through.
- `ag.funder-search` · live · Funder search and match scoring: keyword, semantic and hybrid search, Typesense with a Postgres fallback, and funding-fit scoring.
- `ag.funder-pages` · live · Funder pages: foundation and federal-grant profiles, the search pages, and state, sector and city hubs.
- `ag.search-indexing` · live · What Google may index and how it learns of it: sitemaps, the indexability tier, IndexNow, URL Inspection sweeps and the indexation experiments.
- `ag.edge` · live · The Cloudflare edge: Cache-Control headers and cache rules, purges, the warmer, the origin lock and the Web Bot Auth key directory.
- `ag.landing-pages` · live · Conversion pages: the CMS-edited home page, its try-it widget and walkthrough recorder, and the /grants-for/ lead pages.
- `ag.home-ab-testing` · live · A/B testing on the home page, the estate's experiment surface: hashed arms at the edge, GA4 reads, a per-arm report.
- `ag.pipeline` · live · The grant pipeline: programs, saved funders, contacts, applications, awards and deadlines, and the dashboard over them.
- `ag.reporting` · live · Post-award compliance: reporting requirements, deadlines and reminders, iCal export, and the weekly org digest.
- `ag.matchmaker` · live · Match quality measurement: impression and interaction telemetry, self-reports, golden labels and offline evals.
- `ag.studio` · live · Grant Studio: AI-assisted drafting with versioned drafts in B2, question workshops and QA checks; Anthropic, Gemini, OpenAI via one module.
- `ag.accounts` · live · Accounts: multi-tenant organizations, consultants, magic-link sign-in, onboarding and account deletion.
- `ag.billing` · live · Billing: Stripe via dj-stripe, plans and plan switches, passes, gifts and trials, renewal and beta notices.
- `ag.platform` · live · Request plumbing every app shares: tenancy middleware, role and lapsed-access enforcement, internal auth, abuse guards, storage.
- `ag.notifications` · live · Notifications and mail: routed notification channels, the staging allowlist, and the mail outbox with its drain.
- `ag.ops` · live · Operator surface: the ops dashboard and experiment tracker, `/internal/ops/` reports and verdicts, the load test, DB backup and scratch.
- `ag.acquisition-analytics` · live · Acquisition measurement: GA4 server-side events, first-touch attribution, the signups-from-funder-pages KPI, the GEO probe.
- `ag.feedback` · live · Feedback: in-app bug reports, visitor data corrections exported to GS, and captured email leads.
- `ag.telemetry` · live · Telemetry: one emit() for page, auth and billing events, the pipeline-history JSONL, its B2 archive, and the JWT pull Fiscus reads.
- `ag.worldmodel` · live · Customer world model: belief-shaped state, goals and context assembled on demand, over an append-only event spine.
- `ag.help-centre` · live · The help centre: DB-backed articles written as PR-gated drafts by the docs-author agent, with captured screenshots and drift checks.
- `ag.dev-gates` · live · AG's gates and release tooling: make verify, test settings, CI ratchet counters, the promotion check, the GS pin bump.
- `ag.search-acquisition` · live · Google Search as AG's first customer: the indexable funder-page corpus, offered by sitemap and judged by Search Console.
- `ag.search-measurement` · live · Judging shipped pages by Search Console and GA4 through the CLIs: indexation sweeps, per-arm reads, funnel events.
- `ag.page-red-teaming` · building · Gemini red-teams a page shape before it is built, on static design-bench renders judged under the rater and seeker rubrics.
- `ag.resource-outreach` · live · Resource-page outreach: monthly Brave discovery of grant-resource sites, reviewed drafts, and weekday listing-request emails.
- `gs.irs-ingestion` · live · IRS ingestion: 990-PF Part XV and Schedule I grants (TEOS bulk), BMF monthly sync, SOI annual extract.
- `gs.facsimiles` · live · 990-PF facsimiles: IRS XSL → PDF → B2.
- `gs.other-sources` · live · Other sources: 360Giving; federal opportunities (Grants.gov, SAM, USAspending, agency hydration); community, corporate and diocesan foundation discovery.
- `gs.website-resolution` · live · Websites: Discovery (IRS, Wikidata, Brave, DDG, crt.sh providers) + Anthropic verification judge.
- `gs.crawl` · live · Crawl: Railway sitemap/crawlee crawler; laptop crawler with a local SQLite resume ledger; Common Crawl + Wayback; URL-heuristic page classification (no LLM).
- `gs.enrichment` · live · Enrichment: SKIP LOCKED claim queue drained by in-session Sonnet workers (`.claude/workflows/enrich-drain.*`); metered Anthropic key fail-closed; token-free funding profiles.
- `gs.embeddings-search` · live · Embeddings / search index: Local all-MiniLM-L6-v2 (384-d), source-hash staleness; GS owns the Typesense indexing.
- `gs.data-quality` · live · Data quality: Stage-health ledger (`dq health`), freshness SLAs, canaries, Sentry run-failure sensor, Neon consumption canary.
- `gs.safety` · live · Safety: Operator-armed prod migrations (`db migrate-prod arm|run|cleanup`), pre-migration backup, weekly backups of research + Dagster + AG tenant DBs, monthly restore drill.
- `wp.connectors` · live · WordPress client toolkit; canonical home for external connectors (WP REST, Kit, GA4, GSC, FTP, IndexNow).
- `wp.nathankrupa-hub` · planned · nathankrupa.com as a hub for all of Nathan's work: the Substack, The Almoner, the AG community and Golden Harvest.
- `aa.almoner` · live · `almoner` package — content authoring, CRM, ingestion, WP integration. No CI.
- `gaudi.linter` · live · Architecture linter, open source (PyPI `gaudi-linter`); gates AG and OverSteward.
- `fiscus.kaizen-platform` · live · Observation-and-kaizen platform: subject contracts, weekly/monthly reviews, lessons corpus.
- `exchequer.counting-house` · live · Private counting-house — `exchequer pull` billing connectors, CSV ledgers, monthly close; zero LLM tokens.
- `os.registry` · live · The manifest of managed contexts, and the read-only gather and diff behind /sync-status.
- `os.dev-family-sow` · live · Canonical worktree/guard/env scripts and hooks, deployed to repos by sow; nightly `sync_repos` timer.
- `os.session-sweeps` · live · The session-start sweeps: Sentry triage, Railway liveness, AG ops triage, GS stage health, and the operator-steps channel to Todoist.
- `os.backup` · live · The laptop backups: a readiness-gated monthly WSL export, a daily restic backup of /home/natha, and the backup health sweep.
- `os.telegraph` · live · Membrane over the GitHub-issue bus (Epic Conductor + cross-repo issue filer); transport is Happy.
- `os.vintner` · live · `/pipeline-status` GS→AG funnel; reads one read-only DSN (`VINTNER_RESEARCH_DATABASE_URL`, GS Neon).
- `os.dream-kaizen` · live · Transcript → memory consolidation (systemd timer); kaizen queue from Fiscus lesson clusters + `kaizen` issues, plus the skill miner and trajectory-tag lint.
- `os.review-loop` · live · Assembled-input adversarial reviewer with a `.review-rounds` ledger; CI `reviewer-verdict` gate.
- `os.memory-deploy` · live · steward-memory → `~/.claude/projects/*/memory/`.
- `os.dispatch` · live · Issue intake and in-session pickup: the dispatch playbook, the architect card, the tribe-first queue, /project-status and the abandoned-work sweep.
- `os.estate-reports` · live · Nathan's views of the estate: the nightly Estate Brief vault note and the Estate Board.
- `os.page-judging` · live · Seeing estate pages as a visitor and a rater would: the signed probe through Cloudflare, the Gemini quality-rater pass, and the design bench.
- `os.railway-cron` · live · Provisions a Railway cron service cloned from a sibling service's config, plus its own variables.
- `os.janitor` · live · Reclaims disk that sessions leave behind once nothing is using it.
- `os.estate-map` · building · This map: what the estate builds, where each capability lives, and its current and target shape; checked by the seventh session-start sweep.

Claims, current and target shape, seams (S-1..S-14), invariants (I-1..I-22) and liabilities live in `estate-map.yaml`. Read it at scope time; `scripts/estate_map.py check` is the seventh session-start sweep.

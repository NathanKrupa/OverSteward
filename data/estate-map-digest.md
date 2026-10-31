<!-- Generated from estate-map.yaml by `scripts/estate_map.py render --write`. Do not edit by hand: a test compares this file with a fresh render. -->

# Estate map — digest

**North star.** Provide A+ grant-writing tools to the servants of the poor: the food pantries, parishes and small charities who work on shoestring budgets and are not grant experts. It is not about the money; it is about the people.

**Products.** `ag` (aigranthelper) serves grant seekers at small nonprofits, the users of aigranthelper.com; `gs` (grantspider) serves AI Grant Helper, as the producer of its funder and grant research; `wp` (wphelper) serves Nathan's WordPress clients, and the estate as its external-connector library; `aa` (ai-assistants) serves The Almoner's content authoring, CRM and WordPress work; `os` (oversteward) serves Nathan and every estate session, as the control plane; `gaudi` (gaudi) serves every gated estate repo as its architecture linter, and the public as open source; `fiscus` (fiscus) serves the estate's own learning: observation, reviews and kaizen; `exchequer` (exchequer) serves Nathan's books: billing pulls, ledgers and the monthly close

## Capabilities (`id` · status · purpose)

- `ag.research` · live · Research: Read-only GS mirror (`models/_generated.py`, `_views.py`); match scoring; keyword/semantic/hybrid search; Typesense with fail-open Postgres fallback; public foundation/sector/city pages.
- `ag.pipeline` · live · Pipeline / reporting: Grant lifecycle (Program, FunderRelationship, Application, Award, FunderMilestone, UserFunderSignal, SavedGrantor) and post-award compliance.
- `ag.matchmaker` · live · Matchmaker: Match telemetry, golden-label evals, the `pipeline_history-YYYY-MM-DD.jsonl` writer.
- `ag.studio` · live · Studio: AI-assisted grant drafting (versioned drafts in B2); Anthropic, Gemini, OpenAI via one module.
- `ag.accounts-billing` · live · Accounts / billing: Multi-tenant orgs + consultants, magic-link auth; Stripe via dj-stripe 2.11.
- `ag.seo-edge` · live · SEO / edge: IndexNow, GSC indexation monitor, Cloudflare cache rules + purge + warmer, lead pages; home-page A/B Worker.
- `ag.ops-feedback` · live · Ops / feedback / telemetry: `/internal/ops/` reports + verdicts, visitor DataCorrection, EmailLead, Fiscus telemetry endpoint.
- `ag.docs-bot-worldmodel` · live · Docs / bot / worldmodel: DB-backed help centre; Web Bot Auth key directory; customer world model (beliefs, goals, event spine).
- `ag.dev-gates` · live · AG's local gates and test settings: make verify, pytest configuration and the test database.
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

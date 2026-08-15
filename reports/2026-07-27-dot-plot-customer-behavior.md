# Dot Plots for Customer Behavior — Research Findings

ABOUTME: Deep-research findings on per-user dot plot behavior tracking for AI Grant Helper.
ABOUTME: Covers the technique (Lieb/YC), instrumentation options, AG's existing telemetry, and a build recommendation.

_Date: 2026-07-27. Research: 3 web agents (technique / instrumentation / implementation) + 1 codebase survey of aigranthelper, synthesized. Status: findings only — nothing filed, nothing built._

## TL;DR

- **The technique is real and freshly canonical.** "Dot plot" here = David Lieb's (YC partner, ex-Google Photos) chart: one row per user sorted by signup date, one column per day, a dot when that user performed a **value event** that day. He published a YC podcast on it 2026-07-09 — "until you have hundreds of users, the dot plot could be your only dashboard." Granola's engineering blog independently documents building one. It is exactly the right instrument for AG's stage (near-zero users, need to watch each one).
- **No vendor sells this chart.** Amplitude/Mixpanel/PostHog give per-user *feeds* and aggregate *retention tables*, not the cross-user dot grid. Everyone who has one built it themselves from their own event log. So the question reduces to: where does AG's event log live, and what renders it?
- **AG is not greenfield — it's two-thirds built.** `apps/telemetry` is a live, PII-hardened first-party pipeline (page views, auth, billing, errors already flowing; matchmaker richly instrumented). The gap is precise: the `feature_invoke/complete/abandon` emitters exist, are tested, and have **zero production call sites**. Separately, `worldmodel.Event` (append-only Postgres spine with a 12-kind vocabulary) has a sanctioned `record_event` write-path with **zero production callers** (verified by grep 2026-07-27). Two spines designed, neither fed.
- **Recommendation: no new vendor, no new model.** Instrument ~15 feature spans at view boundaries, feed the Postgres spine, and render two Plotly views in the existing staff-only ops console. GA4 stays as top-of-funnel marketing telemetry; it cannot do this job.

## 1. The technique

**Canonical form (Lieb / Granola):**
- Rows = individual users, sorted by signup date (newest at bottom → the triangle shape shows cohort behavior at a glance).
- Columns = calendar days.
- Dot in a cell = the user performed a chosen **value event** that day. Optional: ring = signup/onboarding day; color or letter = which event type; row label = plan/segment.
- The whole point: DAU/MAU and retention curves are "actively misleading" pre-traction — they trend up from new-user inflow while every existing user silently churns. The dot plot shows *who* gets value, *how often*, and *when they stop* — patterns you eyeball, not pre-specify. (Levchin/PayPal fraud-grid lineage.)

**The one rule that matters:** dots must be **value events** — "listened to a song," "shared a photo" — never "logged in" or "viewed page." Logins measure showing up; value events measure receiving value. This is the single biggest design decision, ahead of any tooling choice.

**Variants and what each is for:**

| Variant | Shape | Use |
|---|---|---|
| **User × day dot grid** (the Lieb chart) | rows=users, cols=days, dot=value event | THE early-stage view. Build this. |
| **Per-user event strip** ("spike raster") | x=time, one row per user, dot per event colored by type | Drill-down: what did *this* user actually do Tuesday? Build this too. |
| Retention cohort table | rows=cohorts, cells=% retained | Aggregate successor; matters at hundreds of users. Later. |
| GitHub punch card (DoW × hour) | bubbles by count | Rhythm analysis. Skip. |
| Calendar heatmap (contribution graph) | one user's year | Habit view. Skip for now. |

**Scaling ceiling:** eyeballing raw rows works to a few hundred users; past that, Lieb samples cohorts ("iOS users in France") and Granola rolls up team-level grids that expand on click. At AG's scale this is years of runway — the chart fits the stage precisely.

## 2. Why GA4 can't do this

- The GA4 UI is aggregate-only: no raw per-user event export, Explorations sample past 10M events, **data thresholding actively suppresses small-cardinality views** — which at AG's traffic means *every* interesting per-user view gets suppressed.
- User-level lookback caps at 14 months (default 2).
- The only raw path is BigQuery export + User-ID wiring + hand-written SQL — i.e., building the same query/viz layer anyway, with an extra vendor hop, versus querying the Neon Postgres AG already pays for.
- Verdict: GA4 keeps its current job (acquisition/pageviews). It is not the behavior substrate.

## 3. What AG already has (codebase survey, 2026-07-27)

**Live and flowing:**
- `apps/telemetry` — typed Pydantic envelope, closed vocabulary (`page_view`, `feature_invoke/complete/abandon`, `auth_event`, `billing_event`, `error_seen`, `user_feedback`); salted-hash user IDs, PII-scrubbed payloads; JSONL sink with rotation, retention, B2 archival; Fiscus pull endpoint. `PageViewMiddleware` emits on every user-facing GET; allauth + dj-stripe signals cover auth and billing.
- Matchmaker instrumentation (most mature surface): `MatchRun`/`MatchStep`/`MatchImpression`/`MatchInteraction`/`MatchFeedback`/`ProfileFieldEvent`.
- GA4 both halves (gtag + Measurement Protocol with `_ga` stitching), consent-gated.
- Staff ops console (`apps/ops`) with Chart.js dashboards — the natural home for the dot plot pages.

**Built but unfed (the actual gap):**
- `emit_feature_invoke/complete/abandon` (`apps/telemetry/services.py:222-251`) — zero production call sites; only the definitions and unit tests exist.
- `worldmodel.Event` + `record_event` (`apps/worldmodel/events.py`) — append-only, org-scoped, dual timestamps, provenance, `schema_version`, 12-kind vocabulary (`match_surfaced`, `funder_saved`, `application_submitted`, `draft_generated`, `search_performed`, …) — zero production callers; ingestion was designed to arrive via worldmodel-side signal receivers "as consumers appear." **The dot plot is the first consumer appearing.**

**Absent:** any third-party product-analytics SDK (good — nothing to rip out); `last_seen` on User; any retention/cohort view; the taxonomy doc (`docs/MATCHMAKER_INSTRUMENTATION.md` is cited in a docstring but doesn't exist).

**Substrate note:** the telemetry JSONL is the wrong plotting substrate (file-based, rotated, salted-hash IDs — built for Fiscus export and PII safety). `worldmodel.Event` is the right one: it's Postgres (SQL straight into Plotly), append-only by contract, and its Kind list should be the naming source of truth for any new events rather than inventing a parallel taxonomy.

## 4. Tooling verdict

| Option | Verdict |
|---|---|
| **First-party events in existing Neon Postgres** | **Winner.** $0, zero export friction, no consent burden (server-side, no cookies), `request.user` already resolved so no identity stitching. AG already owns the schema (`worldmodel.Event`). |
| PostHog Cloud (1M events/mo free) | Fine product, wrong fit: raw data comes back out via HogQL/batch-export, `identify()` wants a cookie consent posture, and the chart still has to be hand-built. Self-hosting is officially "hobbyist" now. |
| Umami / Plausible / OpenPanel | Privacy-friendly web analytics, but per-user timelines are either absent (Plausible rotates visitor hashes daily *by design*) or thin. Wrong tool class. |
| Mixpanel / Amplitude free tiers | Generous volume, heavier vendor commitment, still no dot-grid chart. Their per-user feeds duplicate what a strip plot over own data gives. |
| Metabase / Grafana on Railway | Metabase's scatter can't put a categorical (user) on the y-axis (open issue #11254); Grafana ~$67+/mo and time-series-shaped. Skip BI tools entirely. |

Server-side vs client-side: for a logged-in B2B SaaS the actions that matter (ran matchmaker, generated draft, exported) are all server-visible; client-side JS loses 25–40% to blockers and adds a consent surface. Server-side from view boundaries is the correct default. GA4 client-side stays for anonymous top-of-funnel.

## 5. Recommended build (two small phases)

**Phase A — feed the spine (the prerequisite).** One `track()`-style seam at ~15 view boundaries emitting the existing telemetry feature spans, with worldmodel signal receivers recording the durable Postgres event (the fan-out design worldmodel's README already anticipates). Candidate feature IDs from the URL survey: `onboarding`, `program_profile_edit`, `matchmaker_run`, `match_triage`, `funder_search`, `funder_detail_view`, `application_create`, `application_advance`, `application_submit`, `studio_draft_create`, `studio_generate`, `studio_qa`, `draft_export`, `deadline_manage`, `billing_checkout`. Write the missing taxonomy doc; add `last_seen` to User while in there.

**The five value events** (dot-grid worthy, per the Lieb rule — the rest are drill-down color):
1. `matchmaker_run` — the core value moment
2. `match_triage` (save/hide/feedback) — engagement with results
3. `studio_generate` — the AI-cost-bearing action
4. `draft_export` — "got value out the door"
5. `application_advance`/`submit` — the retention + outcome signal

**Phase B — two staff-only pages in the ops console** (Django view + Plotly `fig.to_html`, ~no new deps):
1. **Dot grid:** users (rows, sorted by signup) × days (cols), dot colored by highest-value event that day, intensity by count, signup-day ring. SQL is a `GROUP BY user, day` + `generate_series` left-join for the dense calendar; pandas pivots it.
2. **Event strip:** `px.scatter(x=occurred_at, y=user, color=kind, hover_data=payload)` — the per-user raster with hover detail. (matplotlib `eventplot` — the neuroscience spike-raster primitive — is the static fallback if we ever want PNG email snapshots.)

Render on-demand only (a staff page hit), never cron-refreshed — keeps Neon autosuspend-compatible and the $50/mo budget untouched. No partitioning, no sessionization, no BRIN heroics at this scale; a `(organization, occurred_at)` index (which the model likely already has) suffices. Sessionization-in-SQL (LAG + gap + running sum) is documented and shelved for when session metrics matter.

**What NOT to do:** adopt PostHog/Mixpanel, stand up Metabase/Grafana, partition the events table, build retention cohort tables yet, or dot "logged in" events.

## 6. Sources (strongest)

- Lieb / YC podcast "Dot Plots: How to Actually See What Your Users Are Doing" (2026-07-09) — summaries: https://finance.biggo.com/podcast/3960385a4a513458 , https://www.startuphub.ai/ai-news/artificial-intelligence/2026/david-lieb-on-understanding-user-behavior-with-dot-plots
- Granola, "Start with a dot-plot": https://www.granola.ai/blog/dot-plot
- Segment Track/Identify spec: https://segment.com/docs/connections/spec/ ; Amplitude taxonomy playbook: https://amplitude.com/docs/data/data-planning-playbook
- PostHog self-host disclaimer: https://posthog.com/docs/self-host/open-source/disclaimer ; pricing: https://posthog.com/pricing
- matplotlib eventplot: https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.eventplot.html ; Plotly scatter: https://plotly.com/python/line-and-scatter/
- Sessionization in SQL: https://randyzwitch.com/sessionizing-log-data-sql/ , https://ryanguill.com/postgresql/sql/2024/06/24/aggregating-event-data-into-sessions.html
- Metabase categorical-y-axis limitation: https://github.com/metabase/metabase/issues/11254
- Event-sequence vis survey (TVCG 2021): https://vaclab.unc.edu/publication/tvcg_2021_guo_b/tvcg_2021_guo_b.pdf
- GA4 limits: https://www.owox.com/blog/articles/data-sampling-in-ga4 ; BigQuery export: https://www.digitalapplied.com/blog/ga4-bigquery-export-2026-marketing-analytics-reference

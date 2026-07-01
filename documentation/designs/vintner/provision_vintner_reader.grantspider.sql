-- ABOUTME: Provisions the vintner_reader role + vintner aggregate-view schema on the GRANTSPIDER Neon project.
-- ABOUTME: The Vintner reads ONLY these views (never base tables) to prove producer-side pipeline health.
--
-- =============================================================================
-- vintner_reader — read-only health-aggregate role for The Vintner (grantspider Neon)
-- =============================================================================
--
-- The Vintner (oversteward) monitors the data pipeline. On the grantspider
-- side it needs the embedding-cron heartbeat (dq_metric_snapshots), ingest
-- freshness (gov_fetch_log), and foundation-embedding coverage/shape
-- (foundations). The data contract (oversteward §4) forbids promoting
-- ag_research_reader, and ag_research_reader does not grant
-- dq_metric_snapshots or gov_fetch_log — so this is a NEW, separate role.
--
-- Pattern (mirrors ops/provision_ag_research_reader.sql + AG-5 views):
--   * vintner_reader reads ONLY the `vintner` schema views below.
--   * Views run with the OWNER's rights (the default, non-security_invoker),
--     so vintner_reader needs NO grant on public.* and never sees a base row.
--   * Views expose AGGREGATES ONLY — counts, ratios, freshness stamps,
--     dimension/norm summaries. No row-level data leaves the cellar.
--
-- Idempotent: safe to re-run. CREATE ROLE is guarded; views are CREATE OR
-- REPLACE; grants are additive.
--
-- TARGET DATABASE: `neondb` — the research corpus (foundations, enrichments,
-- dq_metric_snapshots, gov_fetch_log). NOT `grantspider_dagster` (Dagster's
-- run/event-log metadata) and NOT `postgres` (maintenance). All three exist in
-- the GS Neon project; the views below only resolve against `neondb`.
--
-- Invocation (run as the grantspider Neon project OWNER role, connected to neondb):
--   psql "$GS_NEON_OWNER_URL/neondb" -f provision_vintner_reader.grantspider.sql
--
-- Credentials: this script creates `vintner_reader` LOGIN with a password you
-- set on the marked line in section 1 at run time. The committed file carries
-- only a placeholder plus a guard that aborts if it is left unedited — so a real
-- password is never committed. Re-running resets the password idempotently.
-- Run as the project OWNER role; the owner that creates the role gains admin
-- over it (which is why a later password reset won't hit "permission denied").
--
-- Connection string to hand to the Vintner (env VINTNER_RESEARCH_DATABASE_URL):
--   postgresql://vintner_reader:<password>@<gs-host>/<gs-db>?sslmode=require
--
-- Verify after running:
--   psql "<vintner_url>" -c "SELECT * FROM vintner.embedding_heartbeat_v;"   -- succeeds
--   psql "<vintner_url>" -c "SELECT count(*) FROM public.foundations;"        -- permission denied
-- =============================================================================

-- 1. Role — created LOGIN with a password so it can connect immediately.
--    SET THE PASSWORD on the marked line below AT RUN TIME. Do not commit the
--    real value. Pure SQL (no psql-only syntax); runs in the Neon SQL editor,
--    psql, or any client. Idempotent: creates the role if absent, else resets
--    its password. format(%L) safely quotes any special characters.
DO $$
DECLARE
    vintner_pw text := 'REPLACE_WITH_A_STRONG_PASSWORD';   -- <<< EDIT AT RUN TIME, do not commit
BEGIN
    IF vintner_pw = 'REPLACE_WITH_A_STRONG_PASSWORD' THEN
        RAISE EXCEPTION 'Set vintner_pw to a real password before running (section 1).';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vintner_reader') THEN
        EXECUTE format('CREATE ROLE vintner_reader LOGIN PASSWORD %L', vintner_pw);
    ELSE
        EXECUTE format('ALTER ROLE vintner_reader WITH LOGIN PASSWORD %L', vintner_pw);
    END IF;
END $$;

-- 2. Schema for the aggregate views. vintner_reader gets USAGE here only.
CREATE SCHEMA IF NOT EXISTS vintner;
GRANT USAGE ON SCHEMA vintner TO vintner_reader;

-- 3. Views (aggregates only — no row-level exposure)

-- 3a. Embedding-cron heartbeat (Stage 13). The dead-man's-switch source.
--     Scalar subqueries throughout — Postgres rejects a subscript applied
--     directly to an aggregate expression, so last_metric_value uses an
--     ORDER BY ... LIMIT 1 subquery instead of (array_agg(...))[1].
CREATE OR REPLACE VIEW vintner.embedding_heartbeat_v AS
SELECT
    (SELECT max(computed_at) FROM public.dq_metric_snapshots
       WHERE metric_name = 'embedding_run')                                 AS last_run_at,
    (now() - (SELECT max(computed_at) FROM public.dq_metric_snapshots
       WHERE metric_name = 'embedding_run'))                                AS age,
    (SELECT metric_value FROM public.dq_metric_snapshots
       WHERE metric_name = 'embedding_run'
       ORDER BY computed_at DESC LIMIT 1)                                   AS last_metric_value,
    (SELECT count(*) FROM public.dq_metric_snapshots
       WHERE metric_name = 'embedding_run')                                 AS runs_total;

-- 3b. Foundation-embedding coverage + freshness (Stage 13/14, contract G6/G7).
--     website is NOT NULL DEFAULT '' — "has website" = website <> ''.
--     Counts only; vector math lives in 3c (sampled) to keep this cheap.
CREATE OR REPLACE VIEW vintner.embedding_health_v AS
SELECT
    count(*)                                                            AS foundations_total,
    count(*) FILTER (WHERE website <> '')                               AS foundations_websited,
    count(*) FILTER (WHERE embedding IS NOT NULL)                       AS embedded_total,
    count(*) FILTER (WHERE website <> '' AND embedding IS NOT NULL)      AS embedded_websited,
    round(
        count(*) FILTER (WHERE website <> '' AND embedding IS NOT NULL)::numeric
        / NULLIF(count(*) FILTER (WHERE website <> ''), 0), 4)          AS coverage_websited_ratio,
    count(*) FILTER (WHERE embedding IS NOT NULL
                     AND embedding_source_hash = '')                    AS embedded_missing_source_hash,
    min(embedding_updated_at) FILTER (WHERE embedding IS NOT NULL)       AS oldest_embedding_at,
    max(embedding_updated_at) FILTER (WHERE embedding IS NOT NULL)       AS newest_embedding_at
FROM public.foundations;

-- 3c. Embedding shape sanity over a recent sample (dim must be 384; L2 norm ~1.0
--     for normalized MiniLM output). Sampled to avoid a full 187K-row vector scan.
--     Norm via the core <#> operator (negative inner product) so it works on any
--     pgvector version: -(x <#> x) = ||x||^2.
CREATE OR REPLACE VIEW vintner.embedding_shape_sample_v AS
SELECT
    count(*)                                              AS sample_size,
    min(vector_dims(embedding))                           AS min_dims,
    max(vector_dims(embedding))                           AS max_dims,
    avg(sqrt(GREATEST(0.0, -1.0 * (embedding <#> embedding))))  AS avg_l2_norm,
    min(sqrt(GREATEST(0.0, -1.0 * (embedding <#> embedding))))  AS min_l2_norm,
    max(sqrt(GREATEST(0.0, -1.0 * (embedding <#> embedding))))  AS max_l2_norm
FROM (
    SELECT embedding
    FROM public.foundations
    WHERE embedding IS NOT NULL
    ORDER BY embedding_updated_at DESC NULLS LAST
    LIMIT 1000
) s;

-- 3d. Per-source ingest freshness (Stages 1-3, 5, 17-18). The Vintner compares
--     last_completed_at against config/freshness_slas.yaml windows, and surfaces
--     sla_miss rows + stuck 'running' fetches that freshness_slas already emits.
CREATE OR REPLACE VIEW vintner.ingest_freshness_v AS
SELECT
    source_id,
    max(completed_at) FILTER (WHERE status = 'completed')                AS last_completed_at,
    max(started_at)                                                      AS last_started_at,
    count(*) FILTER (WHERE status = 'sla_miss'
                     AND started_at > now() - interval '7 days')         AS sla_miss_7d,
    count(*) FILTER (WHERE status = 'running'
                     AND started_at < now() - interval '6 hours')        AS stuck_running,
    count(*) FILTER (WHERE started_at > now() - interval '24 hours')     AS runs_24h
FROM public.gov_fetch_log
GROUP BY source_id;

-- 3e. Synthetic semantic probe (the seam check). Uses the most-recent embedding
--     as a query vector and counts its nearest neighbours — exercising the HNSW
--     index + cosine operator end to end. Healthy ⇒ ~10; embeddings collapsed ⇒ 0.
--     Returns a count only: no rows, no ids, no vectors leave the view.
CREATE OR REPLACE VIEW vintner.semantic_probe_v AS
WITH q AS (
    SELECT embedding
    FROM public.foundations
    WHERE embedding IS NOT NULL
    ORDER BY embedding_updated_at DESC NULLS LAST
    LIMIT 1
)
SELECT count(*) AS neighbors_returned
FROM (
    SELECT f.id
    FROM public.foundations f, q
    WHERE f.embedding IS NOT NULL
    ORDER BY f.embedding <=> q.embedding
    LIMIT 10
) t;

-- 3f. Corpus & enrichment funnel (the pipeline-status data layer, issue #146).
--     One row per stage: (stage_order, stage, count, newest_at). stage_order
--     preserves the funnel sequence for the consumer; newest_at is the relevant
--     freshness stamp so the spine can judge running-vs-stopped / staleness.
--     Stages with no meaningful freshness column report newest_at = NULL.
--     Aggregate counts only — no row-level data leaves the cellar.
--
--     Notes baked from the scout (2026-06-30):
--       * sitemaps_discovered counts CANDIDATES discovered (sitemap_candidate_queue),
--         NOT fetched pages — do not conflate with websites_crawled (mine_urls).
--       * The enrichment stages (enrichments_active, missions_present,
--         deadlines_present) are fed by a stage that is currently kill-switched
--         OFF; the newest_at stamp is what reveals that. The view only reports
--         count + freshness; the spine interprets on/off.
--       * display_name_present is a deliberate "field exists / ~0% populated"
--         health signal.
--     website is NOT NULL DEFAULT '' — "has website"/"present" = <> '' (see 3b).
CREATE OR REPLACE VIEW vintner.corpus_funnel_v AS
SELECT 1  AS stage_order, 'foundations_total'        AS stage,
       count(*)                                                              AS count,
       NULL::timestamptz                                                     AS newest_at
FROM public.foundations
UNION ALL
SELECT 2, 'grantmakers_active',
       count(*) FILTER (WHERE is_active_grantmaker = true),
       max(last_classified_at) FILTER (WHERE is_active_grantmaker = true)
FROM public.foundations
UNION ALL
SELECT 3, 'gov_opps_total',
       count(*),
       max(updated_at)
FROM public.gov_opportunities
UNION ALL
SELECT 4, 'gov_opps_open_or_rolling',
       count(*) FILTER (WHERE status IN ('posted', 'preview', 'forecasted')
                        OR close_date IS NULL),
       max(updated_at) FILTER (WHERE status IN ('posted', 'preview', 'forecasted')
                        OR close_date IS NULL)
FROM public.gov_opportunities
UNION ALL
SELECT 5, 'sitemaps_discovered',
       count(*),
       max(enumerated_at)
FROM public.sitemap_candidate_queue
UNION ALL
SELECT 6, 'foundations_with_website',
       count(*) FILTER (WHERE website <> ''),
       max(website_resolved_at) FILTER (WHERE website <> '')
FROM public.foundations
UNION ALL
SELECT 7, 'websites_crawled',
       count(*) FILTER (WHERE status IN ('fetched', 'parsed')),
       max(last_fetched_at) FILTER (WHERE status IN ('fetched', 'parsed'))
FROM public.mine_urls
UNION ALL
SELECT 8, 'enrichments_active',
       count(*) FILTER (WHERE enrichment_status = 'active'),
       max(created_at) FILTER (WHERE enrichment_status = 'active')
FROM public.enrichments
UNION ALL
SELECT 9, 'missions_present',
       count(*) FILTER (WHERE mission IS NOT NULL AND mission <> ''),
       max(updated_at) FILTER (WHERE mission IS NOT NULL AND mission <> '')
FROM public.foundations
UNION ALL
SELECT 10, 'deadlines_present',
       count(*),
       max(source_captured_at)
FROM public.foundation_deadlines
UNION ALL
SELECT 11, 'display_name_present',
       count(*) FILTER (WHERE display_name IS NOT NULL AND display_name <> ''),
       NULL::timestamptz
FROM public.foundations
ORDER BY stage_order;

-- Explicit grant for the funnel view (issue #146) — the ALL TABLES grant in
-- section 4 also covers it, but this makes the vintner_reader access explicit.
-- No base-table grant is added; vintner_reader still reads only vintner.* views.
GRANT SELECT ON vintner.corpus_funnel_v TO vintner_reader;

-- 4. Grant SELECT on the views only (views are tables for this grant).
GRANT SELECT ON ALL TABLES IN SCHEMA vintner TO vintner_reader;

-- 5. Future views in this schema auto-grant to vintner_reader.
ALTER DEFAULT PRIVILEGES IN SCHEMA vintner
    GRANT SELECT ON TABLES TO vintner_reader;

-- 6. Verification (informational): what vintner_reader can read.
SELECT table_schema, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE grantee = 'vintner_reader'
ORDER BY table_schema, table_name;

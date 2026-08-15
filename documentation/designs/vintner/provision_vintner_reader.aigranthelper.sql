-- ABOUTME: Provisions the vintner_reader role + vintner aggregate-view schema on the AIGRANTHELPER Neon project.
-- ABOUTME: The Vintner reads ONLY these views (never the multi-tenant base tables) to prove consumer-side pipeline health.
--
-- =============================================================================
-- vintner_reader — read-only health-aggregate role for The Vintner (aigranthelper Neon, `default` DB)
-- =============================================================================
--
-- AG's `default` DB is multi-tenant and holds paying users' data:
-- matchmaker_match_* telemetry carries foundation_ein_hash and user-scoped
-- rows. The Vintner must NEVER see a user row. So — exactly as on the GS side
-- and per AG-5's security-barrier-view pattern — vintner_reader reads ONLY the
-- `vintner` schema of AGGREGATE views below (counts, ratios, freshness stamps),
-- with NO grant on public.* and no row-level access whatsoever.
--
-- Views are declared WITH (security_barrier = true) for defence in depth and
-- run with the OWNER's rights, so vintner_reader needs nothing on public.
--
-- Idempotent: CREATE ROLE guarded; views CREATE OR REPLACE; grants additive.
--
-- Invocation (run as the aigranthelper Neon project OWNER role):
--   psql "$AG_NEON_OWNER_URL" -f provision_vintner_reader.aigranthelper.sql
--
-- Credentials: this script creates `vintner_reader` LOGIN with a password you
-- set on the marked line in section 1 at run time. The committed file carries
-- only a placeholder plus a guard that aborts if it is left unedited — so a real
-- password is never committed. Re-running resets the password idempotently.
-- Run as the project OWNER role; the owner that creates the role gains admin
-- over it (which is why a later password reset won't hit "permission denied").
--
-- Connection string to hand to the Vintner (env VINTNER_AG_DATABASE_URL):
--   postgresql://vintner_reader:<password>@<ag-host>/<ag-db>?sslmode=require
--
-- Verify after running:
--   psql "<vintner_url>" -c "SELECT * FROM vintner.match_health_v;"               -- succeeds
--   psql "<vintner_url>" -c "SELECT count(*) FROM public.matchmaker_match_run;"   -- permission denied
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

-- 3. Views (aggregates only — no row-level exposure, no ein_hash, no vectors)

-- 3a. Match-run health over rolling windows (Stages C-G). Scalar subqueries keep
--     each aggregate independent (no fan-out join). semantic step_name and the
--     degraded flag are verified against apps/research/match_service.py.
CREATE OR REPLACE VIEW vintner.match_health_v
    WITH (security_barrier = true) AS
SELECT
    (SELECT count(*) FROM public.matchmaker_match_run
       WHERE created_at > now() - interval '24 hours')                          AS runs_24h,
    (SELECT count(*) FROM public.matchmaker_match_run
       WHERE created_at > now() - interval '7 days')                            AS runs_7d,
    -- runs that started but never reached a terminal status (telemetry orphan)
    (SELECT count(*) FROM public.matchmaker_match_run
       WHERE status = 'started' AND created_at < now() - interval '1 hour')     AS orphan_started,
    (SELECT count(*) FROM public.matchmaker_match_step
       WHERE step_name = 'match.semantic_query'
         AND created_at > now() - interval '24 hours')                          AS semantic_steps_24h,
    (SELECT count(*) FROM public.matchmaker_match_step
       WHERE step_name = 'match.semantic_query'
         AND created_at > now() - interval '24 hours'
         AND (output_summary->>'degraded')::boolean)                            AS semantic_degraded_24h,
    -- degraded_rate over the last 24h; NULL when no semantic steps ran (no traffic)
    (SELECT round(
         count(*) FILTER (WHERE (output_summary->>'degraded')::boolean)::numeric
         / NULLIF(count(*), 0), 4)
       FROM public.matchmaker_match_step
       WHERE step_name = 'match.semantic_query'
         AND created_at > now() - interval '24 hours')                          AS degraded_rate_24h;

-- 3b. Program-embedding coverage (Stage B). NULL-ness + freshness only; the
--     vectors themselves are never selected.
CREATE OR REPLACE VIEW vintner.program_embedding_health_v
    WITH (security_barrier = true) AS
SELECT
    count(*)                                                            AS programs_total,
    count(*) FILTER (WHERE embedding IS NOT NULL)                       AS programs_embedded,
    round(count(*) FILTER (WHERE embedding IS NOT NULL)::numeric
          / NULLIF(count(*), 0), 4)                                     AS coverage_ratio,
    min(embedding_updated_at) FILTER (WHERE embedding IS NOT NULL)       AS oldest_embedding_at,
    max(embedding_updated_at) FILTER (WHERE embedding IS NOT NULL)       AS newest_embedding_at
FROM public.programs;

-- 4. Grant SELECT on the views only.
GRANT SELECT ON ALL TABLES IN SCHEMA vintner TO vintner_reader;

-- 5. Future views in this schema auto-grant to vintner_reader.
ALTER DEFAULT PRIVILEGES IN SCHEMA vintner
    GRANT SELECT ON TABLES TO vintner_reader;

-- 6. Verification (informational): what vintner_reader can read.
SELECT table_schema, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE grantee = 'vintner_reader'
ORDER BY table_schema, table_name;

ABOUTME: Per-step instrumentation schema for the Grant Helper Pro Matchmaker workflow.
ABOUTME: Locks the telemetry shape before code lands, so the feedback layer has a typed substrate to query against.

# Matchmaker Instrumentation Schema

**Companion to:** [DETERMINISTIC_AGENTS.md](../DETERMINISTIC_AGENTS.md) §4.1 (Matchmaker as design lead).
**Status:** v0 — design proposal, not yet implemented in code.
**Authoritative for:** the typed shape of every telemetry row the Matchmaker emits, end to end.

This document locks the firmware-layer telemetry contract for Sphere I's flagship workflow. Per the synthesis in DETERMINISTIC_AGENTS.md §3.2, instrumentation must be designed alongside the skeleton — not bolted on after — because the analysis layer in §3.4 can only answer questions the schema is shaped for. Get this right at v0; retrofitting telemetry is many times more expensive than designing it.

---

## §1 Why a separate document

The skeleton in DETERMINISTIC_AGENTS.md §4.1 names the steps and sketches the contract. This document does three things the parent doc does not:

1. **Names every field, in every row, with a type and a redaction rule.**
2. **Specifies the wire format and the storage home.**
3. **Lists the analysis-layer queries the schema must answer**, so the schema is testable against its purpose.

If the schema cannot answer the §6 queries, it is incomplete and must be revised.

---

## §2 Storage home and wire format

**Storage:** `data/pipeline_history.jsonl` (the existing JSONL audit log). One row per step execution. Append-only.

**Wire format:** newline-delimited JSON. Each row validates against the envelope in §3 plus one of the per-step payloads in §5.

**Why JSONL:** the dispatch / project-status pipeline already writes here; one queryable home is worth more than per-agent silos (DETERMINISTIC_AGENTS.md §8.1). Querying is cheap with `jq`, `duckdb`, or a thin Python loader; no DB infrastructure required for v1.

**Compression / rotation:** none at v1. Defer until row count exceeds 10⁷ or file size exceeds 1 GB. Daily snapshot to S3 is a future concern.

---

## §3 Envelope (every row carries these)

```json
{
  "schema_version": 1,
  "ts": "2026-05-08T21:49:07.123Z",
  "sphere": "customer",
  "agent": "matchmaker",
  "run_id": "uuid-v7",
  "user_id_hash": "sha256:64hex",
  "session_id_hash": "sha256:64hex",
  "step": "profile_intake | feature_vector | centroid | hnsw_query | top_n | explanation | presentation | follow_up",
  "step_index": 0,
  "prompt_version": "matchmaker-explanation@v3" | null,
  "rubric_version": "matchmaker-quality@v2" | null,
  "model_id": "claude-opus-4-7" | null,
  "latency_ms": 142,
  "token_cost": {"input": 1024, "output": 256, "cache_read": 0, "cache_write": 0} | null,
  "outcome": "ok | partial | retry | refused | error",
  "error_code": "string-enum" | null,
  "payload": { ... per-step (§5) ... }
}
```

**Field rules:**

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | int | yes | Bump on any backwards-incompatible change to envelope or any payload. Analysis-layer queries pin a version. |
| `ts` | RFC 3339 UTC | yes | Server clock, not client. Resolution: ms. |
| `sphere` | enum | yes | `customer | internal | service | docs`. Always `customer` for Matchmaker rows. |
| `agent` | string | yes | `matchmaker` for this schema; other Sphere I agents (profile_builder, match_refresh, alert_generation) reuse the envelope with their own agent id. |
| `run_id` | uuid v7 | yes | One run = one user-initiated request through the full skeleton. All seven step rows for a single match request share `run_id`. UUID v7 so rows sort chronologically without needing the timestamp. |
| `user_id_hash` | sha256 hex | yes | Hash of the user's GHP user id with a fixed salt. **Never the raw user id.** Salt rotation is a coordinated event (invalidates joinability across rotations); document the rotation in `data/salt_rotations.jsonl`. |
| `session_id_hash` | sha256 hex | yes | Same construction as `user_id_hash`, hashing the session id. Lets us cohort by session without de-anonymizing. |
| `step` | enum | yes | One of the eight named steps below. Adding a step is a `schema_version` bump. |
| `step_index` | int | yes | 0-indexed position in the run. Lets us detect skipped steps without joining on `step`. |
| `prompt_version` | string\|null | yes | Versioned id of the prompt used at this step. Null on non-LLM steps. **Required to be non-null on every LLM step** — a row with `model_id != null && prompt_version == null` is malformed. |
| `rubric_version` | string\|null | yes | Versioned id of the evaluation rubric used at this step. Null when no rubric ran. |
| `model_id` | string\|null | yes | Anthropic model id (or other provider id) for LLM steps. Null on non-LLM steps. |
| `latency_ms` | int | yes | End-to-end wall time of this step's execution. |
| `token_cost` | object\|null | yes | LLM steps only. Cache read/write tracked because cache hit rate is itself a feedback signal. |
| `outcome` | enum | yes | `ok` (clean success), `partial` (degraded but usable, e.g. ungenerated explanation), `retry` (transient failure, retried), `refused` (structured refusal — see §4.2 in DETERMINISTIC_AGENTS.md), `error` (unrecoverable). |
| `error_code` | string\|null | yes | Set when `outcome ∈ {retry, refused, error}`. Drawn from a fixed enum per step (§5). Free-text errors are not allowed in this field — that's what `payload.error_detail` is for. |
| `payload` | object | yes | Per-step shape defined in §5. |

---

## §4 Redaction rules (PII discipline)

The Matchmaker reads sensitive organizational data — EINs, addresses, financial figures, board names. The instrumentation must never become a side-channel that leaks what the user accessed.

**Always-redacted (replaced with hash or category):**
- User id, session id → sha256 hash with salt (envelope).
- Foundation EIN in payloads → `ein_hash: sha256` (the EIN itself is in `research.*`, not in telemetry).
- Free-text dismiss reasons containing email addresses, phone numbers, or names → regex-scrub before write.
- Org name in profile payload → `org_name_hash` only.

**Stored as category, not value:**
- Organization budget size → bucketed enum (`<100k | 100k-500k | 500k-2m | 2m-10m | 10m+`).
- Geography → state/country code only, never street address.
- Focus areas → NTEE code (already a fixed taxonomy), never free-text.

**Never stored:**
- Raw form payloads (only the typed `ProfileV{n}` is stored, and only its content hash — see §5.1).
- LLM prompt text (only `prompt_version`).
- LLM completion text (only structured outputs — see §5.6).
- Any field marked `pii: true` in the GHP user-data inventory.

**Periodic audit:** monthly scan of `pipeline_history.jsonl` against a regex set (email pattern, phone pattern, EIN pattern, SSN pattern). Any hit is a P0 — rotate the salt, document the leak, fix the redaction.

---

## §5 Per-step payloads

Eight steps. Steps 1-7 are the Matchmaker skeleton from DETERMINISTIC_AGENTS.md §4.1. Step 8 (`follow_up`) is the post-presentation user-action capture — the gold signal.

### 5.1 `profile_intake`

```json
"payload": {
  "profile_version_hash": "sha256:64hex",
  "profile_version_n": 7,
  "fields_present": ["mission", "ntee_primary", "budget_bucket", "geography_state", "year_founded"],
  "fields_missing": ["board_size", "focus_areas_secondary"],
  "fields_skipped_by_user": ["focus_areas_secondary"],
  "validation_errors": [],
  "intake_source": "form | api | import"
}
```

- `profile_version_hash`: content hash of the typed profile object. Doubles as the idempotency key.
- `fields_missing` vs `fields_skipped_by_user`: missing = required and not provided; skipped = optional and the user actively skipped it. Distinct fields because the analysis-layer cares about both.
- `error_code` enum: `INVALID_NTEE | INVALID_GEO | BUDGET_OUT_OF_RANGE | REQUIRED_MISSING`.

### 5.2 `feature_vector`

```json
"payload": {
  "input_hash": "sha256:64hex",
  "vector_dim": 768,
  "sparse_features_count": 14,
  "extractor_version": "v2.1",
  "cache_hit": true
}
```

- `input_hash`: hash of the inputs to the extractor (typically the profile_version_hash plus the extractor version). Idempotency key.
- `cache_hit`: whether the vector was cached. Cache hit rate is itself a feedback signal — if it drops, profile churn has spiked.
- `error_code` enum: `EXTRACTOR_FAILED | DIM_MISMATCH | EMBED_API_TIMEOUT`.

### 5.3 `centroid`

```json
"payload": {
  "input_hash": "sha256:64hex",
  "org_history_used": true,
  "history_grants_count": 23,
  "centroid_dim": 768,
  "weights_version": "v1.4"
}
```

- Pure compute step in the happy path; rarely emits non-`ok` outcomes.
- `weights_version`: the feature-weight config version. Promotion (DETERMINISTIC_AGENTS.md §3.5) bumps this; analysis-layer can A/B over weight versions.
- `error_code` enum: `MISSING_HISTORY_KEY | WEIGHT_CONFIG_INVALID`.

### 5.4 `hnsw_query`

```json
"payload": {
  "centroid_hash": "sha256:64hex",
  "filters_applied": {"geography": "GA", "ntee_major": "T"},
  "k_requested": 50,
  "candidates_returned": 50,
  "query_plan_hash": "sha256:64hex",
  "ann_recall_estimate": 0.94,
  "research_db_freshness_hours": 18
}
```

- `query_plan_hash`: idempotency key for the query (centroid + filters + k).
- `research_db_freshness_hours`: hours since the last grantspider snapshot was applied. **Critical** — confidence scores in §5.6 derive partly from this.
- `error_code` enum: `RESEARCH_DB_UNAVAILABLE | INDEX_NOT_LOADED | FILTER_INVALID | RETRY_BACKOFF`.

### 5.5 `top_n`

```json
"payload": {
  "candidates_in": 50,
  "matches_out": 10,
  "filter_pipeline": ["dedupe", "freshness_gate", "exclusion_list", "score_threshold"],
  "filtered_counts": {"dedupe": 3, "freshness_gate": 2, "exclusion_list": 1, "score_threshold": 4},
  "score_min": 0.61,
  "score_max": 0.92,
  "score_median": 0.74
}
```

- The filter funnel is itself a feedback signal — if `freshness_gate` is dropping 30% of candidates, the producer has stale corpus.
- `error_code` enum: `RESEARCH_DB_READ_FAILED | EXCLUSION_LIST_UNAVAILABLE | EMPTY_RESULT_SET`.

### 5.6 `explanation`

```json
"payload": {
  "matches_in": 10,
  "explanations_generated": 9,
  "explanation_failures": 1,
  "evidence_citations_per_match": [3, 4, 2, 3, 5, 3, 2, 4, 3],
  "confidence_distribution": {"high": 4, "medium": 4, "low": 1, "abstained": 1},
  "abstain_reasons": ["EMPTY_PROVENANCE"],
  "data_freshness_factor": 0.87
}
```

- `explanation_failures`: count of matches where the LLM call errored or returned malformed output. The match still presents (per §4.1 design — "ungenerated explanation, not fabricated"), but the row records the gap.
- `evidence_citations_per_match`: array of citation counts per match. Zero is a red flag — should never present a match with zero citations (per the I-18 / `property_lineage` provenance rule).
- `confidence_distribution`: bucketed counts. `abstained` matches present without a confidence score; the reason is in `abstain_reasons`.
- `data_freshness_factor`: `1.0 - (research_db_freshness_hours / decay_hours)`, clamped to [0, 1]. Drives the `low` confidence bucket when the producer corpus has gone stale.
- `error_code` enum: `LLM_API_ERROR | LLM_TIMEOUT | MALFORMED_OUTPUT | PROVENANCE_LOOKUP_FAILED | RUBRIC_VIOLATION`.

### 5.7 `presentation`

```json
"payload": {
  "matches_rendered": 10,
  "render_format": "web | email | api",
  "render_variant": "control | experiment-a",
  "above_fold_count": 4
}
```

- `render_variant`: A/B test cohort. Joins back to the experiment registry by name.
- `above_fold_count`: how many matches the user can see without scrolling. Joins with §5.8 `position_clicked` to compute click-through above vs below the fold.
- Rarely emits non-`ok`.
- `error_code` enum: `RENDER_FAILED | MATCHES_LIST_EMPTY`.

### 5.8 `follow_up` — the gold signal

```json
"payload": {
  "action": "click | dismiss | save | export | apply_to | ignore | abandon",
  "match_id_hash": "sha256:64hex",
  "match_position": 3,
  "time_to_action_ms": 8420,
  "dismiss_reason_category": "wrong_geography | wrong_size | already_applied | not_relevant | other" | null,
  "dismiss_reason_text_redacted": "string-redacted-by-§4-rules" | null,
  "next_action_within_session": "click_other_match | refine_profile | search_manually | leave_session" | null,
  "applied_to_external_signal": "kit_email_clicked | export_downloaded | manual_self_report" | null
}
```

- One `follow_up` row per user action against a presented match. A single run can produce zero `follow_up` rows (user abandons the page) or many (user clicks several matches before saving one).
- `action: "abandon"` is emitted by a session-end hook when the user closes the tab without acting on any match. `next_action_within_session: "leave_session"` accompanies it.
- `applied_to_external_signal`: how we infer that the user actually pursued the match. Inferred from Kit / export logs / explicit user self-report — **see [gold-signal-ingestion.md](gold-signal-ingestion.md) for the three ingestion paths**, their idempotency rules, and the `run_id: null` exception for self-report (§5.6 of that doc, which amends the envelope rule in §3 of this one). **This is the gold field** — the only signal grounded in the user's real fundraising work.
- `dismiss_reason_text_redacted`: free-text dismissal reasons after PII scrub per §4. Most rows carry only `dismiss_reason_category`; free text is opt-in.
- `error_code` enum: `INVALID_MATCH_ID | OUT_OF_SESSION | DUPLICATE_ACTION`.

---

## §6 Analysis-layer queries (the schema's purpose)

The schema is incomplete if it cannot answer these. Each query is a v1 SQL/DuckDB sketch against `pipeline_history.jsonl`. If a query needs a field the schema does not have, the schema must be revised.

### Q1 — Step failure rates

> Which steps fail most often, and why?

```sql
SELECT step, error_code, COUNT(*) AS n, AVG(latency_ms) AS p50_ms
FROM pipeline_history
WHERE agent = 'matchmaker' AND outcome != 'ok'
  AND ts >= now() - INTERVAL '30 days'
GROUP BY step, error_code
ORDER BY n DESC;
```

Schema covers: `step`, `outcome`, `error_code`, `latency_ms`. ✓

### Q2 — Profile fields that predict good matches

> Are there profile fields that strongly predict good matches but that 60% of users skip?

```sql
WITH profile_completeness AS (
  SELECT run_id, payload->'fields_skipped_by_user' AS skipped
  FROM pipeline_history
  WHERE step = 'profile_intake'
),
gold_outcomes AS (
  SELECT run_id, COUNT(*) AS apply_count
  FROM pipeline_history
  WHERE step = 'follow_up' AND payload->>'applied_to_external_signal' IS NOT NULL
  GROUP BY run_id
)
SELECT json_array_elements_text(p.skipped) AS skipped_field,
       COUNT(*) AS runs,
       SUM(COALESCE(g.apply_count, 0)) AS total_applies,
       SUM(COALESCE(g.apply_count, 0))::float / COUNT(*) AS apply_rate
FROM profile_completeness p
LEFT JOIN gold_outcomes g USING (run_id)
GROUP BY skipped_field
ORDER BY apply_rate;
```

Schema covers: `payload.fields_skipped_by_user` (5.1), `payload.applied_to_external_signal` (5.8). ✓

### Q3 — Mechanically good, practically wrong matches

> Are there foundations that are matched often but never applied to?

```sql
WITH presented AS (
  SELECT payload->>'match_id_hash' AS match_hash, COUNT(*) AS times_presented
  FROM pipeline_history
  WHERE step = 'follow_up'
  GROUP BY match_hash
),
applied AS (
  SELECT payload->>'match_id_hash' AS match_hash, COUNT(*) AS times_applied
  FROM pipeline_history
  WHERE step = 'follow_up'
    AND payload->>'applied_to_external_signal' IS NOT NULL
  GROUP BY match_hash
)
SELECT p.match_hash,
       p.times_presented,
       COALESCE(a.times_applied, 0) AS times_applied,
       COALESCE(a.times_applied, 0)::float / p.times_presented AS apply_rate
FROM presented p
LEFT JOIN applied a USING (match_hash)
WHERE p.times_presented >= 50
ORDER BY apply_rate ASC
LIMIT 20;
```

Schema covers: `payload.match_id_hash`, `payload.applied_to_external_signal` (5.8). ✓

### Q4 — Prompt regression detection

> Did prompt version N+1 produce more low-confidence or abstained explanations than N?

```sql
SELECT prompt_version,
       AVG((payload->'confidence_distribution'->>'low')::int) AS avg_low,
       AVG((payload->'confidence_distribution'->>'abstained')::int) AS avg_abstained,
       AVG((payload->>'data_freshness_factor')::float) AS avg_freshness
FROM pipeline_history
WHERE step = 'explanation'
  AND ts >= now() - INTERVAL '14 days'
GROUP BY prompt_version
ORDER BY prompt_version;
```

Schema covers: `prompt_version` (envelope), `payload.confidence_distribution`, `payload.data_freshness_factor` (5.6). ✓

### Q5 — Above-fold click bias

> Are users only clicking above-fold matches? Is rank position dominating relevance?

```sql
SELECT match_position,
       COUNT(*) AS presents,
       SUM(CASE WHEN action = 'click' THEN 1 ELSE 0 END) AS clicks,
       SUM(CASE WHEN action = 'click' THEN 1 ELSE 0 END)::float / COUNT(*) AS ctr
FROM (
  SELECT (payload->>'match_position')::int AS match_position,
         payload->>'action' AS action
  FROM pipeline_history
  WHERE step = 'follow_up'
)
GROUP BY match_position
ORDER BY match_position;
```

Schema covers: `payload.match_position`, `payload.action` (5.8). ✓

### Q6 — Cache hit rate trend

> Is profile churn driving feature-vector cache misses?

```sql
SELECT date_trunc('day', ts) AS day,
       AVG(CASE WHEN (payload->>'cache_hit')::boolean THEN 1 ELSE 0 END) AS hit_rate
FROM pipeline_history
WHERE step = 'feature_vector'
GROUP BY day
ORDER BY day;
```

Schema covers: `payload.cache_hit` (5.2). ✓

### Q7 — Funnel attrition

> Where do users drop out within a single run?

```sql
SELECT step,
       COUNT(DISTINCT run_id) AS runs_reached,
       COUNT(DISTINCT run_id)::float
         / (SELECT COUNT(DISTINCT run_id)
            FROM pipeline_history
            WHERE agent = 'matchmaker' AND step = 'profile_intake') AS retention
FROM pipeline_history
WHERE agent = 'matchmaker'
GROUP BY step
ORDER BY MIN(step_index);
```

Schema covers: `step`, `step_index`, `run_id`, `agent` (envelope). ✓

### Q8 — Manual workaround detection

> Which deterministic paths are users routing around?

```sql
SELECT next_action,
       COUNT(*) AS n,
       AVG(time_to_action_ms) AS avg_dwell
FROM (
  SELECT payload->>'next_action_within_session' AS next_action,
         (payload->>'time_to_action_ms')::int AS time_to_action_ms
  FROM pipeline_history
  WHERE step = 'follow_up'
    AND payload->>'action' = 'dismiss'
)
GROUP BY next_action
ORDER BY n DESC;
```

Schema covers: `payload.next_action_within_session`, `payload.action`, `payload.time_to_action_ms` (5.8). The `search_manually` and `refine_profile` buckets are the workaround signal. ✓

---

## §7 What the schema does NOT cover (and why)

Listed explicitly so the gaps are deliberate.

- **No raw prompt or completion text.** §4 forbids it. Reproducibility comes from `prompt_version + run_id + step`; the prompt registry holds the prompt text by version.
- **No raw user inputs.** Only typed/hashed/bucketed projections. Free text is the highest-leakage surface.
- **No cross-tenant joinability beyond the salt-bound user hash.** A salt rotation severs the join; that is intentional. Long-running cohorts must be scoped within a salt epoch.
- **No real-time ingestion path.** Append to a JSONL file; the analysis layer queries the file. Streaming + a metrics DB (Prometheus, BigQuery) is a future concern, not v1.
- **No model-output diff detection.** "The model's answer for the same input changed" is a useful signal but requires storing more output data than §4 allows; defer.

---

## §8 Implementation checklist (what landing v1 looks like)

- [x] Authored `documentation/prompts/` registry conventions ([README](../prompts/README.md)) and the matchmaker v1 prompts: [explanation@v1](../prompts/matchmaker/explanation@v1.md) + [quality-rubric@v1](../prompts/matchmaker/quality-rubric@v1.md). Implementation moves these to the consuming repo per registry §9 when code lands; until then, oversteward holds the design v0.
- [ ] Define `MatchmakerEvent` Pydantic models matching §3 envelope + §5 payloads. Validation runs before append.
- [ ] Pipe each step's emit through a single `record_event(step, outcome, payload, ...)` helper so the envelope is constructed in one place.
- [ ] Salt configuration in env: `TELEMETRY_HASH_SALT`. Rotation logged to `data/salt_rotations.jsonl` with a date and a reason.
- [ ] Monthly redaction audit (regex scan over `pipeline_history.jsonl` for email/phone/EIN/SSN patterns); fail loud on any hit.
- [ ] First analysis-layer notebook: `notebooks/matchmaker-weekly.ipynb`, runs Q1-Q8 against the prior 7 days. Reviewed weekly with Nathan.
- [ ] Promotion log: `data/promotions.jsonl`, one row per prompt/rubric/weight version bump with the observation that drove it. This is the durable record of the firmware accumulating.

---

## §9 Maintenance

- Bump `schema_version` on any backwards-incompatible change to envelope or any payload. Pin a version in every analysis-layer query.
- Update §5 when a step is added, removed, or its payload shape changes.
- Update §6 when a new question gets asked enough that it deserves to be a standing query.
- If the §6 queries cannot be answered against current data, the schema is incomplete — revise rather than work around.

*Last updated: 2026-05-08 (v0 design proposal — companion to DETERMINISTIC_AGENTS.md §4.1).*

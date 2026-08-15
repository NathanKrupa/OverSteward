ABOUTME: Design doc for The Vintner — a runtime-Gaudí that proves Grant Helper Pro's data pipeline healthy or alarms, so every glass poured from the cellar is a perfect pour.
ABOUTME: Approved 2026-06-16; Phase 1 underway (read-only roles + views live on both Neon projects).

# The Vintner — Intent-vs-Reality Reconciliation for Grant Helper Pro

**Status:** **Approved 2026-06-16.** Phase 1 in progress — the `vintner_reader` roles and `vintner` aggregate-view layer are provisioned and verified read-only on both Neon projects (§4.7, §9). Spine implementation is next.
**Name:** **The Vintner** — fills the casks and monitors the ripening and perfection of the wine, so that every glass out of the cellar is a perfect pour. The metaphor maps to the architecture: **casks** = pipeline stages filling Neon tables; **ripening** = the intent checks proving each batch sound; **a corked bottle** = a silent failure; **a perfect pour** = the sellable slice the paying user receives. Gaudí tastes the *code*; the Vintner tastes the *wine*.
**Author:** Chestertron, 2026-06-13.
**Kinship:** Gaudí's runtime sibling — a discipline layer applied to *data and operations* instead of code.
**Anchors in existing governance:** implements [data-contract](../data-contract-grantspider-aigranthelper.md) gaps **G2** and **G7**, and realizes the unmet **§9 "required behaviors."**

**Decisions locked (2026-06-13):** home = **OverSteward** · access = **two dedicated read-only roles reading aggregate views only** (§4.7) · push = **GitHub-native first, Pushover if a louder channel is wanted** (§4.6) · name = **The Vintner**.

---

## 0. Premise corrections (read this first)

The brief contains factual errors that change the design. Each is verified against source.

| Brief says | Reality | Source |
|---|---|---|
| "64-dimension feature vectors" | **384-dim** (`all-MiniLM-L6-v2`, CPU sentence-transformers). "64" is the HNSW `ef_construction` index param. | `aigranthelper/apps/research/embedding_service.py:19-20` |
| "Haiku batch enrichment over ~1M 990-PF rows producing feature vectors" | Three conflated things: enrichment is **GS-owned, uses Sonnet, and is kill-switched OFF**; embeddings are MiniLM (not an LLM); Haiku is only in AG's *on-demand* match-explanation. | `grantspider/.../enrichment_assets.py:92`; `aigranthelper/apps/pipeline/match_engine.py:105-137` |
| "Nothing in the system can check reality against intent" | **Largely false.** A declarative intent spec and a deterministic freshness spine **already exist and run** for GS ingest: `config/freshness_slas.yaml`, `quality_rules.yaml`, `neutral_voice_rules.yaml`, plus the data contract's §5/§7/§10. Breaches already emit `sla_miss` rows. | `grantspider/config/freshness_slas.yaml`; data contract §5/§6 |

**The reframe this forces.** This is **not** "build intent-checking from scratch." The estate already has:
- a declarative freshness intent spec (`freshness_slas.yaml`) that runs and emits `sla_miss` on breach;
- declarative content-quality intent (`quality_rules.yaml`, `neutral_voice_rules.yaml`) gated in CI;
- a ratified cross-repo data contract whose **§12 explicitly assigns the missing operator-alerting surface (G2, G7) to oversteward**;
- ~25 GS Dagster stages with asset checks and a working dead-man's-switch (embedding cron, 25h).

What is **genuinely missing** (and is therefore the Vintner's real scope):
1. **No alerting / operator surface.** `sla_miss` rows and asset-check failures sit unseen. (Data-contract G2/G7; §9 required behaviors unmet.)
2. **Zero coverage of the highest-leverage seam.** The embedding cron (off-Dagster) → AG semantic search path is *not* covered by `freshness_slas.yaml` (which keys on `gov_fetch_log.source_id`; embeddings stamp `dq_metric_snapshots`). When it decays, AG silently falls back to heuristic-only.
3. **Zero AG-consumer-side health.** AG is on-demand, has rich telemetry (`matchmaker_match_*`) that nothing reconciles, no freshness checks, no Sentry, a single `web` dyno with no cron.
4. **No cross-repo reconciliation and no interpretive agent.**

So the Vintner **federates existing intent, fills the four gaps, and adds the alerting + agent layers** — it does not re-declare what GS already declares.

---

## 1. Stage inventory and silent-failure map

The pipeline spans **two repos on two Neon projects** (data contract §2):

| Django DB alias | Neon project | Owner | Vintner access |
|---|---|---|---|
| `default` | aigranthelper Neon | aigranthelper (RW) | **new `vintner_reader` role** → reads a `vintner` schema of aggregate health views only (§4.7) |
| `research` | grantspider Neon | grantspider | **new `vintner_reader` role** (cannot reuse/promote `ag_research_reader` per contract §4; needs `dq_metric_snapshots` + `gov_fetch_log` that role doesn't grant) → reads a `vintner` schema of views (§4.7) |

The seam — **GS produces, AG consumes read-only through `research.*`** — is the central fact. When a GS stage degrades, AG does not error; it *silently falls back* (heuristic-only matching; `degraded=True` telemetry flag nobody reads; data contract §9 row 1). Producer decay surfaces as quietly-worse matches. That is the canonical silent failure.

### 1.1 GrantSpider stages (producer) — condensed

(~25 stages; grouped, with *existing* observability so we don't rebuild it.)

| # | Stage | Cadence | Writes | Existing observability | Top silent-failure risk |
|---|---|---|---|---|---|
| 1-3 | Grants.gov / SAM.gov / USASpending ingest | daily / monthly | `gov_opportunities/programs/awards`, `gov_fetch_log` | **`freshness_slas.yaml` → `sla_miss` rows**, FetchLog, quality checks | Partial parse/truncation counted as success |
| 4-5 | Discovery gate / IRS BMF sync | weekly / monthly | `foundations`, `irs_bmf`, FetchLog | FetchLog + MaterializeResult | Regional CSV truncation → state coverage short |
| 6-8 | Sitemap discover → enumerate → drain | every 2h | `mine_urls`, `sitemap_candidate_queue` | MaterializeResult counts | **Queue grows unbounded if drain stalls** |
| 9 | Markdown snapshot | hourly | `mine_urls.markdown_b2_key`, B2 | `snapshot_attempted_at` stamps | "attempted but empty" indistinguishable from "not done" |
| 10 | Classification sweep | daily | `foundations.is_active_grantmaker`, `classifier_version` | MaterializeResult | Rule change w/o version bump → silent drift |
| 11-12 | **Enrichment extract (Sonnet) — DORMANT** / TTL reaper | daily | `enrichments` | `enabled` flag, provenance + consistency checks | Kill-switch off mistaken for "fine"; `expires_at` NULL → active forever |
| **13** | **Embedding generation (off-Dagster Railway cron)** | 05:00 UTC daily | `foundations.embedding` (384-dim), `embedding_source_hash`, `dq_metric_snapshots('embedding_run')` | **heartbeat row only** | **Cron dies silently; only the 25h switch catches it. NOT in freshness_slas.yaml.** |
| 14 | Embedding coverage (observe-only) | 06:00 UTC daily | (read-only) | **`foundation_embedding_cron_fresh` (RED >25h), backlog, write-consistency checks** | Stale metric cache → false RED |
| 15-20 | Entity res / fingerprints / state+vendor portals / audit rollup / DB-state snapshot | weekly→daily | various + `vendor_tenant_state` | FetchLog, lifecycle state machine, **cohort-consistency check** | Portal format change → fetched=0 reported as success |
| 21-25 | AG corrections pull→promote / IRS backfill / CFCSRA / robots | daily→weekly | `ag_correction`, `classification_errors`, `cf_funds`, `host_robots` | consistency checks, MaterializeResult | Orphan corrections never applied; scraper layout breakage |

**GS primitives to federate (read, don't rebuild):** `gov_fetch_log` (+ `sla_miss` rows from `freshness_slas.yaml`), `dq_metric_snapshots` (heartbeat table), `vendor_tenant_state` (lifecycle), Dagster asset checks, `gov_quality_rejections`, `structlog` completion events.

### 1.2 aigranthelper stages (consumer)

AG matching is **on-demand** (fires on a user click), not scheduled — so "didn't run" is meaningless and freshness heartbeats false-alarm overnight.

| # | Stage | Trigger | Existing observability | Top silent-failure risk |
|---|---|---|---|---|
| A | Foundation embedding (read dep) | GS Stage 13 owns it | none AG-side | **NULL/stale → semantic arm silently empty** |
| B | Program embedding | sync on `Program.save()` | `embedding_updated_at`; **failures silently swallowed** (`models.py:89-92`) | blank text → empty vector stored |
| C-F | Candidate select → heuristic → semantic → blend | on click | `MatchStep` counts; **`degraded` flag** | **research DB down → caught → heuristic-only, `degraded=True`, unwatched** |
| G-H | Telemetry persist / alignment upsert | on completion | `matchmaker_match_run/step/impression`, `program_grant_alignments` | partial txn → orphan `started` runs |
| I | Match explanation (Haiku) | on-demand | rationale NULL ratio | LLM failure handling unverified |

**AG primitives:** `matchmaker_match_run/step/impression` (rich per-run telemetry — a goldmine nothing reconciles), `PlatformSnapshot`, the golden-set gate (`golden_matches.yaml`, **pre-commit only**). No alerting, no Sentry, no cron.

### 1.3 Silent-failure map, distilled

1. **Cross-repo freshness/coverage collapse (highest, uncovered).** Embedding cron or enrichment decays → AG semantic arm silently empties → matches quietly regress. *Not* covered by existing freshness SLAs. **This is v1's target.**
2. **Producer batch stalls (high, partly covered).** GS catches most via `sla_miss`/asset checks — but **no alerting**.
3. **Outcome degradation (deferred to v2).** Matches run but are poor / users don't convert. Different listening point: golden-set drift, score-distribution drift, `user_rating`, GA4 funnels, and the contract's **§10 sellable-slice criteria**.

---

## 2. Critique of the starting hypothesis; chosen architecture

### 2.1 The three-layer hypothesis is sound — endorsed, with refinements

The brief asked us to critique the **intent spec → deterministic spine → leashed agent** hypothesis. It is the right shape; we keep all three layers. Seven refinements (A1–A7) make it fit the brownfield reality and protect it from its own failure modes:

**A1 — Federate, don't reinvent.** GS already runs a declarative freshness spine. The Vintner **reads existing signals** (`freshness_slas.yaml`'s `sla_miss` rows, `dq_metric_snapshots`, `gov_fetch_log`, AG's `matchmaker_match_*`) and adds *new* checks only where coverage is zero (the embedding→AG seam, AG-consumer health). Re-encoding GS's thresholds would create two sources of truth that drift (the R4 risk).

**A2 — Intent is distributed; the spec aggregates.** Intent already lives as version-controlled YAML *inside the repo that owns each stage* (`freshness_slas.yaml` in GS). The Vintner's spec **references those by pointer and only directly owns the cross-repo + AG-consumer + outcome slices nobody else owns.** Each repo keeps authorship of its own stage thresholds; the Vintner is the *aggregator and alerter*, not a central rival spec. This resolves "who owns the spec / how does it stay in sync."

**A3 — Logic is tested Python, not SQL-in-YAML.** Following Gaudí exactly: checks are **named, fixture-tested Python functions**; the spec (YAML) declares only *which* check, its *thresholds*, *severity*, *mode*, and *windows*. No SQL strings in config — untestable and against the no-raw-SQL-in-app doctrine. The Vintner's reads go through pre-aggregated **views** (§4.7), not raw base tables, centralized in tested read-adapter functions.

**A4 — Watch the watcher.** A heartbeat catches dead *stages* but not a dead *spine*. The spine emits a positive "all-clear" ping every run to an **external** service (healthchecks.io free tier) that alarms on overdue ping. The spine cannot detect its own death; infrastructure it doesn't control must.

**A5 — Un-runnable check ⇒ RED, never skipped.** If a check's query throws (column renamed, permission revoked, DB unreachable), that is **not** green and **not** a silent log-and-continue — that is the watcher failing silently, the exact thing we fight. An un-runnable check is RED ("cannot prove healthy") and routes to alerting like any red. This makes the spine honest about its own blind spots.

**A6 — Agent is read-only and edge-triggered.** Fires only on status *transitions* (green→yellow→red) and a rate-limited periodic review. Never per-tick while stuck-red. Never writes to the pipeline or the spec — returns a narrative for human review.

**A7 — Alerting reuses the estate's nervous system, correctly.** `~/.claude/shared/inbox.md` lives on Nathan's local machines, **not in the cloud** — a cloud cron cannot write it. Resolution: the **cloud spine is source-of-truth** and alerts via durable, cloud-reachable channels (a rolling GitHub issue in OverSteward labeled `pipeline-health` + a push for red). The **local inbox is a view materialized at session start**: the session-start routine (or `/project-status`) pulls open `pipeline-health` issues and writes the yellow/red lines into the local `inbox.md`. Discipline still externalizes — the finding reaches the steward — but through a channel that survives the cron and the laptop being closed.

### 2.2 Chosen architecture

```
        ┌───────────────────────────────────────────────────────────────┐
        │  INTENT  (distributed)                                          │
        │   • GS-owned:  config/freshness_slas.yaml, quality_rules.yaml   │ ← referenced, not copied
        │   • Contract:  data-contract §5/§7/§10 (coverage-critical)      │
        │   • Vintner-owned:  vintner-intent.yaml — ONLY the        │
        │     uncovered slices: embedding↔AG seam, AG-consumer, outcome   │
        └───────────────────────────────┬───────────────────────────────┘
                                         │ read
        ┌────────────────────────────────▼──────────────────────────────┐
        │  DETERMINISTIC SPINE  (scheduled, non-AI, read-only)            │
        │   Read adapters (tested fns): GS research Neon · AG default Neon │
        │     · sla_miss rows · dq_metric_snapshots · matchmaker_match_*   │
        │   Synthetic seam probe: run a canned semantic query, assert     │
        │     non-empty valid result (proves seam regardless of traffic)  │
        │   Checks (tested fns; spec tunes thresholds/severity/mode):     │
        │     ratio · max_age · shape · invariant · count_delta           │
        │   Un-runnable check ⇒ RED.   Heartbeat ⇒ stage RED if overdue.  │
        │   Self-heartbeat ⇒ external all-clear ping (watch-the-watcher)  │
        └───────┬──────────────────────────────────────────────┬─────────┘
                │ green/yellow/red + transitions                │ on y/r transition
                ▼                                                ▼
   ┌────────────────────────────────┐         ┌────────────────────────────────┐
   │ ALERTING (cloud-durable)        │         │ LEASHED AGENT (event-driven)    │
   │  • GitHub issue `pipeline-health`│        │  read-only, Haiku→Sonnet         │
   │  • push (red only)               │◄───────│  interprets drift / "passing    │
   │  • reports/YYYY-MM-DD.md         │ narrat.│  but wrong" → {gap,hypothesis,  │
   │  • inbox.md ← materialized at    │        │  fix}; never writes pipeline    │
   │    session start (pull, not push)│        └────────────────────────────────┘
   └─────────────────────────────────┘
```

**Reliability split (honoured):** the spine is pure Python + read-only SQL + YAML, **zero LLM calls, zero dependency on the agent**. Agent broken/disabled/out-of-credit ⇒ spine still computes status and still alerts.

### 2.3 Where it lives — recommendation: **OverSteward**

The data contract **already assigns G2/G7 to oversteward**, and OverSteward already (a) owns the cross-repo contract, (b) does read-only cross-repo reconciliation (`gather.py`), (c) writes `reports/YYYY-MM-DD.md`, (d) feeds the inbox, (e) has cross-repo read surfaces (`/project-status`, `/sync-status`). It is independent of both watched runtimes — satisfying the reliability split — without a new repo.

| Option | Verdict |
|---|---|
| **OverSteward tool + GitHub Action cron** | **Recommended.** Owner already assigned; surfaces/reports/inbox already exist; independent of AG & GS; GitHub Action cron is free and runs even when laptops are off. |
| New dedicated repo | Defer. Graduate here only if it outgrows OverSteward (own Railway service, many stages). |
| AG management command | Rejected: couples the watcher to a watched repo; muddies AG's domain. |
| Fiscus extension | Rejected: Fiscus observes the *dev process* on a kaizen clock; runtime alerting needs a different cadence. |

Deployment: **GitHub Action scheduled workflow** in OverSteward for Phase 1 (free, durable, independent). Graduate to a Railway cron only if 30-min cadence in Actions proves limiting.

---

## 3. Intent-spec schema and worked example

### 3.1 Schema — Vintner-owned slice only

YAML declares *what to check and how strict*; the *how* is tested Python (A3). The spec references GS-owned specs rather than copying them.

```yaml
version: 1
contract_version: "1.2"          # the data-contract rev this spec was written against (A on drift)
references:                       # federated, not copied (A1/A2)
  - repo: grantspider
    spec: config/freshness_slas.yaml
    via: "sla_miss rows in gov_fetch_log"   # spine reads these; does not re-declare thresholds
  - doc: data-contract §7 coverage-critical surface

defaults:
  unrunnable_check: red           # A5 — cannot prove healthy = red
  alert_on: transition            # edge-triggered, not per-tick

stages:
  - id: gs.embeddings.generate
    title: "Foundation embedding generation (off-Dagster Railway cron)"
    owner_repo: grantspider
    db: research
    code_prefix: EMB
    mode: live                    # or: backfilling (relaxes coverage — A: backfill false-positives)
    heartbeat:
      check: heartbeat_max_age    # tested fn
      source: dq_metric_snapshots
      filter: {metric_name: embedding_run}
      stamp: computed_at
      max_age: 25h
      severity: red
    checks:
      - {check: coverage_ratio, numer: foundations_with_embedding,
         denom: foundations_with_website, yellow_below: 0.90, red_below: 0.75}
      - {check: max_age, target: max_embedding_updated_at, yellow_above: 26h, red_above: 48h}
      - {check: vector_dim, target: foundations.embedding, equals: 384, severity: red}
      - {check: vector_norm_sane, target: foundations.embedding, between: [0.95, 1.05], severity: red}
      - {check: invariant_zero, target: embedded_rows_missing_source_hash, severity: red}  # mirrors GS asset check + contract G6

  - id: ag.semantic.seam
    title: "AG semantic search (consumer of gs.embeddings)"
    owner_repo: aigranthelper
    db: default
    code_prefix: SEM
    depends_on: [gs.embeddings.generate]     # collapse producer+consumer double-red to one root cause
    checks:
      - {check: synthetic_probe, probe: canned_semantic_query,    # traffic-independent (A6)
         assert: non_empty_valid_results, red_on_fail: true,
         agent_hint: "Empty results usually mean foundation embeddings collapsed — check gs.embeddings first."}
      - {check: ratio_when_present, target: degraded_rate, window: 24h,
         yellow_above: 0.05, red_above: 0.25}   # only evaluated when runs exist; no traffic = green
```

**Check library (tested Python fns, A3):** `heartbeat_max_age`, `coverage_ratio`, `max_age`, `vector_dim`, `vector_norm_sane`, `invariant_zero`, `count_delta`, `ratio_when_present`, `synthetic_probe`. Each gets fail/pass fixtures (§4.5). `mode: backfilling` swaps a relaxed threshold table so a known backfill doesn't cry wolf.

### 3.2 Worked example — chosen stage: **embedding generation, NOT enrichment**

The brief suggested enrichment. **I recommend against it**, with reasons:
- Enrichment (GS Stage 11) is **kill-switched OFF** — a worked example would instrument a hypothetical.
- Embedding generation is **live, load-bearing, cross-repo, the single point of failure for AG's whole semantic arm, the most fragile stage** (off-Dagster bare cron, only the 25h switch as net), and — critically — **the one major stage NOT covered by `freshness_slas.yaml`** (it stamps `dq_metric_snapshots`, not `gov_fetch_log`). It is the exact uncovered gap, and it already has a partial heartbeat to build on. It also closes data-contract **G6/G7**.

The §3.1 YAML *is* the worked example. In prose: *"This stage must stamp a heartbeat ≤25h; ≥90% of websited foundations must carry a 384-dim, unit-norm vector with a source hash; the newest vector must be <26h old. Dimensionality, norm, write-consistency, or heartbeat breach is red — each silently breaks AG semantic search. Coverage/freshness slippage is yellow."* Paired with `ag.semantic.seam` (a synthetic probe + degraded-rate), the Vintner can **prove the seam healthy or alarm on it**.

**Enrichment folds in trivially** when un-killed: add a `gs.enrichment.extract` stage (heartbeat on `enrichments.created_at`, yellow on quarantine-rate >5%, red on cost-budget breach) — a few lines of YAML, no new code.

---

## 4. Deterministic spine + heartbeat design

### 4.1 What it is
Pure-Python package; no Django, no AI. Estate-layered: **OUTER** thin CLI/Action entrypoint (`vintner check|report|dry-run`); **MIDDLE** reconciliation service (load spec, run checks, compute status, emit findings, route alerts); **INNER** read-only Neon adapters (one per Neon project), the heartbeat checker, the synthetic probe, the external-ping client. Mirrors Gaudí's `Finding` (`code`, `severity`∈{green/yellow/red}, `stage`, `observed`, `expected`, `recommendation`, `context`) and a check registry keyed by name.

### 4.2 Schedule
**Every 30 minutes** via GitHub Action cron — read-only SQL, effectively free. Per-stage heartbeat windows come from the spec (daily stage ⇒ 25-26h; 2-hourly ⇒ ~2h15m). Each tick evaluates "is this stage overdue against *its* window"; alarms only on breach.

### 4.3 Storage
The spine reads actuals **fresh every run** (never trusts memory — verification doctrine). It persists only: (a) a status row per run for *transition* computation (its own tiny store — **not** in a DB it monitors, preserving the reliability split); (b) the rolling `pipeline-health` GitHub issue; (c) `reports/YYYY-MM-DD.md`.

### 4.4 Heartbeat / dead-man's-switch
- **Stage heartbeat:** latest stamp vs window; overdue ⇒ red *regardless of check results* (you cannot trust checks on data a dead stage produced). Most GS stages stamp something usable already.
- **Spine self-heartbeat (A4):** every successful run pings healthchecks.io; absence-of-ping alarms via a service the spine doesn't control.
- **AG on-demand:** no freshness heartbeat (would false-alarm overnight). Instead: the **synthetic seam probe** runs a canned semantic query every tick and asserts non-empty valid results — proving the seam *independent of user traffic* — plus ratio checks (`degraded_rate`) evaluated only when real runs exist.

### 4.5 Testing the watcher
Detection correctness is the entire value, so the spine gets **Gaudí-style fixture-first TDD**: each check fn ships `fail_*` / `pass_*` fixtures against synthetic DB states (e.g., a foundations fixture with 80% coverage must yield yellow; a 384→768 dim row must yield red; a 26h-stale heartbeat must yield red). The Phase 1 exit gate (§6.2) requires these green plus a live deliberately-stalled-cron test.

### 4.6 Alerting path (A7) — and the push-channel decision
Severity-routed via cloud-durable channels: **green** → daily report only (an *absent/stale* report is itself a yellow); **yellow** → upsert the rolling `pipeline-health` GitHub issue; **red** → issue + push. Local `inbox.md` is materialized at session start by pulling open `pipeline-health` issues. De-dup by transition (a stuck-red finding is alerted once, then summarized, not re-pushed).

**Push channel — recommendation (answers open-Q):** start **GitHub-native, add nothing.** Because red findings already open/update the `pipeline-health` issue, the **GitHub mobile app** delivers a real push for free, with zero new infra, secrets, or accounts — and it's already wired into the estate's "issues are the task board" doctrine. Adopt a dedicated channel only if GitHub's delivery proves too slow or too easy to mute:

| Option | Cost | Verdict |
|---|---|---|
| **GitHub mobile-app notification on the issue** | free | **Recommended for Phase 1.** Nothing to build; reuses the durable record that already exists. |
| **Pushover** | $5 one-time | **The upgrade if a louder, dedicated "the cellar is on fire" channel is wanted.** Purpose-built for server→phone, dead-simple HTTP POST, rock-solid delivery, no per-message friction. Add in Phase 3. |
| ntfy.sh | free | Free alternative to Pushover; HTTP POST to a topic. Caveat: use a reserved/obscure topic or self-host (public topics aren't private). |
| SMTP-to-email | ~free | Universal but noisy and easy to ignore — wrong instrument for an urgent red. |

Net: **GitHub-native now; Pushover later if red needs to shout.** No interactively-authed MCP is involved (R7).

### 4.7 Data access — two roles, views only (R8)
Following the estate's gold-standard pattern (`grantspider/ops/provision_ag_research_reader.sql`, AG-5's security-barrier views), the Vintner **never reads base tables** on either Neon project. Each owning repo exposes a **`vintner` schema of pre-aggregated health views**, and a dedicated **`vintner_reader`** role gets `USAGE` + `SELECT` on those views only — nothing else. The Vintner therefore never sees a single user's row; it sees counts, ratios, freshness stamps, and distribution buckets.

- **AG side (`vintner_reader` on AG `default` Neon):** a `vintner` schema with views like `vintner.match_health_v` (degraded-rate, started-orphan-rate, run volume — all aggregates over `matchmaker_match_*`, **no `ein_hash`, no user identity**) and `vintner.program_embedding_health_v` (coverage count + oldest `embedding_updated_at`, **not the vectors**). Provisioned via a Django migration creating the views + a reviewed `ops/provision_vintner_reader.sql` (mirrors the GS script).
- **GS side (`vintner_reader` on GS Neon):** a `vintner` schema exposing `vintner.embedding_health_v` (coverage, freshness, dim/norm samples, source-hash invariant over `foundations`), plus column-scoped read on the operational bookkeeping tables the existing AG role does **not** grant — `dq_metric_snapshots` (the embedding heartbeat) and `gov_fetch_log` (incl. `sla_miss` rows). Contract §4 forbids promoting `ag_research_reader`, so this is a *new* role. Provisioned via an Alembic migration + `ops/provision_vintner_reader.sql`.
- **Discipline inherited:** views are the column registry (no separate grant ledger); a new column becomes Vintner-visible only when a view migration adds it; least-privilege by construction; the role is `NOLOGIN` at create-time, Neon attaches login+password via console; the connection string is distributed out-of-band, never in version control (credential-hygiene doctrine).

These two view migrations + two provisioning scripts are the **first concrete Phase-1 deliverables** (one PR in AG, one in GS), since the spine cannot read anything until they land.

---

## 5. Leashed agent: triggers, inputs, output, cost

### 5.1 Triggers (event-driven, never looping)
1. Status **transition** to yellow/red (edge-triggered — once per transition, not per stuck-red tick).
2. **Weekly review:** one pass over the green board asking "what's *technically* passing but *obviously* wrong?" (drift, completeness).
3. Manual (Nathan, on a stage).
Hard prohibition: no perpetual loop, no per-tick calls.

### 5.2 Inputs
Pre-assembled by the spine (the agent does no open-ended querying): the triggering `Finding`(s); the stage's spec entry + `agent_hint`; a **bounded** slice of recent actuals the spine already pulled (e.g., 7-day metric history, the relevant distribution, the `depends_on` chain's statuses); recent report history (flapping?). **No raw DB access, no write access.**

### 5.3 Output
Short structured narrative persisted with the finding and folded into the issue/report:
```json
{"stage":"ag.semantic.seam","gap":"degraded jumped 2%→31% at ~04:30 UTC",
 "hypothesis":"gs.embeddings.generate red 26h ago; foundation embeddings unrefreshed → empty pgvector → heuristic-only fallback",
 "suggested_fix":"check Railway embedding-cron logs for OOM on the 05:00 run; re-run; confirm fresh dq_metric_snapshots stamp",
 "confidence":"high","root_cause_upstream":true}
```
`root_cause_upstream` lets the alerter collapse producer+consumer double-red into one item.

### 5.4 Cost envelope
- **Model:** Haiku for triage/most narratives; Sonnet only for genuine drift interpretation. **Metered credit pool** — so the leash is real money, not just tidiness.
- **Weekly review is ONE synthesis call** over per-stage summaries the spine pre-aggregates (not 30 calls). Transitions are one call each.
- **Estimate:** a bad week ≈ 10 transitions + 1 review ≈ **~11 calls**, each a few-thousand-token bounded context. Trivial. A perpetual-loop design would be ~1000× that.
- **Circuit breaker:** weekly call-count ceiling in config; if exceeded (flapping stage), the agent stops and the spine raises a meta-finding ("stage X flapping; agent leashed"). The deterministic layer is unaffected.

---

## 6. v1 scope and phased rollout

### 6.1 Decision: **v1 = Operational. Outcome = v2.**
Instrument the **operational** gap first — specifically the **embedding↔AG seam** (§1.3 class 1, the one major uncovered stage) and routing existing GS `sla_miss`/check signals to alerting (class 2). Justification:
1. **You can't trust an outcome metric on a pipeline you haven't proven ran.** Operational is the prerequisite, not a preference.
2. **Operational gaps are deterministic** — counts, freshness, coverage, dim, norm. No agent, no judgment. The boring-robust spine the reliability split demands.
3. **The highest-leverage silent failure is operational, cross-repo, and watched by nobody** (embedding decay → silent heuristic-only). And it's the gap the existing freshness spec doesn't cover.
4. **GS already has operational signals to federate** ⇒ fastest path to a working spine.

**Outcome (v2)** plugs into the same machinery at a different listening point — and the contract hands us ready-made assertions: golden-set drift (promote `golden_matches.yaml` from pre-commit to scheduled), score-distribution drift over `match_impression`, `user_rating` trend, **GA4 funnels via `analytics-mcp`**, and the **§10 sellable-slice criteria** (some deterministic: "differently-stale data after 30d"; "no placeholder / voice-drift / malformed EIN in results" — checkable against the corpus).

### 6.2 Rollout — one stage first
| Phase | Scope | Exit criterion |
|---|---|---|
| **0 (this doc)** | Design gate | Nathan approves architecture, schema, v1=operational, home=OverSteward |
| **1 — single seam, e2e** | **First: the two `vintner_reader` role + `vintner`-view PRs (AG, GS) — §4.7.** Then: `gs.embeddings.generate` + `ag.semantic.seam` only; tested check fns + fixtures; heartbeat + synthetic probe; GitHub-issue + report alerting; **self-heartbeat ping**; **no agent** | Roles live, views read-only-verified; fixtures green; spine flips red within window on a deliberately-stalled cron; true-positive `pipeline-health` issue; **zero false positives over 1 week** of normal operation |
| **2 — federate + consolidate** | Read GS `sla_miss` rows + asset-check source tables and route to alerting (closes G2/G7); add sitemap-drain-stall + dormant-enrichment-when-enabled; reference (don't copy) `freshness_slas.yaml` | Every GS operational silent-failure mode in §1.1 has a declared or federated intent entry and reaches alerting |
| **3 — graduate agent** | Edge-triggered Haiku agent on transitions + weekly review; circuit breaker; (optional) Railway cron if needed | Agent produces a useful narrative on a real transition; cost inside the weekly ceiling |
| **4 — outcome (v2)** | Promote golden-set to scheduled; score-distribution drift; `user_rating` trend; GA4 funnels; §10 sellable-slice checks | Outcome regressions surface distinct from operational ones |

Each phase is independently shippable. **Phase 1 alone closes the single highest-leverage silent-failure surface in the estate.**

---

## 7. Risks

- **R1 — Alert fatigue / false positives.** Re-creates the original problem if it cries wolf. *Mitigation:* yellow vs red discipline; `mode: backfilling` to silence known backfills; edge-triggered alerting; the 1-week zero-false-positive Phase-1 gate; a **`dry-run` mode** that replays a candidate spec against the last N days of actuals and reports what *would* have alarmed (prevents threshold-tightening storms).
- **R2 — Watcher fails silently.** *Mitigation:* external all-clear ping (A4); dead-simple pure-Python, no AI dependency; un-runnable-check⇒red (A5).
- **R3 — Spec rots / drifts from reality.** *Mitigation:* version-controlled + PR-diffed; `contract_version` field flags when the data contract has moved underneath it; weekly agent review asks "are thresholds still right?"; federating existing constants (not inventing) keeps it grounded.
- **R4 — Two sources of truth (Vintner spec vs GS configs).** *Mitigation:* A1/A2 — federate by reference; GS keeps authorship of its stage thresholds; the Vintner owns only the uncovered slices.
- **R5 — Schema drift breaks the spine's reads.** *Mitigation:* un-runnable⇒red surfaces it loudly; checks reference the data-contract §7 coverage-critical columns (contractually stable); complements the planned **G1 mirror-drift CI** (build-time schema drift) — Vintner is its runtime counterpart.
- **R6 — Metered agent cost surprise.** *Mitigation:* edge-trigger + weekly circuit breaker (§5.4); spine never depends on the agent, so hard-leashing is safe.
- **R7 — MCP unavailable in cron / inbox unreachable from cloud.** *Mitigation:* spine uses **no interactively-authed MCP**; alerting via GitHub issue + push + SMTP, never Gmail MCP; inbox is materialized at session start by pulling issues (A7).
- **R8 — Reading AG's multi-tenant production DB.** `matchmaker_match_*` carries `ein_hash`/user-scoped rows. *Mitigation (§4.7):* the Vintner reads **only a `vintner` schema of pre-aggregated views** through a dedicated `vintner_reader` role — never base tables, never row-level PII. Two new roles (one per Neon project; GS cannot reuse `ag_research_reader` per contract §4), provisioned via reviewed migrations + scripts that mirror the existing `ag_research_reader` discipline. A `CREATE ROLE` + view-`SELECT` grant is low-blast-radius DDL (no data/schema mutation of existing tables), but still applied deliberately with the project owner role via the Neon console — never a raw `psql` one-liner (credential-hygiene + never-migrate-shared-DB).
- **R9 — Scope creep into a general observability platform.** *Mitigation:* it answers exactly one question per stage — "does reality match declared intent?" — and routes the answer. YAGNI on dashboards/TSDBs; the daily report + issue + inbox suffice.

---

## 8. Decisions & remaining questions

**Resolved (2026-06-13):**
1. ✅ **Home = OverSteward.** Phase 1 is a GitHub Action cron + a new `src/oversteward/vintner/` module. (Contract already assigns G2/G7 here.)
2. ✅ **Create the read-only roles.** Approved — `vintner_reader` on *both* Neon projects, reading `vintner`-schema aggregate views only (§4.7). First Phase-1 deliverables: one view-migration + provisioning-script PR in AG, one in GS.
3. ✅ **Push = GitHub-native first** (mobile-app notification on the `pipeline-health` issue), Pushover as the Phase-3 upgrade if a louder channel is wanted (§4.6).
4. ✅ **Name = The Vintner.**

**Still open (not blocking Phase 1):**
5. **External watch-the-watcher:** healthchecks.io free tier (recommended) vs a row the GS Dagster daemon polls? — decide when Phase 1's self-heartbeat is wired.
6. **Should AG also raise its own app-level alarm on the `degraded=True` path** (contract §9 row 1: "log to Sentry"), independent of the Vintner? Defense-in-depth vs single source of truth — a small AG-side decision, deferrable.
7. **Apply path for the roles:** I'll prepare both provisioning scripts + view migrations as reviewable PRs; **applying the `CREATE ROLE` against each production Neon needs the owner connection** — confirm you'll run them via the Neon SQL console (recommended), or that there's a safe owner-role path you want me to use.

---

## 9. Phase-1 bring-up notes (verified 2026-06-16)

The two `vintner_reader` roles and `vintner` view layers are live and smoke-tested read-only on both Neon projects — all views readable, every base table denied. Operational learnings from the bring-up (these belong in the eventual runbook so they aren't re-discovered):

- **GrantSpider research data lives in the `neondb` database**, *not* `grantspider_dagster` (Dagster's run/event-log metadata) and not `postgres` (maintenance). The GS Neon project holds all three; the Vintner's `VINTNER_RESEARCH_DATABASE_URL` must target `neondb`. The AG project's data is likewise in its `neondb`.
- **Provision the role `LOGIN` with its password at creation, not via a later `ALTER ROLE`.** On Neon the non-super project owner can `CREATE ROLE` but cannot `ALTER` a role it doesn't hold admin over — and you only gain that admin by *being the creator*. The provisioning scripts set `LOGIN PASSWORD` in the create step (guarded placeholder, password supplied at run time, never committed). A `NOLOGIN`-then-`ALTER` sequence dead-ends.
- **Grant `SELECT` on the views after they exist** (script Section 4). `GRANT SELECT ON ALL TABLES IN SCHEMA vintner` only covers objects present at grant time; `ALTER DEFAULT PRIVILEGES` (Section 5) covers only *future* objects — so a top-to-bottom run is required, or the views are left ungranted.
- **Launch `gs.embeddings.generate` in `mode: backfilling`.** First live read showed embedding coverage at **7.6%** of websited foundations with `newest_embedding_at` advancing daily — an in-progress backfill, not a failure. Vector shape is perfect (dims 384, L2 norm ≈ 1.0) and the ANN probe returns neighbours. A coverage *floor* would false-RED on day one; backfill mode tracks rate-of-progress until coverage plateaus, then graduates to a floor. Live confirmation of the R1 / `mode` design.
- **First read also surfaced a real candidate signal:** two USASpending fetches (`az_usaspending`, `in_usaspending`) `running` ~13h with no completion — exactly the stuck-fetch class the spine targets. Noted for follow-up, not yet wired to alerting.

## Appendix — evidence base

Inventory gathered 2026-06-13 by direct read of:
- **GrantSpider:** `src/grantspider/orchestration/*` (~25 stages), `config/freshness_slas.yaml`, `config/quality_rules.yaml`, `schema/research.sql`, `docs/runbooks/embedding_cron_railway.md`, `ops/provision_ag_research_reader.sql`.
- **aigranthelper:** `apps/{pipeline,research,matchmaker,ops}/`, `embedding_service.py`, `semantic_matching.py`, `match_service.py`, `matchmaker/{orchestrator,telemetry,models}.py`, `Procfile`, `config/settings/production.py`, `tests/fixtures/golden_matches.yaml`, `apps/core/db_router.py`.
- **OverSteward:** `documentation/data-contract-grantspider-aigranthelper.md` (the anchor — §2 topology, §5 SLAs, §7 coverage-critical, §9 failure modes, §10 sellable slice, §12 gaps G1/G2/G6/G7), `registry.yaml`, `src/oversteward/gather.py`, `reports/`.
- **Gaudí:** `src/gaudi/{core,engine,pack,config,formats}.py` — for the Finding/Rule/Severity model, config-tunes-severity pattern, fixture-first TDD, and output formats reused above.

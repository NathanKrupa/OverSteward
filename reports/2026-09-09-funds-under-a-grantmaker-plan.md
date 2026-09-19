# Funds under a grantmaker — plan v2, red-teamed

Status: DRAFT for Nathan's approval. Written 2026-09-09. Repos: grantspider (schema, ingestion), aigranthelper (render, tracker).

Trigger: Meta's "The Future is for Everyone Fund – Aiken Data Center", administered by ChangeX (deadline 2026-10-19), cannot be tracked in AG because every tracker object requires a grantor, and the fund is a named opportunity under an intermediary. Nathan's ruling: build the general model now (zero customers, no migration pain) and build the community-foundation fund ingestion alongside it, since none exists.

## 0. Facts the plan stands on (measured 2026-09-09 against prod)

| Fact | Value | Consequence |
| --- | --- | --- |
| ChangeX in foundations | yes — `changex-united-states-inc`, EIN 83-4060943, public-charity grantmaker, no deadlines, pathway unknown | the administrator row exists; the fund and its deadline do not |
| Meta in corpus | no row of any kind; not in `registry/corporate_direct.yaml` (10 rows in prod) | sponsor must be minted |
| `cf_funds` rows | 0 (keyed to `community_foundations`, not `foundations`) | free to reshape; nothing to migrate |
| `community_foundations` | 988 rows from the COF locator, no EIN column, no link to `foundations` | the funder edge AG needs cannot be drawn today for any CF fund |
| CF websites matching a `foundations` row by domain | 791 of 928 | A9 (#1054) step 1 is mostly a join, not a merge |
| CF domains already crawled into `mine_urls` | 611 of 928; 28,001 snapshot pages, 8,384 classified `grant` | extraction can start on existing snapshots, no new crawl for two-thirds |
| `cf_site_profiles` | 0 rows | portal detection for CFs never ran; we do not know which CFs host funds off-site |
| `cfcsra_weekly` Dagster asset | registered and scheduled in code; `cf_funds` = 0, `scholarships` = 0 | the one per-site connector has never produced a prod row. Cause UNMEASURED (schedule off in UI vs failing) |
| `foundation_deadlines` | 28,380 rows (25,397 IRS-derived, 2,915 from the deterministic page extractor); AG reads them through `ag_research.foundation_deadlines_v`; the deadline suggester fires on funder save | a fund deadline written here under the administrator reaches the AG calendar with no AG change |
| Sanctioned LLM extraction path | `enrich-drain`: in-session Sonnet agents on Max, `pull-batch` → agent → `apply` with gates, zero metered key | fund extraction rides the same rails; no new spend vector |
| Existing issues | GS#1310 (A11 CF funds with application processes), GS#154 (CF fund scrape pipeline, pre-cutover, describes 1,929 phantom funds that no longer exist), GS#1054 (A9 merge), GS#2471 (portal vendors never followed), GS#1311 (platform-link detection), GS#2506 (Vinea via CFCSRA) | this plan supersedes #154, delivers #1310, does steps 1–2 of #1054, takes (a)+(b) of #2471, and closes #2506 as its second fixture |
| AG seam | AG mirrors GS tables by `inspectdb` at the SHA in `research_schema.lock`, gated by `GRANTSPIDER_OWNED_TABLES` | GS schema must land additively before the AG lock bump |

## 1. Red team of plan v1

Plan v1 said: generalize `cf_funds` to any intermediary, key funds to the administrator foundation, add a sponsor edge, write fund deadlines into `foundation_deadlines`, ingest by registry YAML, render on AG, resolve the CF seam "alongside". Findings, each with the change it forces:

- **R1 — the CF seam is the critical path, not a side quest.** A fund at a community foundation cannot carry the funder edge AG requires until the CF has a `foundations` row. Change: `community_foundations.foundation_id` (nullable FK) backfilled by domain (791), then EIN/name for the rest, and a minted `foundations` row (ein NULL, `data_source='cof_locator'`, `grantmaker_kind='community_foundation'`) for the ~137 unmatched. This is #1054 steps 1–2; the table drop (step 3) stays deferred behind two weeks of dual-read, as that issue already prescribes.
- **R2 — per-site parsers do not scale and the only one never produced a row.** Change: no new site-specific connectors. The generic path is crawl snapshot → extraction. CFCSRA's connector is kept only as a source for the Vinea fixture until the drain covers it.
- **R3 — deterministic-only extraction cannot pull fund name, eligibility, geography, award range from heterogeneous CF pages, and Nathan-law forbids LLM tokens on page classification.** Extraction is enrichment, not classification, and the sanctioned enrichment path already exists. Change: a `funds` drain on the `enrich-drain` rails, in-session Sonnet, zero metered key. Hallucinated funds are the risk, so `apply` gates are stricter than the profile gates: the fund name must appear (normalized) in the cited snapshot; the cited `source_url` must be in the batch the agent was handed; a deadline is accepted only if the deterministic deadline extractor parses the same date from that page; award floor/ceiling are numeric fields and must be `<=`-ordered. A row failing any gate is rejected, not partially written.
- **R4 — many CFs host their grants on Foundant/Submittable/Fluxx portals off-host, and the crawl is same-host by construction.** For those, the snapshot says "apply through our portal" and yields no funds. Change: run the existing platform detector over the 28,001 snapshots (deterministic, no crawl) and persist `application_platform`; count portal-only CFs and report them. Depth-1 off-host portal fetch (#2471 c) is explicitly v2. The number of CFs we cannot reach in v1 is a measured output, not a surprise.
- **R5 — writing fund deadlines under the administrator conflates a CF's fourteen funds into one deadline list.** AG renders deadline lines per foundation. Change: `foundation_deadlines.fund_id` (nullable FK). The view exposes it and the fund name; AG groups by fund on the page. Saving the funder still yields every fund deadline in the calendar with no AG change, which is the tracker requirement.
- **R6 — the sponsor is not a foundation row and the corporate-direct registry writes `community_impact_url` into `website`.** Pointing Meta's `website` at the ChangeX funds page would mis-resolve Meta. Change: Meta enters `corporate_direct.yaml` with Meta's own community page as `website` (verify at build time; do not invent), and the fund row carries the ChangeX `application_url`. `funds.sponsor_foundation_id` is nullable; most CF funds have none.
- **R7 — ChangeX runs one Meta fund per data-center town.** Change: natural key is `(data_source, source_id)` (already on `cf_funds`) with `source_id` derived from the fund page URL, so per-town funds are distinct rows under one administrator with their own geography and cycle.
- **R8 — a renamed or rekeyed `cf_funds` breaks AG's generated model mid-flight.** Change: new `funds` table, additive; `cf_funds` left empty and untouched until Phase 4; AG lock bump only after the GS migration is on prod. The additive-part-1 sequencing the estate already uses.
- **R9 — v1 acceptance was a schema, not an outcome.** Change: two real fixtures prove the whole seam end to end: the Aiken fund (corporate sponsor, intermediary administrator) and Vinea (#2506; foundation sponsor, CF administrator). Done means the AG staging calendar shows each deadline with the fund name after saving the administrator.
- **R10 — a scheduled asset that has produced zero rows is the failure mode the new pipeline would inherit.** Change: Phase 0 root-causes `cfcsra_weekly`'s silent zero from Dagster run history before any new orchestration is added, and every drain/apply run asserts a non-zero applied count or exits red (a canary must be able to alert every run).
- **R11 — "a system for uploading fund pages" can balloon into a new crawler.** Change: v1 crawls nothing new. Extraction runs on the 611 CFs already in `mine_urls`; the 317 uncrawled CF homepages are enqueued into the existing frontier at existing politeness (5 s/host), and their funds arrive whenever the frontier reaches them. Grants-page discovery heuristics (#154 stage 1) are dropped: the frontier plus the `grant` page classification already does that job.
- **R12 — Dagster as the driver contradicts Nathan-law on scheduled agents.** Change: the drain is manually launchable in-session, idempotent, and DB-resumable (cohort state = "CF foundations with grant snapshots and no `funds` extraction newer than the snapshot"). Dagster runs only the deterministic parts (platform detection, deadline refresh) if anything.

## 2. Revised plan

### Phase 0 — measure (no schema)
- Root-cause `cfcsra_weekly` = 0 rows (schedule state in the prod Dagster UI, last run status). Record the finding on #777's successor or a new issue.
- Run the platform detector over existing CF snapshots; report `portal-only` count. Deterministic, zero crawl.
- Deliverable: one report comment with the numbers above; sizes Phase 2b honestly.

### Phase 1 — GS schema, additive (one migration PR carrying its ORM declarations, per the GS migration doctrine)
- `funds`: `id`, `administrator_foundation_id` FK `foundations` NOT NULL, `sponsor_foundation_id` FK `foundations` NULL, `fund_name`, `fund_kind`, `description`, `geographic_focus`, `eligibility`, `program_areas`, `application_url`, `application_process`, `accepts_applications` bool, `award_floor`, `award_ceiling`, `contact_name`, `contact_email`, `source_url` NOT NULL, `data_source`, `source_id`, `completeness_status` (existing vocabulary), `extractor_version`, `source_captured_at`, timestamps. UNIQUE `(data_source, source_id)`; CHECK `award_floor <= award_ceiling`; index on administrator.
- `foundation_deadlines.fund_id` FK `funds` NULL; `foundation_deadlines_v` gains `fund_id`, `fund_name`.
- `community_foundations.foundation_id` FK `foundations` NULL, backfilled by domain then EIN/name; minted `foundations` rows for the unmatched remainder.
- `cf_funds`, `cf_site_profiles` untouched.
- Proof: migration reversible (existing `migration_reversibility` harness); backfill idempotent; a fixture CF with no domain match gets exactly one minted row on repeated runs.

### Phase 2a — manual ingestion path (ships the Aiken fund; first week)
- `registry/funds.yaml` + `grantspider funds apply --registry` (idempotent upsert of fund + its deadline row under the administrator, `data_source='funds_registry'`).
- Meta added to `registry/corporate_direct.yaml` as sponsor.
- First entries: Meta Aiken (administrator ChangeX), Vinea (administrator CFCSRA, sponsor Vinea once minted from its website).
- Proof: after apply, `foundation_deadlines_v` returns 2026-10-19 with the fund name for ChangeX's id.

### Phase 2b — fund drain on the enrich-drain rails
- `grantspider funds pull-batch`: cohort = CF foundations (via `community_foundations.foundation_id`) with ≥1 `grant`-classified snapshot and no extraction newer than the snapshot; emits per-CF source bundles + a versioned prompt.
- `.claude/workflows/funds-drain.js`: split → N Sonnet agents → JSON funds per CF → `grantspider funds apply --batch` with the R3 gates. Re-runnable; resumes from DB state.
- Coverage report command: CFs in cohort / CFs drained / funds written / funds with an application process / portal-only CFs. Feeds A10 (#1055).
- Proof: a seeded fixture bundle where the agent output contains one fabricated fund and one mis-cited URL, and `apply` rejects both while writing the true rows (red against a gate-less apply).

### Phase 2c — platform detection persisted (deterministic)
- Extend `GRANTS_PLATFORM_DOMAINS` with Submittable, Fluxx, Foundant/GrantInterface, Blackbaud, WizeHive, Benevity, SurveyMonkey Apply (#2471 a); persist `application_platform` on `foundations` from snapshot links (#2471 b). Off-host fetch (#2471 c) stays out.

### Phase 3 — AG
- `research_schema.lock` bump; regenerate research models; `funds` added to `GRANTSPIDER_OWNED_TABLES`.
- Foundation page: a "Funds and programs" section listing funds under the administrator with geography, eligibility, cycle, apply link (only when `accepts_applications`), award range when present. Deadline lines grouped by fund.
- Tracker: no model change. Saving the administrator pulls fund deadlines into the calendar through the existing suggester; the calendar row carries the fund name. Save-a-fund as its own tracker object is deferred until a user asks.
- Proof: staging smoke — save ChangeX, calendar shows the Aiken deadline titled with the fund; save CFCSRA, calendar shows the Vinea windows.

### Phase 4 — cleanup
- Drop `cf_funds`; move CFCSRA's parser into a registry entry or retire it; close #154, #1310, #2506 with receipts; #1054 step 3 (drop `community_foundations`) after two weeks of dual-read.

## 3. Design coverage matrix

| Requirement | Where it lands | Proof |
| --- | --- | --- |
| Aiken fund trackable in AG with its deadline | 2a + existing suggester | staging calendar shows 2026-10-19 with fund name |
| Vinea via CFCSRA trackable | 1 (CF link) + 2a | staging calendar shows both windows |
| Named funds under any administrator (CF, intermediary, corporate) | 1 (`funds` keyed to `foundations`) | one row each for a CF fund, a ChangeX fund, a corporate-direct fund |
| Sponsor distinct from administrator | 1 (`sponsor_foundation_id`) + R6 registry rule | Meta row's website is Meta's page, fund's apply URL is ChangeX |
| CF funds ingested from CF websites at scale | 2b on existing snapshots; frontier for the rest | ≥100 CFs with ≥1 sourced fund row (from #1310 AC) |
| No fund without a source page | 1 (`source_url` NOT NULL) + 2b gates | fabricated-fund fixture rejected |
| No LLM on classification; enrichment on Max only | 2b uses enrich-drain rails; 2c deterministic | `guard_metered_api.py` unchanged; no API key in the workflow |
| Deadlines keep the non-nullable funder edge | 1 (`fund_id` nullable, `foundation_id` unchanged) | view returns fund deadlines under the administrator |
| Portal-hosted funds not silently missing | 0 + 2c | portal-only count in the coverage report |
| AG seam not broken mid-flight | additive schema, lock bump after prod migration | AG CI green on the bump PR |
| Silent-zero pipelines caught | 0 root cause + per-run non-zero assertion | forced empty batch exits red |
| Multi-day drain does not hold the DB active | 2b batches: pull, local ledger, batched apply (GS#2384 ruling) | no long-lived session in the workflow |

## 4. Out of scope for v1 (named so they are not silently dropped)
- Depth-1 off-host portal fetch (#2471 c).
- Grants-page discovery crawl beyond enqueuing the 317 uncrawled CF homepages.
- Save-a-fund as a tracker object in AG; the "add a funder that isn't listed" form (still wanted for entities GS does not hold; separate issue).
- Scholarships.
- Dropping `community_foundations` (Phase 4, gated).

## 5. Cost
- Metered API: none. The drain runs in-session on the Max subscription.
- Agent effort: roughly 600 CF slices for the first drain; the enrich-drain precedent puts this at a few sessions.
- Database: under 10k new rows; no CU-hour or latency lever touched.
- Engineering: Phase 0 S, Phase 1 M, 2a S, 2b L, 2c S, Phase 3 M, Phase 4 S.

## 6. Decisions Nathan owns
1. Mint `foundations` rows for the ~137 CFs with no domain/EIN match (ein NULL, like corporate-direct), or leave them fund-less in v1. Recommendation: mint.
2. Keep the sponsor edge on `funds` (nullable). Recommendation: yes; it is what makes Meta-via-ChangeX and Vinea-via-CFCSRA honest.
3. Confirm the enrich-drain precedent extends to structured fund extraction on Max. Recommendation: yes, with the stricter apply gates in R3.
4. Approve the phase order. Phase 2a ships the Aiken fund to the tracker in the first week regardless of 2b's progress.

On approval: file a GS epic carrying this plan with one issue per phase, cross-link #1310/#154/#1054/#2471/#2506, and open the AG issue for Phase 3. Each phase is its own PR through the standard worktree → adversarial review → PR loop.

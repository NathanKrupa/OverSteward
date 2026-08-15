ABOUTME: The GrantSpider to AIGrantHelper data contract — ownership, access rules, freshness SLAs, change management, sellable slice.
ABOUTME: Canonical cross-repo spec for how grantspider (producer) and aigranthelper (consumer) share the research data substrate.

# GrantSpider to AIGrantHelper Data Contract

**Status:** Active — v1.2 (2026-04-30)
**Producer:** grantspider
**Consumer:** aigranthelper
**Home:** OverSteward `documentation/` (cross-repo governance)

> Data is the product. grantspider is the factory. aigranthelper is the storefront. This document is the SKU spec between them.

---

## 1. Purpose

aigranthelper is a Django SaaS whose differentiated value is the enriched grant / funder / award corpus that grantspider produces. This contract defines the engineering and product surface between the two repos so that:

1. The data a paying customer sees today is the data we committed to produce.
2. Schema changes in grantspider do not silently break aigranthelper features.
3. Both sides know where the ownership line is and what requires cross-repo coordination.
4. Failure modes (stale, offline, drift) are handled predictably, not accidentally.

This is not a public API description, not marketing copy, and not a complete field dictionary. It is the spec that must stay true while the two repos evolve. It lives in OverSteward because neither repo exclusively owns a two-way contract.

---

## 2. Topology

**Two Neon projects, one database each.** Post-2026-04-30 cutover (aigranthelper PR #413, grantspider PR #626): the producer and consumer no longer share a Neon cluster. grantspider lives on its own Neon project (`ep-plain-breeze-amopwc5f`); aigranthelper retains the original cluster (`ep-solitary-art-aenuetaf`) for its default DB.

| DB alias (Django) | Neon project | Owner | Migration tool | aigranthelper access |
|---|---|---|---|---|
| `default` | aigranthelper Neon | aigranthelper | Django migrations | RW |
| `research` | grantspider Neon | grantspider | Alembic (SQLAlchemy ORM) | **read-only** (Neon role `ag_research_reader`) |

**Django routing.** `apps/core/db_router.py::SchemaRouter` maps the `research` app label to the `research` alias. All grantspider-owned models in `apps/research/models/` are declared `managed = False` and queried with `.using("research")`. After PR #413, `allow_migrate` returns `False` for the entire `research` label whenever a separate research DB is configured — covering `RunSQL` ops that have no `model_name` (the gap that wiped 34 GS-owned tables in the 2026-04-30 incident).

**Connection strings.** `DATABASE_URL` (default) and `RESEARCH_DATABASE_URL` / `RESEARCH_DATABASE_URL_DIRECT` (research, pooled and direct). The research URL must resolve to the `ag_research_reader` Neon role. Cross-database foreign keys are not possible and intentionally are not attempted; cross-database JOINs are also not possible (see aigranthelper #414 — `Organization.focus_areas` cross-DB M2M is being refactored).

---

## 3. Ownership

| Domain | Owner | Example tables |
|---|---|---|
| Foundations, filings, grants, people | grantspider | `foundations`, `filings`, `grants`, `people` |
| Enrichments | grantspider | `enrichments` |
| Community foundations + funds | grantspider | `community_foundations`, `cf_funds` |
| Federal / state opportunities + awards | grantspider | `gov_opportunities`, `gov_awards`, `gov_programs`, `procurement_opportunities` |
| Crawl bookkeeping | grantspider | `gov_fetch_log`, `gov_quality_rejections`, `mine_urls`, `entity_resolution_candidates`, `irs_bmf` |
| Reference / graph | grantspider | `ntee_codes`, `links` |
| Users, orgs, auth | aigranthelper | `users`, `organizations`, `programs` |
| Pipeline state | aigranthelper | `applications`, `awards`, `funder_relationships`, `foundation_notes`, `program_grant_alignments` |

**Rule.** When aigranthelper needs a new column on a grantspider-owned table, the DDL flows through grantspider as an Alembic migration. aigranthelper never writes to `research.*` and never runs `makemigrations` against research models.

**Cross-reference by value.** aigranthelper stores `foundation_id_ref` (UUID, as string) to reference grantspider foundations. No FK. Name changes and deletes on the producer side therefore propagate only when the consumer re-reads.

Where aigranthelper stores a local copy of a producer-owned field, the copy must be declared as one of two kinds:

- **Snapshot.** Captured at the moment a consumer-owned row is created, intentionally *not* tracked against the source. The copy is part of the consumer row's identity — e.g., "the name of the foundation as the user saved it into their pipeline." Current snapshots: `FunderRelationship.foundation_name`, `ProgramGrantAlignment.foundation_name`. Both are load-bearing for audit logs, admin search, and `__str__` representations across Applications, Awards, FunderContacts, and FunderProgramFits. Drift from source is expected and correct.
- **Cache.** Expected to track the source. No fields of this kind exist today. If added, list here with the refresh mechanism (reconciliation job / refresh-on-read / view-backed).

A field is never *implicitly* a cache. New denormalizations must declare which kind they are in the model's docstring or help_text at the time they are added.

---

## 4. Access Rules

**Reads.** aigranthelper reads `research.*` via Django ORM using `.using("research")`. Unmanaged mirror models live at `apps/research/models/_generated.py` plus hand-patched extensions in `apps/research/models/__init__.py`.

**Writes.** aigranthelper has **no** write path to `research.*`. If a use case requires consumer-originated signal (e.g. "user dismissed this funder"), the data lives in a new aigranthelper-owned table with a value-referenced `foundation_id_ref` — never in a grantspider table.

**Semantic and full-text search.** Query paths depend on `foundations.embedding` (pgvector) and enrichment-text indexes. These are coverage-critical and are listed in §7.

**Credentials.** The Neon role behind `RESEARCH_DATABASE_URL` is `ag_research_reader` — read-only by Neon role grant, on the grantspider-owned Neon project. This is the technical enforcement of the "no write" rule. Create a new role if a different access pattern is needed; do not promote `ag_research_reader`.

---

## 5. Freshness and Coverage SLAs

grantspider's `config/freshness_slas.yaml` defines max hours since last successful fetch per source. The user-facing freshness contract:

| Source class | Target freshness | Notes |
|---|---|---|
| Federal (SAM.gov Assistance Listings, Grants.gov) | 24h | Daily fetch; upstream publishes daily. |
| USASpending awards | 48h | Public dumps, retry on 429. |
| 360Giving (UK publishers) | 14d | Per-publisher CKAN/JSON; cadence varies. |
| ProPublica Nonprofit Explorer | 7d | Weekly IRS BMF release plus lag. |
| IRS TEOS 990-PF bulk | 30d | Monthly XML dumps. |
| State / county / metro portals | 7d default | Per-source override in the jurisdictions registry. |

**Enforcement.** `gov_fetch_log` records successful fetches; the freshness audit reports per-source staleness. Sources that exceed SLA are a *known-stale* state and must be visible to operators. That surface does not exist today — see G2 in §12.

**Coverage (contract v1).** All 50 states on the federal sources; 978 community foundations indexed; ~120K private foundations from ProPublica/IRS; selective state/county/metro coverage driven by the jurisdictions registry. Coverage gaps are tracked as issues in grantspider.

---

## 6. Quality Gates

grantspider produces nothing that has not passed through:

1. **Schema-level.** CHECK constraints (EIN format, non-negative amounts), partial unique indexes on `(data_source, source_id)`, immutable rejection log in `gov_quality_rejections`.
2. **Rule-based.** `config/quality_rules.yaml` — title length, required fields, actionability thresholds, placeholder detection.
3. **Neutral voice.** `config/neutral_voice_rules.yaml` forbids advocacy, superlatives, and first- or second-person language in enrichment output.
4. **Post-hoc audit.** `audit-quality --gate` in CI scans for HTML entities, control chars, truncation, voice drift. Breach blocks merge.
5. **Entity resolution.** Splink candidates write to `entity_resolution_candidates`. **No automatic merges.** Human review required.

Consumer assumption: any row visible to aigranthelper passed these gates at ingest. Rows that later fail a re-audit must be flagged, not silently mutated.

---

## 7. What aigranthelper Depends On (coverage-critical surface)

The features below are what the paying user sees. Breaking any of these breaks the product.

| Feature | Tables used | Critical fields |
|---|---|---|
| Foundation search | `foundations`, `enrichments`, `ntee_codes` | `name`, `state`, `city`, `asset_amount`, `foundation_code`, `accepts_unsolicited`, `grant_restrictions`, enrichment text |
| Foundation detail | `foundations`, `grants`, `enrichments`, `people` | above + `grants.recipient_ein/amount/tax_period`, `people.name/role` |
| Funder matching | `foundations`, `enrichments`, `grants` | `embedding`, enrichment types, historical-grant aggregates |
| Gov grant search | `gov_opportunities`, `gov_awards`, `gov_programs` | `title`, `cfda_numbers`, `states`, `close_date`, `status`, `recipient_name`, `amount` |
| Saved-funder deadlines | `enrichments` (type=deadlines) | parsed deadline dates from enrichment JSON |
| State landing pages (SEO) | `foundations` | `state`, top-funder ordering |

**Contract.** None of these fields may be removed, renamed, or have its meaning changed without the §8 change-management procedure. Adding fields is free.

---

## 8. Change Management

**Authoritative schema.** `grantspider/src/grantspider/models/*.py` (SQLAlchemy ORM) plus `grantspider/alembic/versions/*.py` (DDL). ADR-006 requires data migrations to use the ORM, not raw SQL.

**Consumer mirror.** `aigranthelper/apps/research/models/_generated.py` plus hand-patched `apps/research/models/__init__.py`.

### 8.1 Additive (new table, new column, new index)

- No contract action required on aigranthelper's side.
- Consumer mirror is regenerated on the next `inspectdb` run, or when a feature needs the new field.

### 8.2 Breaking (rename, remove, type change, semantic change) on any table in §7

1. **Announce before merge.** The grantspider PR opens a tracking issue in aigranthelper describing the break, the replacement, and the target cutover date.
2. **Dual-write / deprecation shim.** Keep the old column populated for at least 7 calendar days while the new column comes online.
3. **Migrate the consumer.** aigranthelper opens its own PR that moves reads to the new column.
4. **Drop only after** both PRs are merged and `_generated.py` has been regenerated on the consumer side.

For tables not in §7 (purely internal to grantspider's pipeline), no cross-repo notification is required.

### 8.3 Consumer-mirror regeneration

`_generated.py` must be regenerated after any change that touches a consumed column. Today this is manual; PR #329 was patched by hand, which is fragile.

**Required:** an aigranthelper CI job that diffs a fresh `inspectdb` of `research.*` against committed `_generated.py` and fails on drift. Tracked as G1 in §12.

---

## 9. Failure Modes and Responsibilities

| Scenario | Behavior today | Required behavior |
|---|---|---|
| `research` DB unreachable | aigranthelper catches `DatabaseError`, returns empty matches and deadlines silently | Degrade features, show a non-alarming "data refreshing" banner, log to Sentry |
| Source exceeds freshness SLA | `gov_fetch_log` shows the miss; no operator surface | Internal alert; surface last-updated-per-source in admin |
| Consumer mirror stale | Hand-patched (PR #329 precedent) | CI drift check per §8.3 |
| Enrichment past `expires_at` | Silently served | Filter at query time via DB view (§6-compliant: data preserved, not mutated) |
| Entity-resolution auto-merge | Impossible today (no code path) | Contract: never auto-merge without explicit operator action |
| Embedding stale against changed source text | Served as-is | Add `embedding_source_hash`, backfill on drift |

Items in "Required behavior" that differ from today's behavior are open gaps — see §12.

---

## 10. The Sellable Slice (internal)

> Not marketing copy. The acceptance criteria for *sellable* — what must be true for a paying SaaS user to renew.

A user pays for **access to the enriched grant-funder-award corpus, curated to a standard that free sources (grants.gov, an Instrumentl trial, hand-scraping 990-PFs) do not meet**. The sellable slice is:

1. **Funder discovery beyond keyword search.** NTEE classification, geographic filter, asset-size filter, historical-grant aggregates, the "accepts unsolicited" signal.
2. **Enrichment depth per funder.** Claude-generated guidelines, program areas, deadlines, contact info — gated by neutral-voice and quality rules, not copy-pasted marketing from funder websites.
3. **Opportunity timeliness.** Federal sources within 24h of upstream publication.
4. **Confidence signals.** EIN-verified, entity-resolution reviewed, quality-audit passed. Rows the user sees are rows grantspider stands behind.
5. **Faith-based calibration.** Delivered via the consulting layer and Claude prompt tooling. Not embedded in the raw corpus.

**Product acceptance criteria (internal):**

- A user entering a specific ask ("community foundations in SC funding hunger relief, $50K+, open deadline") must get a non-trivial result set within 3 seconds.
- Each result must include at least: funder name, asset size, NTEE, state, and either an enrichment note or a historical-grant count.
- No result may display placeholder text, voice-drift language, or a malformed EIN.
- The same user running the same search 30 days later must see *differently stale* data — evidence of fresh crawl, not an unchanged snapshot.

If any of these break, the SaaS is no longer sellable. Deployment readiness must protect them.

---

## 11. Non-Goals

- A public HTTP API for `research.*`. grantspider is not a data exchange; it is a producer for one SaaS.
- A complete field dictionary. Authoritative field-level detail stays in `grantspider/src/grantspider/models/*.py`.
- Bulk export of the corpus. The asset is competitive and is not sold in bulk.
- Cross-database foreign keys. Not possible; do not attempt.

---

## 12. Open Gaps (v1)

| ID | Gap | Owning repo | Action |
|---|---|---|---|
| G1 | Consumer-mirror drift check missing (PR #329 precedent) | aigranthelper | CI job per §8.3 |
| G2 | No operator surface for SLA-breaching sources | grantspider or oversteward | Admin panel or `/project-status` extension |
| G4 | Enrichment `expires_at` not filtered at query time | grantspider | Database view exposing only live enrichments |
| G5 | No write-back channel for user signals (dismissed / saved) | aigranthelper | New table, not a grantspider table |
| G6 | Embeddings go stale when source text changes | grantspider | Add `embedding_source_hash`; backfill on drift |
| G7 | Freshness not visible to operators | oversteward or grantspider | Dashboard surface |

Each should become an issue in its owning repo.

---

## 13. Versioning

This contract is versioned as a document. Material changes bump `v#` in the status line and are recorded in the changelog below. Non-material edits do not require a version bump.

### Changelog

- **v1.2 (2026-04-30):** Topology rewrite after the 2026-04-30 incident and cutover (aigranthelper #413, grantspider #626). Replaces "one Neon cluster, two databases" with "two Neon projects, one database each." Adds `ag_research_reader` as the named read-only role on the grantspider Neon project — the technical enforcement of §4. Documents the `RunSQL` model_name gap that triggered the wipe and the router hardening that closes it. Notes the residual cross-DB M2M issue tracked as aigranthelper #414. Router path reference updated to `apps/core/db_router.py`.
- **v1.1 (2026-04-22):** Correct snapshot-vs-cache semantics in §3. `FunderRelationship.foundation_name` and `ProgramGrantAlignment.foundation_name` are intentional snapshots (relationship-scoped name-as-saved), not caches — they do not drift, they carry identity. Retires G3 and removes the "denormalized cache drift" row from §9. Reframes G4 from "reaper" to "DB-view-based TTL filter" to preserve §6's rule that bad rows are flagged, not silently mutated.
- **v1 (2026-04-20):** Initial ratified contract.

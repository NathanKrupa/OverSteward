# CCCF (EIN 57-0793960) vs Hinchilla — what the deep pass must capture

Session 2026-09-17. Nathan's question: "Will our enrichment pass capture and
display the kind of information that they are providing? … This is what
Google is ACTUALLY USING." Answer: not the layer a grant-writer acts on.

## Findings (in-session, `grantspider db scratch` + rendered AG page)

- Money layer: ours is better (455 grants FY2023 exact match; Hinchilla's
  "$21.2M annual giving" is our `totfuncexpns`, grants to orgs is $17.3M).
- Narrative/application layer: `enrichments` 0, `foundation_programmes` 0
  (table holds `name` only, 0 rows estate-wide), `people` 0, restrictions
  structurally empty for every Form 990 filer (990-PF Part XV only).
- Cause: cohort gate `active_us_grantmaker_clause()` = `foundation_code <= 4`
  (#1729); CCCF is code 15 with `grantmaker_status='grantmaker'`.
- Rendered page defects (filed separately): "Private Foundation" label,
  "990-PF filings" heading, Giving/Grants Paid dashes (seam ignores
  `grants_to_orgs_amount`), Typical Grant dash (quartiles from loaded page).
- Feature request: sticky "On this page" rail from the section registry.

## Cohort sizing for the proposed predicate

`grantmaker_status='grantmaker' AND grant_dollars_total >= $10M` (cumulative):

| code | n | with site | site unverified | no profile | usable pages |
|---|---|---|---|---|---|
| 0 | 2597 | 2298 | 2132 | 2176 | 69140 |
| 2 | 10 | 9 | 0 | 7 | 283 |
| 3 | 171 | 130 | 13 | 146 | 15052 |
| 4 | 5132 | 3211 | 103 | 4268 | 291686 |
| 15 | 1328 | 1319 | 1318 | 802 | 74954 |
| 16 | 134 | 132 | 132 | 103 | 15565 |
| 17 | 165 | 144 | 144 | 151 | 4583 |
| 21/22 | 68 | 59 | 59 | 68 | 1277 |

On 2023 single-year giving ≥ $10M: code ≤ 4 = 2,024; code 15 = 523.
Neither reproduces §6's "1,357" — that figure's basis is unknown.

## Architect plan (Fable, 2026-09-17)


```plan
Scope
  branch: feat/deep-pass-programme-record (GS, staging) · feat/programmes-section (AG, staging)
  title:  feat(enrichment): per-programme site record + funder restrictions/contacts for the ≥$10M deep pass
  - GS: extend foundation_programmes + people + FoundationEnrichment; ProgrammeDetail schema/prompt/gates; deep-pass cohort predicate; CCCF fixtures
  - AG: foundation_programmes_v mirror, Programs partial, "doesn't fund" row, site staff block, bench fixture for the judge

Changes
  GS src/grantspider/extraction/schemas.py — FoundationEnrichment gains funding_restrictions list[str], site_contacts list[SiteContact(name,role,phone,email)], site_phone, site_address (line1/city/state/zip). New ProgrammeDetail (name, application_url, pathway, accepts_applications, amount_min/max int, match_requirement, cycle_open/cycle_close date|None, deadline_text verbatim, notification_text, eligibility, restrictions list, contact SiteContact|None, invitation_only) and ProgrammeInventory; registered in the schema map so the drain's session agents get the tool schema.
  GS config/enrichment_extraction_prompt.yaml — rubric rows for the four funder fields; version bump (stamped on runs). New config/programme_extraction_prompt.yaml; services/enrichment_prompt.py loader takes the path (already parametrised by DEFAULT_ENRICHMENT_PROMPT_PATH).
  GS models/foundation_programme.py + one Alembic migration — nullable site columns on the EXISTING table (grants.foundation_programme_id already FKs it with no ON DELETE, so a DELETE is refused; #2657's "new foundation_programs table" would fork the entity): pathway, accepts_applications, amount_min, amount_max, match_requirement, cycle_open, cycle_close, deadline_text, notification_text, eligibility, restrictions, contact_name/role/phone/email, application_url, source_url, source_captured_at, source_hash, extractor_version, retired_at. Same migration: people.source ('irs_990' default, CHECK in {irs_990,website}), people.email/phone/source_url/source_captured_at; ag_research.foundation_programmes_v (security_barrier, sentinel-filtered, retired_at IS NULL) + GRANT SELECT to ag_research_reader.
  GS models/enrichment.py — 'funding_restrictions' into ENRICHMENT_TYPES and WEBSITE_DERIVED_ENRICHMENT_TYPES (test_the_disowned_types_are_canonical already pins the pair).
  GS models/foundation.py — deep_pass_grantmaker_clause(): grantmaker_status='grantmaker' AND coalesce(grant_dollars_total,0) >= DEEP_PASS_MIN_GIVING (10_000_000). active_us_grantmaker_clause() untouched (7 callers; #1729 forward-only stays).
  GS services/enrichment_apply.py — CohortSpec.deep_pass swaps the grantmaker clause in _cohort_filters; _LIST_FIELD_TYPES += funding_restrictions; new prose gate: a "$" figure in profile_description rejects the prose (enrichment_gates.py has none today); _apply_site_contacts writes people rows source='website' (tax_period=''); site phone/address write-through blank-only (foundations.phone precedence comment, line 389) with property_lineage rows (§8.7).
  GS services/website_verification.py — unverified_cohort_stmt (line 277) gains the same deep_pass flag: CCCF has website_verified_at NULL, so without Stage 0 verification the enrichment gate (website_verified_ok_clause) never admits it.
  GS services/programme_inventory.py (new, MIDDLE) — Stage B: per-section page budget, per-page ProgrammeDetail extraction, gates (below), upsert on (foundation_id,name_normalized), retire unseen site rows (retired_at), cap 25 with a 'warning' accuracy_checks row (§8.1 vocabulary). NTEE philanthropy-code gate as #2657 states.
  GS cli — enrich-profile pull/apply --deep-pass; programmes pull/apply; dry-run manifest prints per-funder usable_page_count + code-15 count.
  GS tests — tests/fixtures/cccf/ (markdown of the B2 pages: grant-opportunities, before-you-start, contact/staff); tests/fixtures/enrichment_cohort_deep_pass.sql beside the byte-pinned default (default fixture must not change); tests/services/test_programme_inventory.py; test_enrichment_apply_site_contacts.py; tests/models/test_foundation.py clause test.
  AG apps/research/models/_programme_view.py (new mirror, own module per the gaudi-floor convention) + concrete class in models/__init__.py; _generated.py people columns via regenerate_from_lockfile after the main-SHA bump PR (I-19).
  AG apps/research/services/programmes.py — load_foundation_programme_rows → list | None (None = unreadable, [] = none), mirroring services/deadlines.load_foundation_deadline_lines; services/__init__.py get_people filters source='irs_990'; get_site_staff for source='website'.
  AG apps/research/views.py — _load_foundation_programmes via _timed_section (as line 708 does for deadlines); context keys programme_rows, site_staff. The 8-tuple bundle is untouched.
  AG apps/research/constants.py — PAGE_SLOT_PROGRAMMES, body column, decision tier, after WHAT_THEY_FUND, before ABOUT (line ~522 registry).
  AG templates/research/_detail_programmes.html (new) — one card per programme, every field self-gates, amounts as figures beside prose never in it, contact and source link per card. _detail_seeker_box.html — "Doesn't fund" row from enrichments.funding_restrictions, added to the union gate. _detail_board.html — Staff list under the board, gated on site_staff.
  AG tests/test_foundation_page_sections.py — body-order pin updated; thin bundle renders no Programs heading; programme_rows=None renders nothing. scripts/dev/bench.py — CCCF frozen seam fixture for the Gemini judge (ruling 5) before the AG PR merges.

Invariants touched
  I-4 (AG stays read-only: new view + GRANT only) · I-6 (additive seam, no §7 rename) · I-7 (ORM; view DDL via op.execute as a4e1c7f9d2b6 does) · I-19/I-20 (AG mirror waits for the GS main promote; GS lands on staging) · I-15 (tests named in the brief)

Negative fixtures
  | guard | fixture that makes it red | mutant it kills |
  |---|---|---|
  | deep-pass predicate | code-15 grantmaker, $67M, verified → selected; same row grant_dollars_total 9,999,999 → not | dropping the giving conjunct |
  | default cohort unchanged | enrichment_cohort_default.sql byte-identical with deep_pass=False | predicate leaking into the ordinary drain |
  | Stage 0 admission | CCCF-shaped row, website_verified_at NULL, deep_pass → in unverified_cohort_stmt | verification still on code≤4 |
  | amount grounding | page says "$5,000 to $25,000", extraction amount_max=250000 → rejected | grounding check skipped for numerics |
  | contact grounding | email not a substring of the source page → row dropped, reason stamped | substring check inverted |
  | date grounding | page "March 15", cycle_close 2026-03-16 → rejected, deadline_text kept | month-day token check removed |
  | retire-not-delete | pass 2 omits programme X → retired_at set, row and any grants FK survive | DELETE-based rewrite |
  | cap | 26 programme pages → 25 rows + one 'warning' accuracy_checks row | cap applied silently |
  | people provenance | site contact who is also a 990 officer → two rows, sources differ; board query excludes website | source filter dropped in get_people |
  | funding_restrictions type | apply with the type absent from ENRICHMENT_TYPES → InvalidEnrichmentType | type check bypassed |
  | phone write-through | foundations.phone non-blank → unchanged; blank → site value + lineage row | overwrite of the IRS value |
  | no $ in prose (new gate) | profile_description "awards $25,000 grants" → prose rejected, structured rows land | gate applied to the list fields instead |
  | AG fail-closed | programme_rows=None → no heading; [] → no heading; one row → heading | gate on truthiness of None |
  | AG body order | registry pin lists PROGRAMMES between what_they_fund and about | slot appended at the tail |

Red team
  applied: the predicate change at _cohort_filters alone never admits CCCF — website_verified_at is NULL and unverified_cohort_stmt uses the old clause; added Stage 0. The issue's "new foundation_programs table" forks an entity grants already FK to; extended foundation_programmes instead, and swapped wholesale rewrite (foundation_deadlines style) for upsert+retire because that FK has no ON DELETE. Numeric/contact/date fields are not covered by the prose gates (neutral voice + token overlap); each gets its own grounding gate, and the "no $ in prose" doctrine had no gate at all. Bundle-tuple growth would ripple through every 8-tuple test fixture; loaded like deadline_lines instead, which also gives the None/[] fail-closed shape #1881 established. Default cohort SQL is byte-pinned; deep pass is opt-in so the pin holds.
  rejected: a separate people_site table — AG reads the people base table directly (GS#917) and one roster with a source column is one seam change, not two. Storing restrictions as a foundations column — it would collide with the IRS grant_restrictions precedence; an enrichment type carries provenance and TTL for free. Parsing programme dates with the deterministic deadline extractor — it reads chunks, not per-programme pages; the LLM returns dates and the grounding gate polices them.

Unknowns
  Whether §6's 1,357 was measured on grant_dollars_total (cumulative) or a single-year figure — neither reproduces it (session sizing above). CCCF's NTEE T310 vs the philanthropy-code gate. The enrich-drain workflow file is not in the GS checkout.

Needs Nathan
  1. Revise the "foundation_code ≤ 4, US" budget ruling to grantmaker_status='grantmaker' AND giving ≥ $10M — the admitted code-15 count is the number to decide on.
  2. Named staff on a public page: publish personal email/phone extensions as the competitor does, or role + general inbox only. The schema captures both; the AG partial renders per his call.
```

## Filed (2026-09-17, after Nathan's rulings: cohort revision yes; staff PII = name + role + general inbox)

- GS#2657 rescope comment; child **GS#2697** (programme record, restrictions, site contacts, deep-pass cohort)
- **AG#2073** "Private Foundation" / "990-PF filings" labels
- **GS#2698** filing-history seam ignores `grants_to_orgs_amount`
- **GS#2699** 41,221 funders without distribution stats · **AG#2074** Typical Grant reads seam quartiles
- **GS#2700** address/ZIP backfill + CoF-locator kind reclassification (zero-LLM)
- **AG#2075** sticky "On this page" rail from the section registry (Gemini bench first)

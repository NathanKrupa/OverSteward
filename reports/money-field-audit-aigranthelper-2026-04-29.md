ABOUTME: Tier 4 #11 audit — checks aigranthelper money fields for cents/dollars consistency after PR #306 migrated Program to dollars.
ABOUTME: Investigation only, no code changes. Conclusion: real inconsistency exists; migration is an architectural call, not a clear-cut fix.

# Money field audit — aigranthelper

**Audited:** 2026-04-29 (overnight)
**Scope:** all `BigIntegerField` / `IntegerField` / `DecimalField` / `MoneyField` in `apps/*/models.py`
**Trigger:** PR #306 migrated `Program.annual_budget` + `funding_gap` from cents to dollars; SESSION_STATE Tier 4 #11 asked whether other money fields followed.

## Findings

### Dollars-stored (post-#306, consistent with new contract)

| Model | Field | Storage | Source |
|---|---|---|---|
| `Program` | `annual_budget` | dollars | `apps/pipeline/models.py:24` |
| `Program` | `funding_gap` | dollars | `apps/pipeline/models.py:25` |

### Cents-stored (inconsistent with #306's dollars contract)

| Model | Field | Storage | Source | Note |
|---|---|---|---|---|
| `Application` | `amount_requested` | cents | `apps/pipeline/models.py:235` | `help_text=_HELP_CENTS` |
| `Application` | `amount_awarded` | cents | `apps/pipeline/models.py:236` | `help_text="Cents. Populated on decision"` |
| `Award` | `amount_awarded` | cents | `apps/pipeline/models.py:362` | `help_text=_HELP_CENTS` |
| `Award` | `funds_received` | cents | `apps/pipeline/models.py:368` | `help_text="Running total drawn down, in cents"` |

### Non-money integer (no concern)

- `_user_rating` on Application — 1-5 ML feedback, not currency.

## Consumer surface (cents-aware code that would need touch on migration)

- `apps/pipeline/forms.py:93,173,184` — `amount_requested_dollars` form field with explicit `// 100` and `* 100` conversion shims (clearly designed around the cents storage)
- `apps/pipeline/models.py:379` — `f"${self.amount_awarded / 100:,.0f}"` display formatter on `Award.__str__`
- `apps/pipeline/services/decisions.py:154,157,160` — `_log_decision` uses a `_dollars()` helper to convert cents→dollars for activity log entries
- `apps/pipeline/views.py:973,1010` — `amount_cents` local + `_parse_award_amount` parser on award decision form submission
- `apps/ops/services.py:83-89` — `pipeline_value = sum(a.amount_requested ...)` aggregation; will need unit-context awareness if migrating

## Architectural read — this is a real call, not a clean migration

This is **not** the same kind of latent unit bug that PR #306 fixed. Both arguments are real:

**For migrating these to dollars:**

- Consistency with `Program.annual_budget` / `funding_gap` (post-#306).
- IRS data (HistoricalGrant.amount via grantspider) is dollars-native; `_score_award_size` already operates in dollars-vs-dollars after #306.
- "Mixed conventions invite future unit bugs" — already cost us one matching-engine miss.
- Variable naming convention from session state: prefer `_dollars` unless ambiguous (most foundation grants are dollar-rounded; cent precision rarely matters here).

**For keeping these in cents:**

- Cents-as-integer is the standard transactional money convention (Stripe, ledger, accounting). These ARE transactional fields — applications submitted to funders, awarded grant amounts, drawn-down funds. Different signature than budget figures.
- Migration touches a non-trivial blast radius (5 consumer files + tests + a migration). Risk-vs-reward is closer than #306's was — #306 had a confirmed matching-engine bug; these don't yet.
- The cents-aware shim layer (form `// 100` / `* 100`, `_dollars()` helper) is well-isolated. Bug surface is at the boundaries, not pervasive.
- Legal/compliance audit trails for granted money may favor cent precision when reconciling against Stripe / bank statements (if any).

## Recommendation

**Don't auto-migrate.** Decide explicitly.

If migrating: bundle into one PR similar to #306. Migration + Award.__str__ formatter + form conversion + decisions service + ops aggregation + tests. Estimate: ~150-200 LOC.

If keeping cents: add a comment to `Program.annual_budget` / `funding_gap` documenting why those two are dollars while transactional fields are cents (budgets are estimates, transactional fields are ledger). Add a CLAUDE.md / SESSION_STATE.md note about the convention so it doesn't drift.

**My read** (not binding): the cents-vs-dollars split is actually defensible — budget/projection fields in dollars (estimate-precision), transactional fields in cents (ledger-precision). Document the boundary, don't migrate. But this is your call, Nathan.

## Out of scope for this audit

- Stripe price IDs (already documented as deny-listed and stay in cents per Stripe API).
- Any future money fields not yet on `models.py`.
- Cross-repo: grantspider's HistoricalGrant.amount is documented as dollars-native; no change needed.

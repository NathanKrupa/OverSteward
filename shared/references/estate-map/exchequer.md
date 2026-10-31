<!-- Generated from estate-map.yaml by `scripts/estate_map.py render --write`. Do not edit by hand: a test compares this file with a fresh render. -->

# Estate map — exchequer

**North star.** Provide A+ grant-writing tools to the servants of the poor: the food pantries, parishes and small charities who work on shoestring budgets and are not grant experts. It is not about the money; it is about the people.

This repo's share of OverSteward's `estate-map.yaml`. A wrong row is fixed in the map, never here.

## Capabilities (`id` · status · purpose, then current → target shape)

Each current shape is its first sentence; the full measurement is in the map.

- `exchequer.counting-house` · live · Private counting-house — `exchequer pull` billing connectors, CSV ledgers, monthly close; zero LLM tokens.
  - Unclaimed stub: exchequer is not seeded in this map. → hold

## Seams

- S-6 oversteward → all repos: `registry.yaml`; `shared/` deployed to both `~/.claude` homes; the dev family by sow PRs. In OverSteward the deployed side is symlinks, elsewhere copies
- S-9 pickup repos → fiscus: `andon`-labelled issues → `shared/andon.jsonl`. **The aggregator is a stub that only echoes** (L-FI-1)
- S-14 billing APIs, GA4 → exchequer: `exchequer pull` → `ledgers/pulled_costs.csv` (Anthropic, Stripe, Neon consumption API, Railway); GA4 funnel events emitted by AG (`sign_up`, `funder_saved`, `purchase`, `lead_captured`)

## Invariants

- I-21: One git worktree per session via `scripts/dev/new-session.sh` → `session/<name>`; `guard_main_worktree.py` refuses checkout/switch in the primary tree. OverSteward links the kit from `shared/`; other repos carry copies, currently drifted (L-DEV-1) (`shared/scripts/dev/new-session.sh:44`, `tests/test_deployed_links.py`)

## Liabilities

- L-DISP-1 (exchequer; GitHub API, 2026-10-31): **exchequer** `main` has no branch protection. Every other private dispatch repo has protection with `enforce_admins`
- L-DEV-1 (oversteward; `/sync-status`; OS#572): Dev-family copies drift: `new-session.sh` is one version behind in every repo; exchequer's `guard_main_worktree.py` differs; `worktree_doctor.py` is absent in wphelper, ai-assistants, exchequer, gaudi and pre-#571 in AG, GS, fiscus
- L-FI-1 (fiscus; Fiscus `src/fiscus/andon.py:20-27`, `subjects/*/contract.yaml`): Fiscus andon aggregation is a Phase-0 stub, and the AG/dispatch subject contracts are `status: stub`; exchequer and gaudi lack the andon template
- L-EX-1 (exchequer; exchequer `src/exchequer/connectors/railway.py:2`, `src/exchequer/services/pull.py:38`): Exchequer: Railway connector live-unverified, cron unwired, `_ASSUMED_PRO_INFERENCE_COGS = 4.0` hardcoded; `expenses.csv` partly hand-seeded

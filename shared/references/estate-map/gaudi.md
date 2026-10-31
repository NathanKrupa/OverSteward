<!-- Generated from estate-map.yaml by `scripts/estate_map.py render --write`. Do not edit by hand: a test compares this file with a fresh render. -->

# Estate map — gaudi

**North star.** Provide A+ grant-writing tools to the servants of the poor: the food pantries, parishes and small charities who work on shoestring budgets and are not grant experts. It is not about the money; it is about the people.

This repo's share of OverSteward's `estate-map.yaml`. A wrong row is fixed in the map, never here.

## Capabilities (`id` · status · purpose, then current → target shape)

Each current shape is its first sentence; the full measurement is in the map.

- `gaudi.linter` · live · Architecture linter, open source (PyPI `gaudi-linter`); gates AG and OverSteward.
  - Unclaimed stub: gaudi is not seeded in this map. → hold

## Seams

- S-6 oversteward → all repos: `registry.yaml`; `shared/` deployed to both `~/.claude` homes; the dev family by sow PRs. In OverSteward the deployed side is symlinks, elsewhere copies

## Invariants

- I-21: One git worktree per session via `scripts/dev/new-session.sh` → `session/<name>`; `guard_main_worktree.py` refuses checkout/switch in the primary tree. OverSteward links the kit from `shared/`; other repos carry copies, currently drifted (L-DEV-1) (`shared/scripts/dev/new-session.sh:44`, `tests/test_deployed_links.py`)

## Liabilities

- L-DEV-1 (oversteward; `/sync-status`; OS#572): Dev-family copies drift: `new-session.sh` is one version behind in every repo; exchequer's `guard_main_worktree.py` differs; `worktree_doctor.py` is absent in wphelper, ai-assistants, exchequer, gaudi and pre-#571 in AG, GS, fiscus

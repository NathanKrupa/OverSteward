<!-- Generated from estate-map.yaml by `scripts/estate_map.py render --write`. Do not edit by hand: a test compares this file with a fresh render. -->

# Estate map — marketing-manager

**North star.** Provide A+ grant-writing tools to the servants of the poor: the food pantries, parishes and small charities who work on shoestring budgets and are not grant experts. It is not about the money; it is about the people.

This repo's share of OverSteward's `estate-map.yaml`. A wrong row is fixed in the map, never here.

## Capabilities (`id` · status · purpose, then current → target shape)

Each current shape is its first sentence; the full measurement is in the map.

- `mm.resource-outreach` · live · Resource-page outreach: monthly Brave discovery of grant-resource sites, reviewed drafts, and weekday listing-request emails.
  - Scripts and ledgers sit untracked in the primary checkout (L-MKT-1). → The pipeline in a tracked, tested home with its ledgers outside git, so a send is reviewed code (L-MKT-1).

## Seams

- S-6 oversteward → all repos: `registry.yaml`; `shared/` deployed to both `~/.claude` homes; the dev family by sow PRs. In OverSteward the deployed side is symlinks, elsewhere copies

## Invariants

- I-21: One git worktree per session via `scripts/dev/new-session.sh` → `session/<name>`; `guard_main_worktree.py` refuses checkout/switch in the primary tree. OverSteward links the kit from `shared/`; other repos carry copies, currently drifted (L-DEV-1) (`shared/scripts/dev/new-session.sh:44`, `tests/test_deployed_links.py`)

## Liabilities

- L-MKT-1 (oversteward (ops); OS#644 (open); `reports/2026-10-29-resource-page-outreach/` (untracked); `systemctl --user list-timers ag-outreach*`): The resource-page outreach pipeline, which sends live email on a weekday timer, is untracked files in the primary OverSteward checkout: no review, no tests, no history. Its user systemd units point at that path, and the laptop backups (restic and the WSL export) are its only copies
- L-DEV-1 (oversteward; `/sync-status`; OS#572): Dev-family copies drift: `new-session.sh` is one version behind in every repo; exchequer's `guard_main_worktree.py` differs; `worktree_doctor.py` is absent in wphelper, ai-assistants, exchequer, gaudi and pre-#571 in AG, GS, fiscus

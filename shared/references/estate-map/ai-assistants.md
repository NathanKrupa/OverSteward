<!-- Generated from estate-map.yaml by `scripts/estate_map.py render --write`. Do not edit by hand: a test compares this file with a fresh render. -->

# Estate map — ai-assistants

**North star.** Provide A+ grant-writing tools to the servants of the poor: the food pantries, parishes and small charities who work on shoestring budgets and are not grant experts. It is not about the money; it is about the people.

This repo's share of OverSteward's `estate-map.yaml`. A wrong row is fixed in the map, never here.

## Capabilities (`id` · status · purpose, then current → target shape)

Each current shape is its first sentence; the full measurement is in the map.

- `aa.almoner` · live · `almoner` package — content authoring, CRM, ingestion, WP integration. No CI.
  - Unclaimed stub: ai-assistants is not seeded in this map. → hold

## Seams

- S-5 wphelper → aigranthelper, ai-assistants: Connector library: AG pins it by SHA (`requirements.txt:472`) for IndexNow + GSC; ai-assistants depends on it but still duplicates WP REST/FTP (L-AA-1)
- S-6 oversteward → all repos: `registry.yaml`; `shared/` deployed to both `~/.claude` homes; the dev family by sow PRs. In OverSteward the deployed side is symlinks, elsewhere copies
- S-9 pickup repos → fiscus: `andon`-labelled issues → `shared/andon.jsonl`. **The aggregator is a stub that only echoes** (L-FI-1)

## Invariants

- I-9: wphelper is the canonical connector home; other repos import rather than duplicate. **Violated by ai-assistants** (L-AA-1) (wphelper `src/wphelper/`; memory `project_wphelper_is_connector_home`)
- I-21: One git worktree per session via `scripts/dev/new-session.sh` → `session/<name>`; `guard_main_worktree.py` refuses checkout/switch in the primary tree. OverSteward links the kit from `shared/`; other repos carry copies, currently drifted (L-DEV-1) (`shared/scripts/dev/new-session.sh:44`, `tests/test_deployed_links.py`)

## Liabilities

- L-AA-1 (ai-assistants; `src/almoner/wp/api.py` (363 lines), `src/almoner/wp/ftp.py`): ai-assistants keeps its own WP REST client and FTP module beside the wphelper dependency (I-9)
- L-DEV-1 (oversteward; `/sync-status`; OS#572): Dev-family copies drift: `new-session.sh` is one version behind in every repo; exchequer's `guard_main_worktree.py` differs; `worktree_doctor.py` is absent in wphelper, ai-assistants, exchequer, gaudi and pre-#571 in AG, GS, fiscus
- L-FI-1 (fiscus; Fiscus `src/fiscus/andon.py:20-27`, `subjects/*/contract.yaml`): Fiscus andon aggregation is a Phase-0 stub, and the AG/dispatch subject contracts are `status: stub`; exchequer and gaudi lack the andon template

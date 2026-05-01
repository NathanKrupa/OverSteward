---
last_updated: 2026-05-01
scope: aigranthelper, grantspider, wphelper, ai-assistants, oversteward, gaudi
maintenance: pull-based — update on any session that discovers staleness
read_by: scoping / planning sessions only. Read at the start of an in-session pickup if the issue may touch more than one repo or any §3 invariant.
token_budget: ~2k. If the doc grows past that, the architecture has outgrown the format — restructure rather than expand.
---

# Architecture (machine-readable state)

What has actually been built across the House of Krupa development estate. Authoritative for "what exists today, who owns it, what's known broken." Every row cites its source — if a row's source no longer exists, the row is stale and must be corrected before relying on it.

**When to read:** at the start of a scoping or planning session that may touch more than one repo, or that may affect a load-bearing invariant. For routine in-session pickup of a single issue scoped against one repo, the issue body and the per-repo doc in [`documentation/repos/`](documentation/repos/) are sufficient.

**When to update:** the session that scopes a §7-surface change updates §5 with the PR# on landing. The session that discovers a stale row corrects it before continuing.

---

## §1 Repos

| ID | Purpose | Stack | Pickup target | Soul | Local path |
|---|---|---|---|---|---|
| aigranthelper | Grant-matching SaaS — paying-user surface | Django, Railway, Neon (default DB) | yes | chestertron | `C:\Users\natha\OneDrive\Tech\Python\aigranthelper` |
| grantspider | Crawler/enrichment producer | Python, SQLAlchemy + Alembic, Neon (research DB) | yes | chestertron | `C:\Users\natha\OneDrive\Tech\Python\grantspider` |
| wphelper | WordPress client toolkit; canonical home for external connectors (WP, Kit, GA4, GSC, FTP) | Python | yes | chestertron | `C:\Users\natha\OneDrive\Tech\Python\wphelper` |
| ai-assistants | almoner package — content authoring, CRM, ingestion, WP integration | Python | yes | chestertron | see registry |
| oversteward | Governance + this document; orchestration coordination + cross-repo contracts | Python, YAML | no (governance) | chestertron | `C:\Users\natha\OneDrive\Tech\Python\Oversteward` |
| gaudi | Architecture linter; ratchet runs in issue-to-pr-workflow step 11a | Python AST, PyPI | no (open source) | chestertron | `C:\Users\natha\OneDrive\Tech\Python\Gaudi` |

Source: `registry.yaml` (`dispatch_target` flag — kept as eligibility signal for `/project-status` and `/questions`), `~/.claude/CLAUDE.md` layer map.

---

## §2 Cross-repo seams

| Producer → Consumer | What flows | Source-of-truth |
|---|---|---|
| grantspider → aigranthelper | Foundation/grant/award corpus across two Neon projects (post-2026-04-30 cutover); aigranthelper connects as `ag_research_reader` (read-only Neon role) | `documentation/data-contract-grantspider-aigranthelper.md` v1.2 |
| wphelper → ai-assistants | External connector code (WordPress REST, Kit, GA4, GSC, FTP) imported as library; ai-assistants does not duplicate connector code | memory `project_wphelper_is_connector_home` |
| oversteward → all | `registry.yaml`, `shared/` (souls + personas), `documentation/issue-to-pr-workflow.md`, `documentation/repos/*.md`, `.claude/skills/` (answer/questions/project-status skills) | `registry.yaml`, `shared/`, `documentation/`, `.claude/skills/` |

---

## §3 Load-bearing invariants

Rules that, if violated, break something. Each cites where it lives. Listed roughly by blast radius.

| # | Invariant | Cite |
|---|---|---|
| I-1 | In-session work never touches Nathan's live working tree (worktrees only); fallback to live tree on worktree failure is a fireable offense | `documentation/issue-to-pr-workflow.md` non-negotiables + steps 5-6, grantspider #426 postmortem |
| I-2 | One in-flight PR per repo at a time (serialize same-repo work; in the in-session model, parallelism comes from opening a second Claude Code window — not from spawning subagents) | `documentation/issue-to-pr-workflow.md` step 1 concurrency check |
| I-3 | Never bypass git hooks (`--no-verify`, `--admin`, `--no-gpg-sign`); never `git add -A` | workflow non-negotiables; `~/.claude/CLAUDE.md` |
| I-4 | aigranthelper has no write path to `research.*` (Neon role `ag_research_reader` on the grantspider Neon project is read-only; technical enforcement of the no-write rule). Django router additionally returns `False` from `allow_migrate` for the entire `research` label whenever a separate research DB is configured — closes the `RunSQL`/`model_name=None` gap that wiped 34 GS tables 2026-04-30 | data contract §4, aigranthelper PR #413 |
| I-5 | aigranthelper local copies of producer fields are explicitly Snapshot OR Cache, declared at definition time in docstring/help_text | data contract §3 |
| I-6 | §7 data-contract fields cannot be removed/renamed/semantically-changed without §8 dual-write procedure | data contract §7-8 |
| I-7 | grantspider uses the ORM, not raw SQL; raw SQL bypasses client-side defaults/invariants | memory `feedback_orm_only_no_raw_sql`; grantspider ADR-006 |
| I-8 | Pre-migration UPDATEs collapsing many rows to one value must audit every sibling UNIQUE (partial + full) on touched columns, not just CHECKs/FKs | memory `feedback_migration_sibling_unique_audit` |
| I-9 | wphelper is the canonical connector home; other repos import, do not duplicate connector code | memory `project_wphelper_is_connector_home` |
| I-10 | wphelper "content generation" (authoring) is forbidden; orchestrating primitives is OK | memory `project_wphelper_orchestration_ok` |
| I-11 | grantspider has no in-repo Grant DB writer; cross-repo pattern is to expose a fail-open seam, not an ingestion hook | memory `project_grantspider_no_in_repo_grant_writer` |
| I-12 | Architect decisions must address every audit finding from the agent's STOPPED_FOR_INPUT report, not just the headline question | memory `feedback_architect_decision_completeness` |
| I-13 | Tests never patch module globals (`monkeypatch.setattr("module.attr", ...)` for subprocess, HTTP, filesystem, clock, env, random) when the fix is to expose the dependency as a parameter | workflow non-negotiables; `~/.claude/shared/references/architecture-principles.md` §Dependency Seams |
| I-14 | aigranthelper work forbidden Mon-Thu except 12-1 lunch (Golden Harvest day-job boundary) | `SESSION_STATE.md`, registry note |
| I-15 | Issues touching §7 data-contract surface or the in-session workflow itself **should** name, in the issue body, the specific test that would fail if the change were wrong (norm; mechanize into workflow step 8 if violated) | this document, established 2026-04-25 |
| I-16 | CI required checks intentionally off across pickup repos (cost conservation pre-launch); not an enforcement gap | memory `project_ci_required_checks` |
| I-17 | Long-running streaming INSERTs to Neon must implement retry-with-reconnect + per-batch commit; the pooler drops mid-stream connections under sustained load | grantspider PR #464 (5 connection drops during 1.34M-row grants migration, all recovered cleanly); pattern lives in `_bulk_upsert` |

---

## §4 Known liabilities

Honest list of broken / stale / load-bearing-without-tests. Each owned by one repo. The most valuable section and the one most likely to atrophy without discipline — when in doubt, keep this section longer rather than shorter.

| ID | Liability | Owner | Tracking |
|---|---|---|---|
| G1 | Consumer-mirror drift check missing (PR #329 was hand-patched; precedent is fragile) | aigranthelper | data contract §8.3 |
| G2 | No operator surface for SLA-breaching sources | grantspider or oversteward | data contract §12 |
| G4 | Enrichment `expires_at` not filtered at query time; stale rows silently served | grantspider | data contract §12 (DB-view approach) |
| G5 | No write-back channel for user signals (dismissed/saved); needed in aigranthelper-owned table, never in research.* | aigranthelper | data contract §12 |
| G6 | Embeddings go stale when source text changes; no `embedding_source_hash` to detect drift | grantspider | data contract §12 |
| G7 | Freshness not visible to operators | oversteward or grantspider | data contract §12 |
| H1-2 | Pipeline metrics on `/project-status` (cycle time, needs-input age, PR success rate, self-critique fire rate) not yet shipped | oversteward | `MASTER_TODO.md` PR #13 |
| L-WD-1 | Windows + OneDrive worktree-husk fragility — fresh worktrees can register metadata without populating the checkout. Mitigated by workflow step 4 prune + step 6 viability probe; underlying race remains | oversteward (workflow) | `documentation/issue-to-pr-workflow.md` §"Out-of-band cleanup" + step 6 |
| L-DISP-1 | Branch-protection enforcement absent on private repos (GitHub Free tier limitation); discipline-only on 7 private repos | all pickup repos | `SESSION_STATE.md` 2026-04-06 |
| L-DISP-2 | Orphan agent branches from the retired dispatch era — ~80 on aigranthelper, ~30 on wphelper, ~5 on grantspider, all `ahead=1` or `ahead=2`. Heartbeat-pushed stubs from harness-dropped subagents (Anthropic claude-code #47931 / #47936). Not blocking; one-time triage | oversteward | `documentation/issue-to-pr-workflow.md` §"Orphan-branch sweeper" |
| L-GS-1 | Crawl graph (`mine_urls`, `mine_url_entity_links`) at 0 rows after Neon wipe; not in SQLite snapshot. Per-URL → foundation linkage from pre-wipe enrichment is gone; B2 retains markdown but with no embedded original URL (only domain recoverable from key path) | grantspider | grantspider `SESSION_STATE.md` 2026-04-27 |

---

## §5 Recent architectural moves

Rolling, capped at ~10 entries. Older moves drop off; this is the "what changed lately and why" surface, not a full history.

| PR | What changed | Why |
|---|---|---|
| aigranthelper #419 + #421 + #422 + #423 + #424 (closes #415, #420, #414, #416) | Cross-DB residual cleanup. Removed `MIRROR: default` test paperwork (separate research test DB on local Postgres); `Organization.focus_areas` swapped from cross-DB M2M to `ArrayField(TextField())` with new `NteeCatalogService`; dual-residence `ntee_codes` stub dropped from default DB; single-DB legacy fallback retired in `apps/core/db_router.py` (router has one code path); Dockerized pgvector test backend stood up (~6× faster suite). Test infra adds `pytest-timeout` (`func_only`) and `pytest-rerunfailures` | Closes the 2026-04-30 cutover. L-AG-1 (cross-DB M2M debt) and L-AG-2 (router fallback) retired; both rows removed from §4 |
| aigranthelper #413 + grantspider #626 | Research-DB cutover. Producer moved to its own Neon project; consumer connects as `ag_research_reader` (read-only role). AG router hardened: `allow_migrate` returns `False` for the entire `research` label when a separate research DB is configured (closes the `RunSQL`/`model_name=None` gap). Historical 0001-0006 research migrations neutralised to no-op markers. `crawl_queue` and `cf_scrape_log` (GS-retired) dropped from AG codegen | 2026-04-30 incident: AG's `apps/research/migrations/0001`'s `reverse_sql=DROP TABLE foundations` ran on the shared Neon DB through the router gap, deleting 34 GS-owned tables. GS data restored to a fresh dedicated Neon project from the pre-incident snapshot; AG no longer shares a Neon cluster with the producer. |
| grantspider #464 | SQLite -> Postgres recovery migration; retry-with-reconnect for Neon transient drops | Neon `research.*` was wiped earlier this month. 2.92M rows recovered (foundations/filings/grants/enrichments) from legacy SQLite; all four tables reconcile +0 OK. Surfaces I-17: streaming INSERTs to Neon must retry-on-drop. Crawl graph (mine_urls) NOT in snapshot — see L-GS-1. |
| oversteward #20 | Data contract v1.1 — snapshot/cache distinction; retire G3; reframe G4 | `FunderRelationship.foundation_name` and `ProgramGrantAlignment.foundation_name` are intentional snapshots (relationship-scoped name-as-saved), not caches; G4 reframed as DB-view TTL filter (preserves "bad rows flag, never silently mutate" rule) |
| oversteward (this PR) | Retire dispatch skill + repo-scoped subagents; pivot to in-session pickup model | Anthropic claude-code #47931 / #47936 silent-termination bug (open since 2026-04-14, no Anthropic response, ~80 orphan branches on AG); Managed Agents launched April 2026 with metered $0.08/session-hour billing — apparent strategic nudge to the metered tier. In-session work on the existing Max subscription is the cheapest reliable path. Playbook content survived the move as `documentation/issue-to-pr-workflow.md`; `<repo>-dev.md` content survived as `documentation/repos/*.md` |
| oversteward #19 | Dispatch playbook v1.6 — harden worktree isolation | grantspider #426 postmortem: agent fell back to live tree on worktree failure, contaminating Nathan's working state; non-negotiable rule + step-6 viability probe added |
| oversteward #18 | Dispatch playbook v1.4 — preflight `git worktree prune` | Windows + OneDrive husk metadata blocked fresh worktree creation |
| oversteward #17 | Add GrantSpider to AIGrantHelper data contract | Two-repo data contract crystallized as cross-repo governance artifact |
| oversteward #16 | Collapse answer loop onto GitHub issues (H1-5) | Removed `/morning-digest`, `/answer-flow`, session-start hook; question-asking now structured GH comment; stale counter ≥48h surfaced in `/project-status` metrics block |
| oversteward #15 | Dispatch kill-switch via `dispatch-paused` label | Per-repo pause without editing skill code |

---

## §6 Maintenance protocol

- **Read at:** scope/plan time. Skim §1-2 for orientation, grep §3-4 for the surface you're touching.
- **Update at:** any session that learns a row is wrong, lands a §7-surface PR, or discovers a new invariant or liability.
- **Cite or omit:** every row carries a source. If you can't cite it, it doesn't belong here — it belongs in your own session notes until it has one.
- **Token cap:** ~2k. If §3 or §4 grows past that, the architecture has outgrown the single-file format and we restructure (probably by splitting per-repo). Do not just keep appending.
- **Routine in-session pickup does not require this doc.** Single-issue work scoped against one repo reads the issue body and the per-repo doc in [`documentation/repos/`](documentation/repos/). Cross-repo or invariant-touching work is when this doc earns its read cost.

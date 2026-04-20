# Master TODO — OverSteward

**Vision:** Two-pillar steward — (1) governance sync across 14 contexts, (2) orchestration of scoped autonomous agents against four production repos.

**Workflow:** Completed tasks → TODO_COMPLETED.md | Next tasks pull from → TODO_BACKLOG.md

Plan reference: `OVERSTEWARD.md` (Phase Roadmap); full v3 history in Stewards_Ledger.

---

## Active — Horizon 1 (Integrity + Visibility, target 2 weeks)

- [ ] **H1-1** — Move dispatch target list to `registry.yaml` (`dispatch_target: true`); update `/dispatch`, `/questions`, `/morning-digest`, `/answer-flow`, `/project-status` to read from registry (PR #12)
- [ ] **H1-2** — Pipeline metrics on `/project-status` (cycle time, needs-input age, PR success rate, self-critique fire rate) + `data/pipeline_history.jsonl` daily snapshot (PR #13)
- [ ] **H1-3** — Formalize `soul_in_local` in registry schema docs; pin sow.py safety-gate design contract (PR #14)
- [ ] **H1-4** — Dispatch kill-switch: `dispatch-paused` label handling; `/dispatch` refuses paused repos (PR #15)
- [ ] **H1-5** — GH-native answer loop: build `/answer <issue>` skill; delete `/morning-digest` + `/answer-flow` + their cron schedules; archive Chestertron Inbox file; add stale-question counter to `/project-status` (PR #16)

## Standing (carried across horizons)

- [ ] **Analyst persona** — build via `/create-persona` when a real Stocks/OpportunityMiner use case lands (trigger-gated, not scheduled)
- [ ] **billions registry note** — `soul_in_local: true` design formalized in H1-3; sow.py implementation in Horizon 3

---

## Horizon 2 / Horizon 3

See TODO_BACKLOG.md.

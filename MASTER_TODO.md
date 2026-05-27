# Master TODO — OverSteward

**Vision:** Two-pillar steward — (1) governance sync across 15 contexts, (2) orchestration of in-session pickup work across five production repos (aigranthelper, grantspider, wphelper, ai-assistants, fiscus).

**Workflow:** Completed tasks → TODO_COMPLETED.md | Next tasks pull from → TODO_BACKLOG.md

Plan reference: `OVERSTEWARD.md` (Phase Roadmap); full session history in Stewards_Ledger.

---

## Active

- [ ] **PR #46 — trajectory template** (open, current branch `feat/trajectory-template`). Schema for in-session PR trajectory notes lives at `documentation/trajectories/TEMPLATE.md`; self-bootstrap note for #46 already drafted. Nathan's call whether to merge.
- [ ] **PR #33 — formally retire `/dispatch` skill** (open since 2026-05-01). De-facto retired since 2026-05-02 orphan-branch sweep — all five pickup repos work via in-session model, captured in `documentation/issue-to-pr-workflow.md` + `documentation/repos/*.md`. PR retains the source-of-truth deletion; either merge or close-and-document.
- [ ] **Issue #37 — andon issue template + label** (Fiscus channel). Copy Fiscus's canonical `andon.md` template into `.github/ISSUE_TEMPLATE/`; create matching label. Tracking-only per Nathan 2026-05-14; no auto-PR.
- [ ] **Issue #39 — drain accumulated OneDrive-locked worktree husks** (carryover-2026-05). Operator-driven; ~80 husks across grantspider's `.git/worktrees/`. Mitigated by /dispatch retirement but residue remains. Long-term mitigation (worktree-add outside OneDrive) is a separate spike.

## Standing (carried across horizons)

- [ ] **Analyst persona** — build via `/create-persona` when a real Stocks/OpportunityMiner use case lands (trigger-gated, not scheduled).
- [ ] **billions registry note** — `soul_in_local: true` design formalized in H1-3; sow.py implementation in Horizon 3.

---

## Horizon 2 / Horizon 3

See TODO_BACKLOG.md.

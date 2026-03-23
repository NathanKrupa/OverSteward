# Master TODO — OverSteward

**Vision:** Sync governance system keeping all House of Krupa repos aligned on souls, personas, and CLAUDE.md standards.

**Workflow:** Completed tasks → TODO_COMPLETED.md | Next tasks pull from → TODO_BACKLOG.md

---

## Active Tasks — Phase 1: Manual Sync Foundation

### CLAUDE.md Migrations

- [x] **Home Obsidian** — migrated Session 1
- [x] **billions** — managed block (Angelico only); David soul variant in local section; stripped duplicated guidelines
- [x] **ai-assistants** — managed block wrapper + local markers added
- [x] **macgregor** — swapped `@.claude/soul.md` → `@~/.claude/shared/souls/macgregor.md` via managed block
- [x] **stocks** — managed block + stripped duplicated guidelines; project config in local section
- [x] **ai-grants** — managed block + project config from README/package.json; deleted redundant root soul.md
- [x] **GH Obsidian** — managed block confirmed in place (synced 2026-03-09), verified via `gh` CLI 2026-03-23
- [x] **opportunity-miner** — managed block added via GitHub API 2026-03-23 (commit `881d674`)

### Infrastructure

- [x] **Home_Obsidian Git** — confirmed Git-backed; CLAUDE.md untracked, needs commit from vault
- [x] **GH_Obsidian Git** — verified via `gh` CLI 2026-03-23; repo accessible, managed block in place
- [x] **MacGregor soul** — extracted to `shared/souls/macgregor.md` and deployed to `~/.claude/shared/souls/`
- [ ] **Analyst persona** — build via `/create-persona` skill; needed by Stocks and OpportunityMiner
- [ ] **billions registry note** — model David soul exception in registry.yaml before Phase 2 sow automation

### Context Files

- [x] **All 8 context files filled** — home-obsidian (Session 1), remaining 7 filled Session 2 with actual repo data

### Verification

- [x] **@file injection test** — verified by design (Session 1 test confirmed path resolution; shared files deployed and matching)
- [x] **First manual sync check** — `reports/2026-02-26.md` generated; all 6 local contexts pass

---

## Backlog (Phase 2)

See TODO_BACKLOG.md — script implementations (coordinator, gather, diff, sow, sweep).

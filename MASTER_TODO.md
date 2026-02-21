# Master TODO — OverSteward

**Vision:** Sync governance system keeping all House of Krupa repos aligned on souls, personas, and CLAUDE.md standards.

**Workflow:** Completed tasks → TODO_COMPLETED.md | Next tasks pull from → TODO_BACKLOG.md

---

## Active Tasks — Phase 1: Manual Sync Foundation

### CLAUDE.md Migrations

- [x] **Home Obsidian** — migrated Session 1
- [ ] **GH Obsidian** — locate existing instructions, restructure as CLAUDE.md *(repo on work computer — GitHub-only)*
- [ ] **billions** — add managed block (Angelico only, NOT standard soul — David variant is intentional); keep inline soul + project config in local section
- [ ] **ai-assistants** — add managed block wrapper (already delegates to global, no duplication)
- [ ] **ai-grants** — add managed block; strip duplicated guidelines; Nathan needs to add project-specific config (currently has none)
- [ ] **macgregor** — replace `@.claude/soul.md` with `@~/.claude/shared/souls/macgregor.md` via managed block
- [ ] **stocks** — add managed block; strip duplicated guidelines; keep project config in local section
- [ ] **opportunity-miner** — add managed block *(repo on another computer — GitHub-only)*

### Infrastructure

- [x] **Home_Obsidian Git** — confirmed Git-backed; CLAUDE.md untracked, needs commit from vault
- [ ] **GH_Obsidian Git** — repo on work computer, cannot verify from here
- [x] **MacGregor soul** — extracted to `shared/souls/macgregor.md` and deployed to `~/.claude/shared/souls/`
- [ ] **Analyst persona** — build via `/create-persona` skill; needed by Stocks and OpportunityMiner

### Context Files

- [x] **All 8 context files filled** — home-obsidian (Session 1), remaining 7 filled Session 2 with actual repo data

### Verification

- [ ] **@file injection test** — confirm managed block `@file` directive is injected (not just readable) in at least one context
- [ ] **Run first manual sync check** — generate `reports/2026-02-21.md`

---

## Backlog (Phase 2)

See TODO_BACKLOG.md — script implementations (coordinator, gather, diff, sow, sweep).

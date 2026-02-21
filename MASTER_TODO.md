# Master TODO — OverSteward

**Vision:** Sync governance system keeping all House of Krupa repos aligned on souls, personas, and CLAUDE.md standards.

**Workflow:** Completed tasks → TODO_COMPLETED.md | Next tasks pull from → TODO_BACKLOG.md

---

## Active Tasks — Phase 1: Manual Sync Foundation

### CLAUDE.md Migrations

- [ ] **GH Obsidian** — locate existing instructions file, restructure as `CLAUDE.md` at vault root with Oversteward managed block + local section; fill `contexts/gh-obsidian.md`
- [ ] **billions** — audit existing CLAUDE.md (if any); ensure managed block + Angelico always-on config; fill `contexts/billions.md`
- [ ] **ai-assistants** — audit existing CLAUDE.md; ensure managed block + Angelico available config; fill `contexts/ai-assistants.md`
- [ ] **ai-grants** — audit existing CLAUDE.md; ensure managed block + Angelico available config; fill `contexts/ai-grants.md`
- [ ] **macgregor** — audit existing CLAUDE.md; soul-protection enforcement; fill `contexts/macgregor.md`
- [ ] **stocks** — audit existing CLAUDE.md; ensure managed block + analyst available config; fill `contexts/stocks.md`
- [ ] **opportunity-miner** — audit existing CLAUDE.md; ensure managed block + analyst available config; fill `contexts/opportunity-miner.md`

### Infrastructure

- [ ] **Home_Obsidian Git** — confirm vault is Git-backed and pushed to `NathanKrupa/Home_Obsidian`; add `.gitignore` if missing
- [ ] **GH_Obsidian Git** — confirm vault is Git-backed and pushed to `NathanKrupa/GH_Obsidian`; add `.gitignore` if missing
- [ ] **MacGregor soul** — extract from MacGregor repo → `shared/souls/macgregor.md`; required before MacGregor sync can proceed
- [ ] **Analyst persona** — build via `/create-persona` skill; needed by Stocks and OpportunityMiner

### Verification

- [ ] **@file injection test** — confirm managed block `@file` directive is injected (not just readable) in at least one context; ask Claude to describe itself unprompted
- [ ] **Run first manual sync check** — follow sync instructions in CLAUDE.md; generate `reports/2026-02-20.md`

---

## Backlog (Phase 2)

See TODO_BACKLOG.md — script implementations (coordinator, gather, diff, sow, sweep).

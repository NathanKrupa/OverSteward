---
session_date: 2026-03-30
status: complete
---

## Completed This Session

**Session 7 — Architecture standard rollout across all projects**

### Architecture Principles Deployment
Reviewed the new three-layer architecture standard created in ai-assistants (Architecture 90 curriculum, `documentation/fluency/ARCHITECTURE_90.md` and `documentation/architecture/LAYERS.md`). The portable reference at `~/.claude/shared/references/architecture-principles.md` was already in place.

Implemented architecture sections with project-specific layer maps in three projects:

1. **Oversteward** (`1636121`) — scripts as outer, orchestration logic (Phase 2 stubs) as middle, registry/contexts/shared as inner. Noted that Phase 2 business logic should extract to `src/oversteward/`.
2. **ai-grants** (`2eba57a`) — Vercel serverless + frontend as outer, sync/analysis scripts as middle, Todoist API + data store as inner.
3. **aigranthelper** (`3bb7739`) — Django views/commands/templates as outer, `services.py` as middle, models/constants/config as inner. References both shared principles and project's own `SERVICE_LAYER_GUIDE.md`.

ai-assistants already had this in place — all four repos are now aligned.

### Tool Registry
Regenerated `data/tool_registry.md` (6 tools).

## Remaining Phase 1

- [ ] **Analyst persona** — build via `/create-persona`; needed by Stocks and OpportunityMiner
- [ ] **billions registry note** — model David soul exception before Phase 2 sow automation

## Phase 1 Progress: ~97%

All CLAUDE.md migrations complete. Architecture standard deployed. Two infrastructure items remain.

## Gotchas

1. **billions soul** — `soul_in_local: true` in registry. Managed block = Angelico only
2. MacGregor is soul-protected — never deploy Chestertron there
3. **gh CLI path** — `/c/Program Files/GitHub CLI/gh.exe` (not on PATH in bash sandbox)
4. **aigranthelper working hours** — forbidden Mon-Thu except 12-1 lunch (Golden Harvest boundary)
5. **OpportunityMiner CLAUDE.md** — managed block trimmed local section to core rules only

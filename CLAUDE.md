<!-- [oversteward:managed | synced: 2026-02-20] -->
@~/.claude/shared/souls/chestertron.md
<!-- [oversteward:managed:end] -->

---

# Working Guidelines

Core rules: `~/.claude/CLAUDE.md`

---

# Project-Specific Configuration

<!-- [oversteward:local] -->

## Python Environment

**ALWAYS use the `Oversteward` conda environment** for running Python commands:
```bash
conda run -n Oversteward python <script>
conda run -n Oversteward python -m <module>
```

Do NOT use the base conda environment.

## Key Components

- **registry.yaml** — manifest of all managed contexts (soul, personas, sync behavior)
- **shared/** — canonical soul and persona source files (deploy to `~/.claude/shared/`)
- **contexts/** — per-context local override instructions (one file per managed repo)
- **scripts/** — coordinator, gather, diff, sow, sweep (Phase 2)
- **.claude/skills/create-persona.md** — scaffold and deploy new personas

## Key Files

- **Spec:** `OVERSTEWARD.md` (architecture and all design decisions)
- **Ledger:** `Stewards_Ledger.md` (project status and session log)
- **Todo:** `MASTER_TODO.md` (active) + `TODO_BACKLOG.md` (queued) + `TODO_COMPLETED.md` (archive)
- **Session:** `SESSION_STATE.md` (handoff between sessions)

## Sync Instructions (Phase 1 — Manual)

When Nathan asks for a sync check:
1. Read `registry.yaml` for the current context list
2. Sync `shared/` → `~/.claude/shared/` (copy files)
3. For each context (skip `skip_sow: true`): check whether the managed block matches what registry specifies
4. Generate a report in `reports/YYYY-MM-DD.md`
5. Present proposed changes; wait for approval before running sow.py

<!-- [oversteward:local:end] -->

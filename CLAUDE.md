<!-- [oversteward:managed | synced: 2026-03-09] -->
@~/.claude/shared/souls/chestertron.md

At session start, check `~/.claude/shared/inbox.md` for updates. If entries exist, review them and apply any relevant changes, then clear the file.
<!-- [oversteward:managed:end] -->

---

# Working Guidelines

Core rules: `~/.claude/CLAUDE.md`

---

# Project-Specific Configuration

<!-- [oversteward:local] -->

## Python Environment

**Use the project venv** (uv-managed) for running Python commands:
```bash
uv run python <script>
uv run python -m <module>
uv run pytest
```

`uv` auto-creates `.venv/` from `pyproject.toml` on first invocation; subsequent `uv run` calls implicitly activate it. No need to `source .venv/bin/activate` manually.

Bootstrap on a fresh checkout:
```bash
uv sync --extra dev
```

## Architecture

Principles: `@~/.claude/shared/references/architecture-principles.md`

**Layer map for this project:**
- **OUTER:** `scripts/` (coordinator, gather, diff, sow, sweep), `.claude/skills/`
- **MIDDLE:** Orchestration logic within scripts (Phase 2 — currently stubs). As scripts grow beyond stubs, extract services to `src/oversteward/`
- **INNER:** `registry.yaml` (config), `contexts/` (per-repo instructions), `shared/` (canonical source files)

Oversteward is currently a config-management project in Phase 1 (manual sync). When Phase 2 scripts are implemented, business logic (diff analysis, conflict resolution, sow decisions) belongs in a middle-layer service, not in the scripts themselves.

## Key Components

- **registry.yaml** — manifest of all managed contexts (soul, personas, sync behavior)
- **shared/** — canonical soul and persona source files (deploy to `~/.claude/shared/`)
- **contexts/** — per-context local override instructions (one file per managed repo)
- **scripts/** — coordinator, gather, diff, sow, sweep (Phase 2)
- **.claude/skills/create-persona.md** — scaffold and deploy new personas

## Key Files

- **Architecture state:** `architecture.md` — machine-readable snapshot of repos, cross-repo seams, load-bearing invariants, known liabilities, recent moves. **Read at scope/plan time** when a task may touch more than one repo or any §3 invariant. If a row is wrong, fix it before continuing. Dispatch agents do NOT read this — it's a scoping-time tool.
- **Spec:** `OVERSTEWARD.md` (architecture and all design decisions)
- **Ledger:** `Stewards_Ledger.md` (project status and session log)
- **Todo:** `MASTER_TODO.md` (active) + `TODO_BACKLOG.md` (queued) + `TODO_COMPLETED.md` (archive)
- **Session:** `SESSION_STATE.md` (handoff between sessions)

## Sync Instructions (Phase 1 — Manual)

When Nathan asks for a sync check:
1. Read `registry.yaml` for the current context list
2. Deploy `shared/` to **both** Claude home directories:
   - Windows: `C:\Users\natha\.claude\shared\`
   - WSL2: `/home/natha/.claude/shared/` (via `\\wsl.localhost\Ubuntu-24.04\home\natha\.claude\shared\` or `wsl --exec bash -c "cp ..."`)
   Both must stay in lockstep — repos on either filesystem resolve `@~/.claude/shared/...` against their own home. Skipping the WSL mirror silently breaks AG/GS (and any future WSL repo).
3. For each context (skip `skip_sow: true`): check whether the managed block matches what registry specifies
4. Generate a report in `reports/YYYY-MM-DD.md`
5. Present proposed changes; wait for approval before running sow.py

<!-- [oversteward:local:end] -->

---
name: sync-status
description: "Show governance drift across every registry.yaml context: CLAUDE.md managed-block presence, soul references, the canonical shared/scripts/dev/ byte-copy family checked member-by-member against each repo's origin ref (present-identical / drifted / absent / absent-but-doctrine-referenced), .gitleaksignore baseline presence, dual-target ~/.claude/shared deploy parity (WSL + Windows), .claude/settings.json variance, and tracking-doc freshness (SESSION_STATE vs last merge). Read-only — reports drift, never writes. Use when Nathan asks for \"sync status\", \"sync check\", \"governance drift\", \"are the repos in lockstep\", or runs /sync-status."
---

# /sync-status — governance drift report

Governance's `/project-status`: one read-only report answering "is the estate in
lockstep with the registry?" All comparison logic lives in `src/oversteward/`
(gather + diff services); the script is a thin wrapper.

## Invocation

```
/sync-status
```

No arguments.

## What the skill does

### 1. Run the drift report

```bash
uv run python scripts/diff.py
```

- Runs from the Oversteward repo root (or a session worktree — use
  `.venv/bin/python` there).
- Read-only: pure file reads + one local `git log` for the freshness check. No
  network, no writes.
- Exit 0 = lockstep; exit 1 = drift found (expected most runs; not an error).
- `--json` emits the structured findings list instead of the text report.

### 2. Present the report

Relay the DRIFT section grouped by surface, worst first:

- **shared-deploy:wsl / shared-deploy:windows** — canonical `shared/` vs the two
  deployed `~/.claude/shared/` homes. These break `@~/.claude/shared/...`
  resolution silently; lead with them.
- **managed-block / soul** — contexts whose CLAUDE.md lacks the
  `[oversteward:managed]` block or references the wrong soul.
- **canonical-family** — members of `shared/scripts/dev/` that are drifted, or
  absent while the repo's CLAUDE.md tells agents to use them; read from
  `origin/<branch>`, so the finding is about what the repo actually ships.
  `--family` prints the full matrix.
- **tracking** — SESSION_STATE.md older than the last merge to master.

INFO findings (unreachable contexts, settings variance, target-only files) go
in a short footnote, not the headline.

### 3. If Nathan asked for a formal sync check

Save the report to `reports/YYYY-MM-DD.md` (Phase 1 protocol), then present
proposed remediations and **wait for approval** — fixing drift is sow's job
and every write needs Nathan's sign-off. This skill itself never remediates.
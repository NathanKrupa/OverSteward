---
name: sync-status
description: "Show governance drift across every registry.yaml context: CLAUDE.md managed-block presence, soul references, the canonical shared/scripts/dev/ byte-copy family checked member-by-member against each repo's origin ref (present-identical / drifted / absent / absent-but-doctrine-referenced), hook registration on each origin ref (registered / registered-absent / present-unregistered), .gitleaksignore baseline presence, dual-target ~/.claude/shared deploy parity (WSL + Windows), .claude/settings.json variance, and tracking-doc freshness (SESSION_STATE vs last merge). Read-only — reports drift, never writes. Use when Nathan asks for \"sync status\", \"sync check\", \"governance drift\", \"are the repos in lockstep\", or runs /sync-status."
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
- Read-only: file reads, one local `git log` for the freshness check, and one
  `git fetch origin <branch>` per managed repo (refs only, never a working tree)
  unless `--no-fetch`, which reads the local origin refs as they stand. No writes.
- Exit 0 = lockstep; exit 1 = drift found (expected most runs; not an error);
  exit 2 = something could not be read (the `COULD NOT READ` group). 2 outranks 1,
  and "In lockstep" never prints while anything went unread.
- `--json` emits the structured findings list instead of the text report.
- `--family` prints the canonical-family matrix; `--hooks` prints the hook
  registration matrix (registered against present per repo, one line per script).

### 2. Present the report

Relay the COULD NOT READ section first: each line is a repo nothing was measured
in, never a clean one. Then the DRIFT section grouped by surface, worst first:

- **hook-registration `missing` (registered-absent)** — a hook command in
  `.claude/settings.json` or an agent card's frontmatter names a script that is
  not a file at `origin/<branch>`. The interpreter exits 2 on a script it cannot
  open, and 2 is the code the guards return to refuse, so every matching tool
  call in a session launched from that tree is refused, the repair included.
  Lead with it.
- **hook-registration `drift` (present-unregistered)** — a `.claude/hooks/*.py`
  file nothing registers: it reads as coverage and runs on nothing. A command
  registers a script only as `$CLAUDE_PROJECT_DIR/.claude/hooks/<name>.py`;
  any other mention of `.claude/hooks/` is an INFO line and registers nothing.
- **shared-deploy:wsl / shared-deploy:windows** — canonical `shared/` vs the two
  deployed `~/.claude/shared/` homes. These break `@~/.claude/shared/...`
  resolution silently; lead with them.
- **managed-block / soul / reference** — contexts whose CLAUDE.md lacks the
  `[oversteward:managed]` block, references the wrong soul, or lacks an
  `@~/.claude/shared/references/<path>` line its registry
  `references_always_on` declares. An estate-map slice reaches its repo's
  sessions only once that line is added to the block by hand; until then this
  finding is the record that it has not.
- **canonical-family** — members of `shared/scripts/dev/` that are drifted, or
  absent while the repo's CLAUDE.md tells agents to use them; read from
  `origin/<branch>`, so the finding is about what the repo actually ships.
  `--family` prints the full matrix.
- **tracking** — SESSION_STATE.md older than the last merge to master.

INFO findings (unreachable contexts, settings variance, target-only files, the
hook audit's count of contexts read, scripts present and registrations) go in a
short footnote, not the headline.

### 3. If Nathan asked for a formal sync check

Save the report to `reports/YYYY-MM-DD.md` (Phase 1 protocol), then present
proposed remediations and **wait for approval** — fixing drift is sow's job
and every write needs Nathan's sign-off. This skill itself never remediates.
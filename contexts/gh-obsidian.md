ABOUTME: Context-specific instructions for the GH (Golden Harvest) Obsidian vault.
ABOUTME: Work vault — fundraising, grants, donor relations, and professional writing.

# GH Obsidian Context

## Purpose
Work knowledge management — fundraising strategy, grant research, donor notes, campaign planning for Golden Harvest Food Bank.

## Personas Available
- Chestertron (soul)

## Platform
- Plugin: Claudian (v1.3.60) — embeds Claude Code in Obsidian
- System prompt: `.claude/instructions.md` (not CLAUDE.md)
- Skills format: JSON (`.claude/skills/*.json`)
- Settings: `.claude/claudian-settings.json`

## Local Path
GitHub-backed: `https://github.com/NathanKrupa/GH_Obsidian.git` — located on work computer (GHFB086).

## CLAUDE.md State
Managed block added to `.claude/instructions.md` on 2026-03-09. Existing local instructions preserved in `[oversteward:local]` block. Soul loaded via `@~/.claude/shared/souls/chestertron.md`.

## Deployed Skills
- `create-todoist-task.json` — task creation via `.todoist-create.sh` wrapper
- `complete-todoist-task.json` — task completion via `.todoist-complete.sh` wrapper

## Notes
- This vault handles confidential Golden Harvest organizational data
- Home Obsidian context explicitly redirects GH-specific work here
- Has "Principle of Discretion" — redirects personal topics to Home vault
- Credentials stored in `.claude/credentials` (gitignored)
- `@file` resolution in Claudian unverified — needs testing on work machine

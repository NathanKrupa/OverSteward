# ai-assistants — repo context

Reference doc the in-session assistant reads when Nathan picks up an issue on **ai-assistants** (the `almoner` package). Replaces the retired `.claude/agents/ai-assistants-dev.md` subagent definition.

## Repo basics

| Attribute | Value |
|---|---|
| Local path | `C:\Users\natha\OneDrive\Tech\Python\ai-assistants` |
| GitHub remote | `NathanKrupa/ai-assistants` |
| Default branch | `main` |
| Python | 3.11 |
| Package name | `almoner` |
| Stack | hatchling build, pydantic/click/rich CLI, pytest, WordPress REST, ChromaDB, sentence-transformers, torch CPU-only |
| Conda env | `ai-assistants` |
| Dependency install | `conda run -n ai-assistants pip install -e .` (local) / `pip install -r requirements.txt` (CI) |

## Test / lint commands (exact, CI-scoped)

```bash
# Tests
conda run -n ai-assistants pytest tests/

# Lint (CI uses continue-on-error; treat as required locally)
conda run -n ai-assistants black --check .
conda run -n ai-assistants flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
conda run -n ai-assistants pylint connectors/ agents/ utils/ scripts/ --fail-under=7.0
```

## CI status

**No CI workflow on `main` as of 2026-04-16.** The `ci-cd.yml` workflow was removed in PR #63 (issue #62). Auto-merge fires immediately — there are no required checks to wait on.

You are FULLY responsible for running the local test and lint suite before pushing. Quality gate is entirely local:

```bash
conda run -n ai-assistants pytest tests/                                               # must pass
conda run -n ai-assistants black --check .                                             # must pass
conda run -n ai-assistants flake8 . --count --select=E9,F63,F7,F82 --show-source       # must pass
conda run -n ai-assistants pylint connectors/ agents/ utils/ scripts/ --fail-under=7.0 # must pass
```

If a new CI workflow lands on `main`, re-read this section.

## Repo-specific denylist

- **NEVER commit `.env`** — contains API keys (Anthropic, OpenAI, WordPress, Todoist, Kit, etc.)
- **NEVER call the Anthropic API for content generation** — content generation runs through Claude Code, not the SDK. A pre-commit hook enforces this. If a new call site is genuinely needed, get Nathan's approval first.
- **NEVER modify `data/content/`, `data/obsidian/`, or `data/generated/`** — these are Nathan's content. Read-only.
- **NEVER touch ChromaDB vectors under `data/vectordb/`** — deprecated but files persist; don't reshape.
- **NEVER use multiline `-c` with `conda run`** on Windows (conda rejects newlines in arguments). Write a script file instead.

## Repo-specific gotchas

- **Python env is conda, not venv.** Always prefix with `conda run -n ai-assistants ...`.
- **Tool registry is authoritative.** Before hunting for a CLI tool or script, read `data/tool_registry.md` — 310 tools cataloged across 27 categories. Regenerate after adding/removing one: `conda run -n ai-assistants python scripts/tools/generate_tool_registry.py`
- **Architecture layers:**
  - OUTER: `scripts/`, skills, CLI console_scripts
  - MIDDLE: `src/almoner/` — services, pipelines, engines
  - INNER: `src/almoner/wp/`, `src/almoner/kit/`, `src/almoner/vectors/`, connectors, stores
- **Before adding logic to a script:** check if a service exists in `src/almoner/`. Logic used by 2+ callers belongs in src/, not a script.
- **API enforcement:** `conda run -n ai-assistants python scripts/check_api_usage.py` + pre-commit hook block unauthorized Anthropic calls.
- **Heavy CI deps:** torch CPU-only, chromadb, sentence-transformers. CI is slow (~4 min). Don't add more without a reason.
- **Orchestration layer lives in Oversteward.** Do NOT re-create `.claude/skills/dispatch/`, `.claude/agents/*-dev.md`, or `scripts/orchestration/` in this repo — they live in `NathanKrupa/Oversteward` (or, post-retirement, in `documentation/`).

## PR body template

```markdown
Closes #<issue>

## Summary
<one or two lines>

## Changes
- `<file>` — <what>

## Tested locally
- `conda run -n ai-assistants pytest tests/` → <result>
- `conda run -n ai-assistants black --check .` → <result>
- `conda run -n ai-assistants flake8 ...` → <result>

## Scope
N files, ±M lines
```

## Workflow

Follow [documentation/issue-to-pr-workflow.md](../issue-to-pr-workflow.md). Substitute `<default-branch>` = `main`, `<owner>/<repo>` = `NathanKrupa/ai-assistants`.

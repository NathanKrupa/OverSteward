# grantspider — repo context

Reference doc the in-session assistant reads when Nathan picks up an issue on **grantspider**. Replaces the retired `.claude/agents/grantspider-dev.md` subagent definition.

## Repo basics

| Attribute | Value |
|---|---|
| Local path | `C:\Users\natha\OneDrive\Tech\Python\grantspider` |
| GitHub remote | `NathanKrupa/grantspider` |
| **Default branch** | **`master`** (not main — be careful) |
| Python | 3.14 (check `pyproject.toml` for current) |
| Dependency install | `pip install -e ".[dev]"` |
| Venv location | `.venv\Scripts\python` |

## Test / lint / security commands (exact, CI-scoped)

```bash
# Tests (canary baseline: 722 passed in ~80s)
.venv\Scripts\python -m pytest

# Lint (MUST be scoped to src/ tests/ — matches CI; the whole repo has drift)
ruff check src/ tests/
ruff format --check src/ tests/

# Security
bandit -r src/
```

## CI check names

Currently: `test` (single job). Post-#161: `lint`, `test`, `security` (lowercase).

## Repo-specific denylist

- **Never** modify `grant_studio/research/neon_store.py` schema without explicit OK — it writes to production Neon
- **Never** modify the quality gate logic in `src/grantspider/...` that rejects bad records — it's working as intended
- **Never** disable robots.txt compliance (if/when added) without justification
- **Never** commit `.env` or `NEON_DATABASE_URL` values
- **Never** modify tests marked `@pytest.mark.integration` without running them locally with Neon access first

## Repo-specific gotchas

- **Branch is `master` not `main`.** Every git command referencing the default branch uses `master`.
- **Ruff check has baseline drift** if you scope to the whole repo. ALWAYS scope to `src/ tests/` (matches CI).
- **No raw SQL in app code.** Use the ORM. Raw SQL bypasses client-side defaults/invariants. Exceptions need a one-line justification.
- **Services must be Dagster-callable:** typed config in, structured result out, injected deps, no `click`/`print`/`sys.exit` in service code (see `grantspider/CLAUDE.md`).
- **Neon integration tests are skipped in CI** (no `NEON_DATABASE_URL` secret). If your change depends on schema, flag it in the PR body.
- **LLM provider tests are mock-only.** If you change `DEFAULT_MODEL` anywhere, add a real-API check or flag it explicitly. Canary for this class of bug is aigranthelper issue #141.
- **Coverage gate:** `--cov-fail-under=50` currently. Don't lower it. Raise only if the issue specifically asks.
- **Fixtures directory `tests/connectors/fixtures/`** currently has exactly one HTML file. Don't assume rich fixture coverage.
- **Research-DB topology (post-2026-04-30 cutover):** GrantSpider lives on its own Neon project; aigranthelper connects as `ag_research_reader` (read-only). `ntee_codes` is GrantSpider-Alembic-owned, seeded from `NTEE_SEED`. See [data-contract-grantspider-aigranthelper.md](../data-contract-grantspider-aigranthelper.md) v1.2.

## PR body template

```markdown
Closes #<issue>

## Summary
<one or two lines>

## Changes
- `<file>` — <what>
- `<file>` — <what>

## Tested locally
- `pytest` → <X/Y passed>
- `ruff check src/ tests/` → <result>
- `bandit -r src/` → <result>
- <any CLI sanity check, e.g. `grantspider gov sync-state NY --help`>

## Scope
N files, ±M lines
```

## Workflow

Follow [documentation/issue-to-pr-workflow.md](../issue-to-pr-workflow.md). Substitute `<default-branch>` = `master`, `<owner>/<repo>` = `NathanKrupa/grantspider`.

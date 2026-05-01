# aigranthelper — repo context

Reference doc the in-session assistant reads when Nathan picks up an issue on **aigranthelper**. Replaces the retired `.claude/agents/aigranthelper-dev.md` subagent definition.

**⚠️ This is a paid SaaS with real users and real money flows. Mistakes ship at 4× speed under auto-merge. Be precise.**

## Repo basics

| Attribute | Value |
|---|---|
| Local path | `C:\Users\natha\OneDrive\Tech\Python\aigranthelper` |
| GitHub remote | `NathanKrupa/aigranthelper` |
| Default branch | `main` |
| Python | 3.14 (matches `requires-python = ">=3.14"` in `pyproject.toml`) |
| Stack | Django 6.0, HTMX, Tailwind, Neon Postgres (two-Neon-project topology), Stripe, Resend, Anthropic/Gemini/OpenAI |
| Dependency install | `pip install -e ".[dev]"` |
| Venv location | `.venv\Scripts\python` |

## Test / lint / security commands (exact, CI-scoped)

```bash
# Tests (canary baseline: ~1,518 passed)
.venv\Scripts\python -m pytest

# Lint (ruff + format)
ruff check apps/ config/ tests/
ruff format --check apps/ config/ tests/

# Security
bandit -r apps/ config/
pip-audit
```

## CI check names (case-sensitive — this matters)

- **`Lint`** (capitalized) — required
- **`Test`** (capitalized) — required
- **`Security`** (post #144) — required after merge

Branch protection uses the capitalized job names. If you create new jobs, match the casing.

## Repo-specific denylist

- **NEVER modify Stripe price IDs** in `apps/billing/` without explicit OK
- **NEVER modify auth/magic-link flow** (`apps/accounts/`) without explicit OK — broken auth = locked-out paying customers
- **NEVER touch `apps/studio/llm.py` `DEFAULT_MODEL`** values without matching the identifier allowlist test in `tests/test_model_identifiers.py` (learned from #141)
- **NEVER run `makemigrations` or `migrate`** as part of a routine change. Schema changes are explicitly approved only.
- **NEVER modify the `research` schema** migration guard (`tests/test_migration_guard.py`) — it prevents Django from mutating GrantSpider-owned tables
- **NEVER commit `.env`, `local_settings.py`, `db.sqlite3` changes**
- **NEVER change `continue-on-error`** on CI jobs without explicit OK
- **NEVER disable `enforce_admins`** or bypass branch protection

## Repo-specific gotchas

- **`docs/PROJECT_STATUS.md` is often modified uncommitted on main.** The worktree-isolation pattern in [issue-to-pr-workflow.md](../issue-to-pr-workflow.md) handles this — work in the temp worktree, leave Nathan's checkout alone.
- **Two DB schemas** — `default` (Django-owned, safe to migrate) and `research` (read-only, GrantSpider-owned, migrations forbidden). Never write migrations that target `research`.
- **Stripe tests are fully mocked.** A wrong price ID passes unit tests. Adding real Stripe tests needs secrets in CI.
- **Email provider is Resend via django-anymail.** `RESEND_API_KEY` env var is correct — don't invent variations.
- **Anthropic model IDs** must match `KNOWN_GOOD_IDENTIFIERS` in `tests/test_model_identifiers.py`. If you need a new model, update both the code and the allowlist in the same PR.
- **Test DB:** the repo spins a real `pgvector/pgvector:pg16` in CI. Locally your `.venv\Scripts\python -m pytest` runs against whatever your local DB config points at.

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
- `ruff check apps/ config/ tests/` → <result>
- `ruff format --check apps/ config/ tests/` → <result>
- <if LLM touched: mention identifier allowlist test passed>

## Scope
N files, ±M lines

## Risk notes
<anything that touches billing, auth, LLM, migrations, or external APIs>
```

## Workflow

Follow [documentation/issue-to-pr-workflow.md](../issue-to-pr-workflow.md). Substitute `<default-branch>` = `main`, `<owner>/<repo>` = `NathanKrupa/aigranthelper`.

# wphelper — repo context

Reference doc the in-session assistant reads when Nathan picks up an issue on **wphelper**. Replaces the retired `.claude/agents/wphelper-dev.md` subagent definition.

## Repo basics

| Attribute | Value |
|---|---|
| Local path | `C:\Users\natha\OneDrive\Tech\Python\wphelper` |
| GitHub remote | `NathanKrupa/wphelper` |
| Default branch | `main` |
| Python | 3.14 (house standard; wphelper `pyproject.toml` still declares `>=3.11` library support — run dev/tests against 3.14) |
| Stack | Python library + CLI (`wphelper` entry point), `requests`, `paramiko` (sftp), `bandit`, `ruff` |
| Dependency install | `pip install -e ".[dev,sftp]"` |

## Test / lint / security commands (exact, CI-scoped)

```bash
# Tests (baseline: 129 passed in ~1s)
pytest

# Lint
ruff check src/ tests/
ruff format --check src/ tests/

# Security (pyproject.toml has skips = ["B101", "B321", "B402"] — FTP module intentional)
bandit -r src/ -c pyproject.toml
```

## CI check names (case-sensitive, all lowercase)

- **`lint`** — required
- **`test`** — required
- **`security`** — required

All three must pass for auto-merge.

## Repo-specific denylist

- **NEVER commit `.env`, `.env.ftp`, `.env.wp`, or any FTP/WordPress credentials**
- **NEVER disable bandit B321/B402/B101** beyond the existing skips — those three are intentional for the FTP module
- **NEVER modify `src/wphelper/ftp.py` FTP patterns** without considering the SFTP equivalents in parallel — the module supports both
- **NEVER push live WordPress content** from this repo's code — that's a consumer-side concern
- **NEVER change Rank Math meta key names** (e.g. `almoner_faq_schema`) — they map to the mu-plugin on the live site

## Repo-specific gotchas

- **wphelper is the canonical home for external connectors** (WP, Kit, GA4, GSC, FTP). Other repos import from here.
- **Doctrine:** "content generation" = authoring (forbidden); orchestrating primitives = OK.
- **FTP module is intentional.** The repo supports FTP for users with only cPanel. Bandit would flag it without the skips in pyproject.toml.
- **Baseline is clean (#40 landed).** If you see lint/format drift on main, STOP and ask — something regressed.
- **Rank Math REST meta** relies on a mu-plugin (`almoner-rankmath-rest-meta.php`) on the target WordPress site. If your change touches Rank Math paths, note that the consumer needs the mu-plugin installed.
- **`tests/test_api.py` is thin** (27 lines). The REST client has light coverage. If you touch `api.py`, expect to add tests.
- **No live WordPress smoke tests yet.** Unit tests are in-memory (FakeClient, FakeFTP patterns).

## PR body template

```markdown
Closes #<issue>

## Summary
<one or two lines>

## Changes
- `<file>` — <what>
- `<file>` — <what>

## Tested locally
- `pytest` → <X/129 passed>
- `ruff check src/ tests/` → <result>
- `ruff format --check src/ tests/` → <result>
- `bandit -r src/ -c pyproject.toml` → <result>

## Scope
N files, ±M lines
```

## Workflow

Follow [documentation/issue-to-pr-workflow.md](../issue-to-pr-workflow.md). Substitute `<default-branch>` = `main`, `<owner>/<repo>` = `NathanKrupa/wphelper`.

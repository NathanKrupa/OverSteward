ABOUTME: Cross-project rule against raw-SQL one-liners and `source .env` for secret extraction.
ABOUTME: Sourced into ~/.claude/CLAUDE.md so it loads regardless of which repo is active.

# Credential Hygiene

**Never `source .env` for secret extraction. Never run raw `psycopg`/`psql`/`sqlite3` one-liners against project databases.**

## The failure mode

Connection strings with `&`-containing query parameters (every Neon URL carries `&channel_binding=require`) leak through bash job control when sourced. The mechanism, in detail:

```bash
set -a && source .env && set +a && python -c "..."
```

Bash treats each `&` inside a sourced assignment as the job-control separator. Every `KEY=postgresql://USER:PASS@HOST/...&channel_binding=require` after the first `&` becomes a backgrounded command. Bash then prints `[N] Done KEY=postgresql://USER:PASS@HOST/...` to **stderr** — and the agent transcript captures everything on stderr. The connection string with credentials is now in the conversation log.

**This happened on 2026-05-26** (grantspider). Five Neon connection strings leaked into the transcript and required a full credential rotation. The architectural sin under the leak: skipping the registry → service → CLI flow for what felt like a too-small-for-the-process query.

## The rules

For any read or write against a project database — counts, recency checks, ad-hoc operator questions, "I just need a number":

1. **`cat <repo>/data/tool_registry.md | grep <topic>`** — look for an existing CLI subcommand first.
2. **If none exists, add the query as a method on the appropriate service** (`src/<package>/services/`) plus a thin CLI shell (`src/<package>/cli/`). Connection comes from the project's settings factory (`build_neon_store()`, `get_settings()`, or equivalent) — never from `os.environ` access in a one-liner. The added CLI *is* the work, not overhead on the work.
3. **For genuine ad-hoc reads with no permanent home**, use the project's `db scratch` subcommand if one exists (`<package> db scratch --sql "..."`). It enforces SELECT-only by default and reads connection state in-process via pydantic-settings.
4. **Only after all of the above are infeasible** do you fall back to raw `psycopg.connect()`, and even then **never** via shell `source .env`. Load secrets in-process with `from dotenv import load_dotenv; load_dotenv()`.

## What's blocked at the harness layer

`~/.claude/settings.json` denies the failing shapes — `source .env*`, `set -a*`, `python -c *psycopg*`, `psql:*`, `*DATABASE_URL*`, etc. Denial there is a backstop, not an authorization model: if you find yourself fighting the deny-list, you are about to write the wrong code.

**For anyone authoring such a block:** redirect on block, never just deny. A bare deny gives the agent no path forward — it retries, gets denied again, eventually asks Nathan. A PreToolUse hook that exits non-zero with a structured "do this instead" message (pointing at the `db scratch` CLI, the service-layer pattern, or `load_dotenv()`) makes the discipline self-teaching. The deny payload *is* the doctrine surface for the moment the agent is most likely to read it.

## How to apply

The temptation is loudest when the task feels too small for the full process. "Small" is the threat model the registry + layering rules exist to defend against, not an exception to them. The correct response to "I just need a number" is still "find or write a CLI." If adding a CLI is genuinely out of scope for the current task, stop and ask rather than fall back to raw SQL.

The rule extends past database queries: any shell command that consumes secrets via `source` of an unquoted `.env` is fragile by construction, regardless of whether the values look "safe." Use `load_dotenv()` from inside Python, or invoke a CLI that does.

See related: [pr-workflow](pr-workflow.md), [architecture-principles](architecture-principles.md).

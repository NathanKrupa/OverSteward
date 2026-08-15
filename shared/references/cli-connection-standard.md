ABOUTME: Estate-wide rule that CLIs — not MCP servers — are the standard connection procedure for GA4, GSC, Railway, Sentry, and Neon.
ABOUTME: Sourced into ~/.claude/CLAUDE.md so it loads regardless of which repo is active; pairs with credential-hygiene.md.

# CLI Connection Standard

**For GA4, GSC, Railway, Sentry, and Neon, the CLI is the standard connection procedure. Do not add these as MCP servers.**

## Why — the maps are unstable

MCP servers ("the maps") are a live network transport. When one churns or its
host stalls, it can silently take the whole session's transport down. That is
what caused the **2026-07-04 mobile-session disconnect**: the `sentry` HTTP MCP
server was a transport churner (removed in OverSteward PR #198). The auth-looping
claude.ai connectors (Google Drive/Calendar) compound it.

CLIs have none of that failure mode. They are:

- **Stable** — a subprocess that exits, not a long-lived socket that can wedge the session.
- **Scriptable & auditable** — every call is a shell command in the transcript.
- **Credential-hygiene-enforceable** — the harness hooks (`guard_neon`, the
  credential-hygiene deny rules) gate CLI shapes; MCP calls bypass them.

For the five services the estate actually operates against, the CLI already
covers the need. The MCP servers are redundant churn — retire them.

## The rule

1. **Never register GA4, GSC, Railway, Sentry, or Neon as an MCP server** — not in
   a repo `.mcp.json`, not in `~/.claude.json` `mcpServers`, not as a claude.ai
   connector. Use the CLI below.
2. **A repo `.mcp.json` for a managed context is `{"mcpServers": {}}`** unless there
   is a specific, justified need that a CLI cannot meet.
3. **Read-only by default.** Agents get read-only access to production systems;
   mutating/destructive/credential-revealing operations are operator-only. See
   `credential-hygiene.md` for the secret-handling rules that apply to every
   command below.

## Per-service procedure (verified 2026-07-04)

### Railway — `railway`
Installed at `~/.railway/bin/railway`, authenticated via `railway login`.

- `railway status` — project/environment/service overview.
- `railway logs -s <service> -e <env> [--build]` — deploy/build logs.
- `railway whoami` — auth check.
- MCP-free structured reads (deployments, metrics) are also available via the
  railway MCP tools **only if** a session still has them; prefer the CLI.
- **Never** `railway variables --json` / `--kv` — it prints raw secrets to the
  transcript. Check presence with a boolean pipe; rotate if a value leaks.

### Neon — `neon` (2.30.0)
Guarded by the `guard_neon.py` PreToolUse hook (OverSteward #196): **deny-by-default,
read-only for agents.**

- Allowed (agents): `neon me | --version | --help`, `projects list|get`,
  `branches list|get`, `databases list`, `roles list`, `operations list|get`.
- **Operator-only** (mutating/destructive/credential-revealing) — run with the
  `!` operator prefix in your own session: `! neon <subcommand>`. The estate has
  a history of accidental full-database wipes; this guard is load-bearing.
- For SQL reads against a project DB, use that project's `db scratch` / `db state`
  read-only subcommand, never a raw `psql`/`psycopg` one-liner (see credential-hygiene.md).

### GA4 (Google Analytics) — `wphelper analytics`
Via the wphelper CLI (`/home/natha/wphelper/.venv/bin/wphelper`), profile
`aigranthelper`, service account `exchequer-ga4@`. Read-only.

- `wphelper analytics top-pages` — top pages by views.
- `wphelper analytics sources` — traffic sources by sessions.
- `wphelper analytics page <url>` — full breakdown for one page.
- `wphelper analytics trend <metric>` — daily trend.

### GSC (Google Search Console) — `wphelper gsc`
Same wphelper CLI + profile. Read-only for reporting; sitemap submit is the one
write and is deliberate.

- `wphelper gsc top-queries` — top queries by clicks.
- `wphelper gsc top-pages` — top pages by clicks.
- `wphelper gsc sitemap-status` — registered sitemaps + status.
- `wphelper gsc submit-sitemap <url>` — (write) submit/re-submit a sitemap.
- URL Inspection is rate-limited (~2000/day/property); sample and log the sample size.

### Sentry — `sentry-cli` (3.6.0)
Installed to `~/.local/bin/sentry-cli`. Reproduce on a new machine with:

```bash
mkdir -p ~/.local/bin
curl -sL https://sentry.io/get-cli/ | INSTALL_DIR="$HOME/.local/bin" bash
```

Auth via `sentry-cli login` or a `SENTRY_AUTH_TOKEN` env var (never commit the
token; supply it in-process, not on the command line). Read-only use:

- `sentry-cli info` — verify configuration + authentication.
- `sentry-cli projects list` — projects in the org.
- `sentry-cli issues list` — issues (filter with `--query`).
- `sentry-cli events list` — events for a project.

## claude.ai connectors (Google Drive/Calendar, Canva, Gmail)

These are account-level MCP connectors, not covered by the five services above and
**not CLI-touchable** from a session. When they auth-loop or go unused they add
transport churn — disable the unused ones in **claude.ai → Settings → Connectors**.
This is an operator-manual action.

## See also

- `credential-hygiene.md` — the secret-handling rules (no `source .env`, no raw
  DB one-liners, no `railway variables` secret-print) that every command here obeys.

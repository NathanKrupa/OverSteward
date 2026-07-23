# Estate Secrets Registry

ABOUTME: Canonical inventory of every secret across the House of Krupa estate — name,
ABOUTME: location, consumer, and regeneration/rotation procedure. Never values.

**Iron rule: this document contains NO secret values — ever.** Names, storage
locations, consumers, and procedures only. The secret-scan pre-commit gate
(OS#221) enforces hygiene mechanically; this registry exists so a rotation or
rebuild never starts from archaeology again (born of the 2026-07-23
`WEB_BOT_AUTH_PRIVATE_KEY` exposure, where the rotation procedure had to be
reverse-engineered from three repos).

**How to use it:** when a secret leaks, expires, or a provider forces a reset,
find its row, follow the *Regenerate* and *Apply* columns, done. When you mint a
**new** secret, follow [§ New-secret standard process](#new-secret-standard-process)
— the entry lands here in the same PR that introduces the secret.

---

## 0. Estate-level credentials (no single repo)

Credentials that authenticate *the operator or the tooling itself*, held outside
any repository.

| Credential | Where it lives | Consumer | Regenerate | Apply |
|---|---|---|---|---|
| GitHub CLI auth | `gh auth` keyring/config (per machine: WSL2 + Windows) | all repos — PRs, issues, dispatch | `gh auth login` (browser flow) | nothing else — CLI reads it directly |
| Railway CLI OAuth | `~/.railway/config.json` (`user.accessToken`) | deploys, variables, logs, usage forensics | `railway login` (browser flow) | nothing else; note: backboard GraphQL needs this token + browser UA (see memory `railway-usage-api`) |
| Neon CLI/API auth | `neonctl` auth / Neon console API key | DB branch ops (operator-only under read-only-Neon law) | Neon console → Account → API keys | re-auth `neonctl`; hard hook keeps Claude read-only |
| Happy relay pairing | Happy app/CLI pairing (public relay) | phone membrane to operator sessions | re-pair from the Happy app | none |
| Anthropic Max session | Claude Code login (per machine) | all in-session work | `claude login` | none |
| Google Cloud SDK auth | `gcloud auth login` (`~/google-cloud-sdk`) | GA4/GSC checks per CLI-connection standard | `gcloud auth login` | none |
| Sentry CLI auth | `sentry-cli` token in its config | error triage per CLI-connection standard | Sentry → User settings → API tokens | `sentry-cli login` / update token |

## 1. aigranthelper (AG)

One Railway project, two environments (`production`, `staging`); variables are
**per-environment** (staging cloned from prod with overrides —
`docs/operations/staging-deploy.md`). Authoritative var list:
`config/settings/base.py` + `docs/deploy.md` (the `.env.example` lists only 4
vars — known gap). GitHub Actions secrets are a separate store for CI/smoke.

| Secret | Consumer | Regenerate | Apply / notes |
|---|---|---|---|
| `SECRET_KEY` | Django core | operator: `python -c "import secrets; print(secrets.token_urlsafe(64))"` (`docs/operations/production-deploy.md` Phase 1) | Railway per-env; rotating invalidates sessions |
| `DATABASE_URL` | tenant Neon DB | Neon dashboard → rotate connection string | Railway per-env (staging = staging tenant) |
| `RESEARCH_DATABASE_URL` | `apps/research` read-only (`ag_research_reader` role) | Neon research project → reset role password | shared across envs by design |
| `ORIGIN_VERIFY_SECRET` | Cloudflare→origin lock (`apps/core/origin_lock.py`) | operator-gen random | must be updated in the **Cloudflare rule and Railway together** |
| `RESEND_API_KEY` | magic-link/email (Anymail) | Resend dashboard | also a GH Actions secret for smoke |
| `STRIPE_SECRET_KEY` + `DJSTRIPE_WEBHOOK_SECRET` (+ price IDs) | dj-stripe billing | Stripe dashboard → roll key; Webhooks → per-endpoint signing secret | staging is TEST mode by design (Nathan-law); CI smoke uses distinct name `STRIPE_TEST_SECRET_KEY` |
| `B2_ACCESS_KEY_ID`/`B2_SECRET_ACCESS_KEY` (+ org-docs vars) | studio docs, telemetry archive, DB backup | Backblaze B2 → Application Keys | — |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` | Studio LLM calls | provider consoles | also GH Actions secrets for LLM smoke |
| `TELEMETRY_HASH_SALT` | telemetry PII hashing | operator-gen random | rotating breaks hash continuity — note before rotating |
| `WEB_BOT_AUTH_PRIVATE_KEY` + `WEB_BOT_AUTH_PUBLIC_KEY_JWK` | Cloudflare Verified Bots directory (`apps/bot`) | **`uv run python scripts/web_bot_auth_keygen.py`** — operator terminal only, never via a Claude session | Railway **shared vars, both envs** (same pair); verify: directory `x` value changed at `/.well-known/http-message-signatures-directory`; verifier caches ≤1h. Rotated 2026-07-23 after transcript exposure. |
| `SENTRY_DSN` | error reporting | Sentry project settings | low sensitivity |
| `GA4_MP_API_SECRET` | GA4 Measurement Protocol | GA4 Admin → Data Streams → MP API secrets | — |
| `CORRECTION_EXPORT_TOKEN` | internal corrections export auth (GS is the client) | operator-gen random | **rotate in AG Railway + GS `GRANTSPIDER_CORRECTION_EXPORT_TOKEN` together** |
| `SMOKE_TEST_TOKEN` | Playwright login bypass | `secrets.token_urlsafe(32)` (staging-deploy.md Phase 3) | staging value must differ from prod; also GH Actions secret (workflow uses singular `SMOKE_TEST_EMAIL` vs settings' plural — known trap) |
| `TYPESENSE_SEARCH_API_KEY` (+ `TYPESENSE_URL`) | foundation/gov search connectors | Typesense API-key endpoint on the AG `typesense` service (search-only key) | prod URL is the **private domain `typesense.railway.internal:8108`** — typo'd hostname broke prod search until 2026-07-23 |
| `PERPLEXITY_API_KEY` | `apps/ops/geo_monitoring.py` (direct `os.environ` read) | perplexity.ai dashboard | ⚠ undocumented anywhere in AG — highest-priority doc gap |
| `FISCUS_JWT_PUBLIC_KEY_PATH` (+ alg/issuer/audience vars) | telemetry endpoint verifies bearer JWTs | public key material — not a secret; the **signing** key's home is an open gap (see § fiscus) | — |

GitHub-Actions-only: `CF_ACCESS_CLIENT_ID`/`CF_ACCESS_CLIENT_SECRET` (Cloudflare
Zero Trust → Access service tokens; reaches protected staging),
`GRANTSPIDER_READ_TOKEN` (fine-grained PAT, cross-repo schema-drift read — also
runtime-consumed), `BUMP_PR_TOKEN` (PAT for auto-bump PRs).

Gaps (2026-07-23 sweep): `.env.example` near-empty; no rotation runbook beyond
Stripe live-cutover; `PERPLEXITY_API_KEY` and `GRANTSPIDER_READ_TOKEN` scopes
undocumented.

## 2. grantspider (GS)

Composition root: `src/grantspider/config/settings.py` (pydantic-settings,
`env_prefix="GRANTSPIDER_"`; most secrets also accept a bare legacy alias).
Set in Railway shared vars (GrantSpider project, production env), local `.env`
via `scripts/dev/with_test_env.py`, and GitHub Actions secrets for CI/DQ.

| Secret | Consumer | Where set | Regenerate | Apply / notes |
|---|---|---|---|---|
| `GRANTSPIDER_NEON_DATABASE_URL` (alias `NEON_DATABASE_URL`) | research DB — crawler, enrichment, Dagster assets | Railway shared; `.env`; GH secret `NEON_DATABASE_URL` (DQ workflows) | Neon dashboard → reset role password | ⚠ #1849: in the daemon the bare alias points at the *metadata* DB — orchestration requires the prefixed name |
| `NEON_DATABASE_URL_CI` | CI test DB | GH Actions secret only | Neon (CI branch/role) | — |
| `GRANTSPIDER_ANTHROPIC_API_KEY` (alias) | enrichment/classifier LLM calls | Railway shared; `.env`; GH secret | console.anthropic.com → API Keys | — |
| `GRANTSPIDER_BRAVE_SEARCH_API_KEY` | website discovery | `.env` / Railway | api-dashboard.search.brave.com | optional; empty disables |
| `GRANTSPIDER_SAM_API_KEY` | SAM.gov sync | Railway shared; `.env` | sam.gov account → API key | optional; empty disables |
| `GRANTSPIDER_B2_ACCESS_KEY_ID` + `GRANTSPIDER_B2_SECRET_ACCESS_KEY` | B2 snapshots, backups, audit archive | Railway shared; `.env` | Backblaze B2 → Application Keys (secret shown once) | bucket shared with AG |
| `GRANTSPIDER_TYPESENSE_ADMIN_API_KEY` | nightly foundations reindex/alias swap | Railway (engine lives in AG project — cross-project reach) | Typesense bootstrap key / API-key endpoint on the AG `typesense` service | **admin/write key** — distinct from AG's search-only key |
| `GRANTSPIDER_NEON_API_KEY` | pre-migration Neon branch snapshot (armed-migration path) | local `.env` only | Neon console → API keys | `SecretStr`; migration path only |
| `GRANTSPIDER_CORRECTION_EXPORT_TOKEN` | AG corrections export bearer | `.env` / Railway | issued by aigranthelper (`/internal/corrections/` auth) | — |
| `DAGSTER_PG_PASSWORD` (+ non-secret HOST/USERNAME/DB) | Dagster metadata DB | Railway shared (webserver+daemon) | Neon → reset `grantspider_dagster_user` password | probed at boot by `pg_probe_entrypoint.sh` |
| `AG_TENANT_DATABASE_URL` | daily AG-tenant pg_dump → B2 | Railway (backup path) | Neon (AG tenant, `pg_read_all_data` role) | **read-only role**, direct endpoint for pg_dump |
| `GRANTSPIDER_SMTP_PASSWORD` (+ HOST/PORT/USER) | dead-man's-switch alerting | `.env` / Railway | SMTP provider dashboard | — |
| `GRANTSPIDER_OUTBOUND_PROXY_URL` | egress proxy pinning the published crawler IP | Railway / `.env` | `docs/runbooks/tinyproxy_egress_proxy.md` | URL embeds `user:pass` — treat whole URL as secret |
| `GRANTSPIDER_WEB_BOT_AUTH_PRIVATE_KEY` | Web Bot Auth request signer (Cloudflare Verified Bots) | **currently unset in prod** (signer disabled; verified 2026-07-23) | new Ed25519 pair; publish pubkey at `GRANTSPIDER_WEB_BOT_AUTH_KEY_DIR_URL` (default `bot.thealmoner.com` directory) | separate identity from AG's pair |
| `RAILWAY_API_TOKEN` (+ service/env ID vars) | daemon-watchdog Railway restart | Railway (webserver) | Railway → Account/Project Tokens | IDs are identifiers, not secrets |
| `AG_DISPATCH_PAT` | cross-repo dispatch to AG on main | GH Actions secret | GitHub → fine-grained PAT (repo-dispatch on AG) | — |

**Delegated-arm migration token** is not an env secret: a mode-restricted local
file `~/.grantspider/prod-migration.arm`, written by the arm CLI, single-use
(see `documentation/prod-migration-neon.md`). Its only real credential
dependency is `GRANTSPIDER_NEON_API_KEY`.

Gaps (2026-07-23 sweep): `.env.example` documents only ~15 vars — missing
Typesense admin, Neon API, correction token, Dagster PG set, `AG_TENANT_DATABASE_URL`,
proxy URL, bot-auth key, watchdog token, and the direct-`os.environ` LLM
alternates (`GEMINI_API_KEY`/`GOOGLE_API_KEY`, `OPENAI_API_KEY`). No Sentry
integration exists in GS despite folklore.

## 3. wphelper (+ wphelper-clients)

Two delivery paths for the WordPress secret: **env/`.env`** (single site,
`config.wordpress_env()` — every env read centralized in
`src/wphelper/config.py`) and **OS keyring per project** (service
`wphelper:<project>`, entry `<env>`; env override
`WPHELPER_<PROJECT>_<ENV>_PASSWORD`; stored via
`wphelper project credentials set <project> <env>`). Per-client `client.yaml`
holds only non-secret refs; the client `.env` (gitignored) holds credentials.

| Secret | Consumer | Where set | Regenerate | Apply / notes |
|---|---|---|---|---|
| `WP_APP_PASSWORD` / per-project keyring password | WordPress REST basic-auth | `.env`, per-client `.env`, or keyring | WP admin → Users → Profile → **Application Passwords** | ⚠ WP app-password format (`xxxx xxxx xxxx xxxx`) is a **gitleaks blind spot** — no default rule matches it; add a custom rule (tracked from the 2026-07-23 dream lesson). |
| `WP_FTP_PASSWORD` (+ `WP_FTP_HOST`/`WP_FTP_USERNAME`) | FTP/SFTP transfer; doubles as SSH/WP-CLI password fallback | `.env` | Host control panel (cPanel/Plesk) → FTP accounts | — |
| SSH private key at `SSH_PRIVATE_KEY_PATH` (+ `SSH_PASSPHRASE`) | SFTP + WP-CLI over SSH | key file on disk; path in `.env` | `ssh-keygen`, re-add pubkey to host `authorized_keys` | key file is the secret, not the path |
| `KIT_API_KEY` | Kit/ConvertKit v4 client | `.env` | kit.com → Account Settings → Developer | optional |
| GA4/GSC service-account JSON at `GA4_CREDENTIALS_PATH`/`GSC_CREDENTIALS_PATH` | Analytics + Search Console reports | JSON file outside repos (`~/.config/exchequer/ga4-the-almoner.json`), path in `client.yaml`/`.env` | GCP → IAM → Service accounts → new JSON key; grant GA4 property + GSC site access | one SA shared across GA4+GSC by design — one leak exposes both |
| `INDEXNOW_KEY` | IndexNow submissions | `.env` | self-generated; publish key-file at site root | optional |
| `PYPI_API_TOKEN` | CI publish (`release.yml` → `TWINE_PASSWORD`) | **GitHub Actions secret** | PyPI → Account settings → API tokens | only CI secret in the repo |

Gaps (2026-07-23 sweep): `wphelper-clients/special-angel/.env` is world-writable
on a OneDrive symlink (harden perms); no custom gitleaks rule for WP app
passwords yet; no offboarding/rotation doc for client credentials; keyring
absent on headless WSL forces the env-override channel.

## 4. ai-assistants (almoner)

Secrets in `.env` / `.env.production` / `.env.staging` plus PHP sub-app `.env`
files (`grant-helper-mvp/`, `work-with-almoner/`); mapped through
`config/settings.py`.

| Secret | Consumer | Regenerate | Apply / notes |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | RAG content generator | console.anthropic.com | — |
| `TODOIST_API_KEY` | Todoist CLI integration | todoist.com → Settings → Integrations → Developer | `SETUP_NEW_MACHINE.md` wrongly calls it `TODOIST_API_TOKEN` |
| `WP_APP_PASSWORD` (+ URL/username) | WordPress REST publishing to thealmoner.com | WP admin → Users → Profile → Application Passwords (`WORDPRESS_INTEGRATION_GUIDE.md` §1; 90-day rotation documented) | same gitleaks blind-spot as wphelper |
| `WP_FTP_PASSWORD` (+ host/user/port) | debug.log / FTP retrieval | cPanel → FTP Accounts (`WORDPRESS_FTP_SETUP.md`; 90-day rotation) | `SSH_*` SFTP fallback vars exist in code but in no `.env.example` |
| `KIT_API_KEY` (= `KIT_V3_API_KEY`) | Kit/ConvertKit CRM (PHP backends + import scripts) | Kit dashboard | ⚠ same key under two names — easy to misconfigure |
| `RECAPTCHA_SECRET_KEY` | form protection (PHP backends) | google.com/recaptcha/admin | — |
| `SMTP_PASS` (+ host/user/port) | inquiry notification email | cPanel → create/reset `inquiries@thealmoner.com` | — |
| `NEON_DATABASE_URL` (+ `_DIRECT`) | `src/almoner/db/cli.py` | Neon dashboard | — |
| `GOOGLE_ADS_DEVELOPER_TOKEN`/`CLIENT_ID`/`CLIENT_SECRET`/`REFRESH_TOKEN` | Google Ads optimizer | Google Ads API console / OAuth consent re-issue | live in `.env` though `.env.example` marks them "future" |
| GA4 SA JSON (hardcoded path) | `scripts/analytics/ga4_grant_helper_report.py` | GCP → IAM → new SA JSON key | ⚠ hardcoded machine-specific Windows path — not env-driven |

Gaps (2026-07-23 sweep): `CICD_SETUP.md` prescribes ~16 `STAGING_*`/`PRODUCTION_*`
GH Actions secrets but **no workflows exist** (vaporware — don't provision);
`SAM_API_KEY` + `INQUIRIES_USER/PASSWORD` provisioned with no in-repo consumer
(remove or document); no rotation policy beyond the WP/FTP 90-day note; **no Web
Bot Auth material here** — `bot.thealmoner.com` (GS's default key-directory URL)
is served by no estate repo (dormant identity, currently 404/non-JSON).

## 6. fiscus

Live repo is `/home/natha/Fiscus` (capital F; lowercase `fiscus` is a read-only
mirror). No `.env.example` exists (gap). Pure telemetry *consumer* — holds no
signing keys.

| Secret | Consumer | Regenerate | Apply / notes |
|---|---|---|---|
| `FISCUS_TELEMETRY_TOKEN` | `src/fiscus/transports.py` bearer header on `signed_jwt` pulls | ⚠ **no mint procedure exists anywhere yet** — the AG-side signer is "designed, not built" (`FISCUS.md`); AG holds only the *verify* public key (`FISCUS_JWT_PUBLIC_KEY_PATH`) | local `.env` (mode 600) / CI env |
| `ANDON_INGEST_TOKEN` → injected as `GH_TOKEN` | `gh issue list --label andon` across pickup repos | GitHub → fine-grained PAT, `issues:read` on the six estate repos | GH Actions secret in `weekly-review.yml` |
| `GHP_TELEMETRY_TOKEN` | CI injection in `weekly-review.yml` | — | ⚠ **name mismatch bug**: CI injects `GHP_TELEMETRY_TOKEN` but code reads `FISCUS_TELEMETRY_TOKEN` — signed-jwt pulls in CI silently degrade to `TelemetryUnavailable` |
| `OBSIDIAN_DEPLOY_KEY`, `DIGEST_SMTP_HOST/USER/PASS` | delivery steps in CI | deploy key: Home_Obsidian repo settings; SMTP: provider | consumers (`fiscus.delivery.*`) are **unbuilt stubs** — secrets declared before their consumers exist |

Open architecture gap: nothing in the estate currently mints the telemetry JWT
— the signing private key has no designated home. Decide (AG-side mint script
vs operator-held key) before provisioning `FISCUS_TELEMETRY_TOKEN` anywhere.

## 5. exchequer

Local-only repo; **all secrets live in `/home/natha/exchequer/.env`** (gitignored),
read solely by the `src/exchequer/config.py:from_env` factory; each connector
takes its credential as a constructor param. A missing key disables that one
connector, not the run. Names documented in `.env.example`.

| Secret | Consumer | Regenerate | Apply | Notes / scope |
|---|---|---|---|---|
| `STRIPE_API_KEY` | `connectors/stripe_billing.py` | Stripe Dashboard → Developers → API keys → **Create restricted key** | edit `.env` | Restricted read-only: Balance transactions + Subscriptions Read. Never the live secret key. |
| `ANTHROPIC_ADMIN_KEY` | `connectors/anthropic_cost.py` (org cost report) | Anthropic Console → Settings → **Admin keys** | edit `.env` | Reads the org bill, not inference. Max subscription is untracked here (manual in `expenses.csv`). |
| `NEON_API_KEY` | `connectors/neon.py` | Neon console → Account settings → API keys | edit `.env` | Read-only. Identifiers ride along: `NEON_ORG_ID`, `NEON_AG_PROJECT_ID`, `NEON_GS_PROJECT_ID`. |
| `RAILWAY_TOKEN` | `connectors/railway.py` (GraphQL) | Railway → Account settings → Tokens | edit `.env` | Account-scoped. Connector's `estimatedUsage` query shape unverified end-to-end. |
| `GOOGLE_APPLICATION_CREDENTIALS` | `connectors/ga4.py` | GCP → IAM → Service accounts → new JSON key (Analytics Data API enabled, Viewer on AG GA4 property) | replace the JSON key file at the path in `.env` (file lives **outside** the repo: `~/.config/gcp/`) | ⚠ scope drift: the live SA was granted **Editor** on GA4 for a one-off; intent is Viewer. Reconcile at next rotation. |

MCP configs (`.mcp.json`) hold **no** secret values — only a path to the out-of-repo
SA key and identifiers; Railway MCP rides the CLI login; Monarch is browser OAuth
(account-scoping to the business account is convention-only — flagged, not a credential).

Known gaps (from 2026-07-23 sweep): no rotation cadence documented; connectors
never exercised against live APIs; `.gitignore` `*.json` guard for stray SA keys
possibly unmerged.

## 6. fiscus

<!-- filled from repo sweep -->

## 7. OverSteward

Only one runtime env-secret family: the Vintner reader DSNs. Everything else the
control plane does (dispatch, dream, telegraph) rides estate-level CLI auth
(§0) — deliberately no `ANTHROPIC_API_KEY` in this repo (Max subscription, not
metered API). `.mcp.json` is empty by design (PR#198) — no MCP-held secrets.

| Secret | Consumer | Regenerate | Apply / notes |
|---|---|---|---|
| `VINTNER_RESEARCH_DATABASE_URL` | `src/oversteward/vintner/reader.py` (sole `os.environ` touch, ARCH-020) → `/pipeline-status` | re-run `documentation/designs/vintner/provision_vintner_reader.grantspider.sql` as the **GS Neon owner** (Neon SQL console, top-to-bottom); rebuild the DSN with the new password | export in shell or repo-root `.env` (gitignored). Role sees only `vintner.*` views. |
| `VINTNER_AG_DATABASE_URL` | ⚠ documented, **no code consumer yet** (Vintner AG adapter unbuilt) | `provision_vintner_reader.aigranthelper.sql` as the **AG Neon owner** | provision only when the adapter lands |

**Neon provisioning invariant** (the-vintner.md §9): create the role `LOGIN`
**with the password at creation** — a non-super owner cannot `ALTER` a role it
didn't create. Re-running the script is the rotation procedure (idempotent
password reset); always via the Neon SQL console as owner, never a raw `psql`
one-liner.

Gaps (2026-07-23 sweep): no `.env.example` (violates the process below — first
follow-up); no standalone Vintner rotation runbook (procedure lives in the SQL
file headers); sibling-repo secret names appearing in OverSteward design docs
are references, not requirements.

---

## New-secret standard process

Every time a new key/token/credential is minted for any estate component, the
introducing change MUST do all of the following **in the same PR** (for
console-side secrets with no code change, a standalone registry PR the same
day):

1. **Register it here.** Add a row to the owning repo's section: name, storage
   location (Railway shared vs per-service, GitHub Actions secret, local
   `.env`, per-client file), consumer, regeneration procedure (exact dashboard
   path or script), apply procedure (what to update + whether a
   redeploy/restart is needed).
2. **Never commit the value.** Placeholder in `.env.example` (name + comment,
   no value). The secret-scan pre-commit gate is the backstop, not the process.
3. **Scope it minimally.** Prefer read-only / restricted / search-only variants
   (Typesense search key vs admin key; Stripe restricted keys; Neon
   `vintner_reader`-style roles). Record the scope in the Notes column.
4. **Prefer a keygen script over hand-minting** when the secret is
   self-generated (the `scripts/web_bot_auth_keygen.py` pattern): one-shot,
   prints to the operator's terminal, never writes to disk or transcript.
   Reference the script in the Regenerate column.
5. **Generation is operator-side when output is sensitive.** Claude never runs
   a command that prints a fresh private key into a session transcript; the
   operator runs it in their own terminal and pastes into the storage location
   (dashboard editor for multi-line values).
6. **State the blast radius** in Notes: what an attacker gets with this value,
   and whether rotation is zero-downtime.

**Standing review:** the monthly `/refresh-docs` sweep checks this registry's
`Last verified` stamps against reality; any secret touched in a session gets
its row updated in that session's PR.

_Last full inventory: 2026-07-23._

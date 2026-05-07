---
session_date: 2026-05-06
status: paused (epic #729 crawler-legitimacy fully shipped; Web Bot Auth code on master; deploy prerequisites scoped but not built)
context: 22 PRs across the #717-#728 crawler-legitimacy epic; pivoted #725 IP-list path to Web Bot Auth (#728) after Railway-Pro plan blocker surfaced; discovered aigranthelper isn't deployed yet
---

## Where we left off

Marathon session through grantspider epic #729 — every dispatchable issue (#717 through #724) plus follow-ups (#735, #736, #742, #753) and the cross-repo Web Bot Auth half (aigranthelper #443) are merged. **22 grantspider PRs + 1 aigranthelper PR + 3 Neon migrations applied to prod** in one day.

The unfinished work isn't code — it's **infrastructure**: aigranthelper has no production host. That blocks Cloudflare Verified Bots submission (#727) and means the Web Bot Auth signer in grantspider is dormant until aigranthelper.com serves the key directory. Two operator-shaped issues filed (AG#448, AG#449) to unblock; a third bigger one (production Django deploy itself) is not yet filed — left to scope when you have time to commit to a deploy session.

## Merged this session

### grantspider (22 PRs)

**Foundation (Phase 1):**
| PR | Issue | What |
|---|---|---|
| #731 | #717 | OutboundHTTPClient factory + Gaudi lint guard |
| #732 | #718 | Brand consolidated to aigranthelper.com (UA + From) |
| #733 | #721 | host_health migration |

**Risk-surface migration (Phase 2):**
| PR | Issue | What |
|---|---|---|
| #734 | #719 | Foundation fetchers (enricher / page_scraper / cf_platform_detect) → factory |
| #737 | #720 | 6 Client-constructing API connectors → factory + `consult_robots` flag |
| #738 | #720 | 3 module-level `httpx.get` connectors (brave/ddg/irs) → factory |
| #746 | #735 | website_finder.url_liveness → factory (4th foundation fetcher; deferred from #719) |

**Durability (Phase 3):**
| PR | Issue | What |
|---|---|---|
| #739 | #722 | host_request_summary migration |
| #744 | #722 | Audit-log code (JSONL writer + Dagster rollup + B2 upload + CLI) |
| #740 | #723 | crawl_blocklist migration |
| #745 | #723 | Blocklist gate in factory + CLI commands |
| #741 | #724 | Cadence tiers (discovery/refresh/deep_dive) — app-side check, no migration |

**Coverage cleanup (#736 — 6-tranche split):**
| PR | Tranche | Files |
|---|---|---|
| #747 | A1 — state_portals primary 5 | _base, bidnet, feeds, scbo, usaspending |
| #748 | A1.5 — state_portals cleanup | ckan, gpr, sitemap, socrata + drop _default_client helper |
| #749 | A2 — foundations + procurement | procurement_portals/_base, ga_gma, cfcsra, us_chamber |
| #750 | B — gov + utility | gov_pdf, sitemap (top-level), sam_gov, irs_bmf_client + add `follow_redirects` to factory |
| #751 | C — reference + async | wikidata, wikipedia, http_head_client, ollama + add `httpx_timeout`/`max_redirects` to async factory |
| #752 | D — robots.py exemption | Lint exempts robots.py as 2nd factory peer (cycle-safe) |

**Infra:**
| PR | Issue | What |
|---|---|---|
| #743 | #742 | Strip `channel_binding=*` from URL before pg_dump (libpq 12 incompat with Neon) |
| #754 | #753 | Web Bot Auth Ed25519 signer + factory integration (sync + async) |

### aigranthelper (1 PR)

| PR | Issue | What |
|---|---|---|
| #445 | #443 | Web Bot Auth key directory at `/.well-known/http-message-signatures-directory` (signed JWKS) + keygen script |

### Closed without code

| Issue | Why |
|---|---|
| #728 | Decision documented: implement Web Bot Auth (replaces #725 IP-list path; Cloudflare Feb 2026 made signed requests the primary verification method) |

## Operations applied

- **Pulled grantspider main checkout** to refresh editable install
- **Applied 3 migrations to Neon production** via `alembic upgrade head` — head at `c2f1a8b3d6e5`. B2 backup uploaded at `db-backups/grantspider/20260506T123344Z_alembic.dump`
- **Installed PostgreSQL 17 client tools** on Windows (operator action; pg_dump 17.9 against Neon 17.8)
- **Edited `~/.bashrc`** to prepend `C:\Program Files\PostgreSQL\17\bin` so future shells pick pg 17 over Anaconda's pg 12.15
- **Installed Railway CLI** via npm — `railway 4.47.1` at `~/AppData/Roaming/npm/`
- **Generated Ed25519 keypair** at `C:\Users\natha\.secrets\` (wba_private.pem, wba_public.jwk.json, wba_thumbprint.txt) — awaiting a deploy target

## Decisions worth remembering

- **#725 (Railway egress + rDNS) superseded by Web Bot Auth path.** Railway-Pro plan blocker on static IPs prompted the pivot. Cloudflare's Feb 2026 announcement made signed requests primary; signed requests don't need stable IPs. Should formally close #725 next session.
- **#726 (`/bot` page) lower-priority.** Folded conceptually into AG#448's placeholder (which serves the static signed key directory at the same domain). Could close #726 or leave open as a future operator-page reminder.
- **#736 inventory was undercount.** Issue body said 14 connectors; fresh `git grep` found 19 (1 factory + 18 migration-eligible). Architect-ruled into 6 tranches. Reinforces memory `feedback_no_pre_enumeration_in_audit_issues` — pre-enumerated file lists rot fast.
- **Harness instability hit hard mid-session.** Roughly 6 dispatches dropped or stalled (false-positive completions, mid-narrative cutoffs). Most agents got their work to remote via heartbeat-pushes; one (#722 P2) had to be resumed; #720 PR-A and #736 A1.5 were each re-dispatched twice. Mitigations that helped: explicit "push after every migrated file" instructions, "keep all commit messages and PR title/body lines under 72 chars" (mid-trim of long lines was a recurring drop site).
- **Ad-hoc in-session work succeeds when worktrees are reused.** When Nathan said "do it in session" for #736 A2 mid-tranche, doing the migration directly via the existing dispatch worktree (rather than re-dispatching) was faster and cleaner. Pattern to repeat when an agent gets stuck near completion: kill, take over the WIP branch, finish manually.

## In flight / pending

### AG follow-ups filed today (not yet built)

- **AG#448 — coming-soon placeholder at aigranthelper.com.** Cloudflare Pages or similar static host. Critically also serves the **signed Web Bot Auth directory as a static file** so Cloudflare submission can proceed without waiting for Django deploy.
- **AG#449 — staging.aigranthelper.com pre-prod environment.** Marked `backlog`; depends on production Django deploy existing first.

### Implicit prerequisite NOT yet filed

- **Production Django deploy of aigranthelper to Railway.** Discovered today: AG project on Railway has no services. Aigranthelper has never been deployed. This is a half-day operator+code task (Railway service + GitHub auto-deploy + DATABASE_URL to Neon AG project + ALLOWED_HOSTS / SECRET_KEY / Stripe / DEBUG=False / migrate / collectstatic / custom domain DNS + SSL). Filed-when-ready.

### Operator follow-ups when AG#448 ships

1. Provision keypair: copy `C:\Users\natha\.secrets\wba_private.pem` and `wba_public.jwk.json` content into the deploy target's env vars (or rotate by re-running the keygen)
2. Verify: `curl -i https://aigranthelper.com/.well-known/http-message-signatures-directory` returns signed JWKS
3. Submit to Cloudflare dashboard → Manage Account → Configurations → Bot Submission Form → "Request Signature" verification (closes #727)

### Issues to triage next session

- **#725 Railway egress + rDNS:** close as superseded-by-Web-Bot-Auth
- **#726 `/bot` page:** keep open as reminder, or close (folded into AG#448's scope)
- **#727 Cloudflare Verified Bots submission:** awaiting AG#448 + keypair provisioning
- **AG#448 `ready-for-agent`:** scope-review per AG conventions, then dispatch (the static page + static signed directory file is mostly mechanical)

## Architecture state

`architecture.md` was last updated 2026-05-02. Today's work touched:

- **§5 (recent moves):** should add an entry for the #729 crawler-legitimacy epic (one-line: "PRs #731-#754 — every connector now flows through `OutboundHTTPClient`; signed-request infra ready for Cloudflare verification once aigranthelper deploys")
- **§3 (invariants):** could add I-19 — "All outbound HTTP traffic flows through `OutboundHTTPClient`; bare `httpx.Client` construction is forbidden outside the factory and `robots.py` (lint-enforced)"
- **§4 (liabilities):** add an entry — "Aigranthelper not yet deployed to production; AG#448 placeholder + AG#449 staging + implicit prod-deploy issue track this"

Update next session if priorities allow.

## Gotchas for next session

- **`~/.bashrc` PATH fix only affects login/interactive shells.** `bash -c` (Claude Code's Bash tool) doesn't source `.bashrc`, so `pg_dump --version` in this tool still reports Anaconda's 12.15. Doesn't affect anything Nathan does interactively — only matters if a future Claude session needs pg_dump for some reason.
- **Stale-sibling-install pattern recurred.** When grantspider's `.venv` editable install pointed at out-of-date code, agent dispatches needed `PYTHONPATH=src` overrides to find newly-added code. Memory `feedback_stale_sibling_install` codified this.
- **Aigranthelper default branch is `main`, not `master`.** The dispatch playbook prompt template defaults to `master`; AG#443's agent corrected for this and proceeded. Worth noting in the playbook eventually.
- **Generated Ed25519 keypair sits at `C:\Users\natha\.secrets\` — never commit.** Re-usable when AG deploys; rotate freely if you'd rather start fresh.
- **Railway CLI auth doesn't span shells.** Nathan logged in via Git Bash; Claude's Bash tool sees no token. Either run Railway commands in Nathan's interactive shell, or copy the token (path TBD on Windows — wasn't found in the obvious AppData locations).

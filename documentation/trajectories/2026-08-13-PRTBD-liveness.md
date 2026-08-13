---
date: 2026-08-13
repo: oversteward
pr: oversteward#TBD
branch: session/liveness-sweep
issues:
  - oversteward#353
session_kind: in-session-pickup
duration: 60min
---

# Trajectory — give the session-start pass a way to see liveness

## Context

Nathan queued OS#353 as the first project after a day in which the estate's
blind spot proved itself: GrantSpider's `embedding` service sat CRASHED from
2026-08-11 to 08-13 while the morning Sentry sweep reported inbox zero
throughout. A crashed Railway service emits no Sentry issue, so every layer the
estate had — Sentry's own alerts, the triage sweep, `ON_FAILURE` restarts — was
answering "what errored" and none was answering "what is still running".

## Trajectory

The feasibility question was whether Railway could be read programmatically
without a per-project `cd`. It can: `railway service list --json --project <id>
--environment <env>`. The `--environment` requirement is not incidental —
`--project` alone is rejected, and without the pair the CLI falls back to
whatever directory it was invoked from, which would silently sweep the wrong
estate. That is pinned by a test.

The substance turned out to be **classification, not transport**. Railway's
`status` alone does not answer liveness: a scheduled one-shot legitimately ends
`SUCCESS` *and* `deploymentStopped`, while a long-running service that is
stopped is down. The estate has both shapes in one project — AG runs six cron
services alongside its web service. So the judgement is: SUCCESS+stopped is
`completed`, SUCCESS+running is `running`, BUILDING/DEPLOYING are `in-flight`
and not findings, CRASHED is `down` **whether stopped or not** (that run
failed), and an unrecognised status is `unknown` rather than assumed healthy.

The instrument found something on its first live run —
`aigranthelper/submit_seo_urls` CRASHED. Worth being precise about what that
proves: it correlates with AG#1368, an open issue, so Sentry *did* capture that
error. The liveness check adds **state** ("it is sitting crashed") rather than an
event. The genuinely Sentry-blind case remains `embedding`, which emitted
nothing at all.

## What worked

- [design] Putting the verdict in `models.py` as a property rather than in the client or the CLI: the transport stays a transport, and the one interesting decision in the whole feature is in one place with its own tests.
- [process] Exercising both failure exits for real — empty registry, and `railway` absent from PATH — rather than trusting the unit tests. The instrument's entire purpose is that a failure to look must not read as a clean result, so a mocked-only proof of that would have been self-defeating.
- [design] Refusing on an unreadable project instead of skipping it. A partial sweep reported as complete is the same failure class the instrument exists to remove.
- [tooling] Running it against the live estate before writing the PR: 20 services across two projects, and it found a real one.

## What didn't  (cost: trivial | minutes | hours | blocked)

- [design][minutes] The first OUTER script took a `registry_path` parameter and manipulated `sys.path`; gaudi blocked the commit on SEC-012 (tainted path to `open`) and STRUCT-010. Both were real: the sibling `sentry_triage.py` needs no `sys.path` hack because the package is installed, and a config loader accepting an arbitrary path is a traversal surface for no benefit when there is exactly one registry → remedy: `liveness/config.py` became a pure function over *loaded* registry data, and the script reads its one fixed path. The tests got simpler too — dicts instead of temp files.
- [process][trivial] Regenerated `data/tool_registry.md` only after the first commit attempt failed; it should be part of the same change as a new script.

## What was learned

- [design] When a gate rejects an entrypoint for a security or packaging error, the fix is usually a layering fix, not a suppression: both findings here disappeared by moving config parsing into the middle layer where it belonged → promote: doctrine.
- [design] "Is it running" is not derivable from a single status field once an estate mixes long-running services with scheduled one-shots. Encode the shape difference, or a completed cron reads as an outage every morning → promote: memory.
- [process] An instrument whose purpose is to distinguish "found nothing" from "could not look" must have *both* failure paths exercised against reality, or it has only been tested on the path that was never in doubt → promote: doctrine.

## Tools

- `railway service list --json --project <id> --environment <env>` [used] — the read; needs both flags
- `scripts/service_liveness.py` [NEW] — the sweep
- `.venv/bin/gaudi check --severity error` [used] — caught the layering error before commit

## Open threads

- **`aigranthelper/submit_seo_urls` is CRASHED right now** (last run 2026-08-13 03:00 UTC). Correlates with AG#1368; its Railway logs had already aged out. Worth confirming whether #1368's fix is deployed.
- The sweep covers grantspider and aigranthelper. Any other Railway project is invisible until it gets a `railway:` block in registry.yaml.
- Freshness assertions over what each service *writes* (option 1 in OS#353) remain unbuilt. Railway status answers "is the process up", not "is it doing its job" — a service can be Online and stalled, which is the `#1821` daemon-watchdog shape.
- Nothing yet runs this automatically; it is a session-start pass like the others, and the estate's law is that scheduled cloud agents are unreliable.

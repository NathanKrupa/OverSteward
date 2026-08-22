---
name: ag-triage
description: "Drain aigranthelper's operator queues — sweep every named ops report (untriaged feedback, visitor-reported corrections, funnel/KPI/alert reports) over the /internal/ops/ seam, then rule on each item and record the verdict. Deterministic and zero-LLM. Invoke at the START of a session, when Nathan says \"ag triage\" / \"/ag-triage\", or when asked what AG users are waiting on."
---

# /ag-triage — every AG queue read, none left unread

The pull side of aigranthelper's operator seam (AG#1719). AG's in-app feedback
and visitor-reported data corrections used to be visible only by clicking
through the admin, which meant they were visible only when someone remembered to
look. This sweep makes "nothing is waiting" a measurement instead of an
assumption — same shape, and the same reasons, as `/sentry-triage`.

Run from the **OverSteward** working tree:

```bash
export PYTHONPATH="$PWD/src"
AGTRIAGE=".venv/bin/python scripts/ag_ops_triage.py"
```

Two scoped tokens, both read in-process from the repo-root `.env` by the tool's
own factory: `OPS_REPORTS_TOKEN` (read) and `OPS_VERDICTS_TOKEN` (write). The
split is deliberate — a sweep holds only the read token, and a leak of it moves
no rows. **Never `source .env`, never put a token on a command line**
(credential-hygiene.md). `AG_OPS_BASE_URL` overrides the target
(`https://www.aigranthelper.com` by default) for a staging check.

## Step 1 — sweep

```bash
$AGTRIAGE sweep
```

It pulls the manifest from `/internal/ops/reports/`, then every report the
manifest names — no hardcoded report list, so a report AG adds appears here the
day it ships.

**Exit codes carry meaning — do not collapse them.**

- **0** — a measured answer. Either a queue, or `AG ops queues current —
  nothing awaiting a verdict.` **followed by every report's `scanned` count.**
  A clean sweep always shows its working; a bare "ok" would be indistinguishable
  from a sweep that never asked.
- **1** — could not look. The seam is down, timed out, throttled, answered a
  problem-details 503 naming a dead source — **or its contract drifted**. The
  consumer pins the producer's `contract_version` major and asserts the envelope
  keys; a mismatch is a red exit naming what moved, never a best-effort read.
- **2** — not configured to look. A token missing from OverSteward's `.env`, a
  producer that answers "endpoint not configured" (its unprovisioned-token 503),
  a rejected credential, or the surface not mounted at all (404 on the manifest).

The producer's two 503s are told apart by their bodies: the unconfigured one
carries `{"error": ...}`, a dead source carries RFC 9457 problem details naming
the `source`. "Not provisioned yet" and "production is broken" must never print
the same.

## Step 2 — give every waiting item a verdict

The vocabulary is the producer's, and it is narrower than the admin's on
purpose:

| kind | verdict | when |
|---|---|---|
| `feedback` | `responded` | the submitter has been answered |
| `feedback` | `closed` | no reply needed, or the thread is done |
| `correction` | `reviewed` | the report is credible and is going to GrantSpider |
| `correction` | `rejected` | not a defect — the data is right as displayed |

**`applied` and `gs_dismissed` are token-unreachable by design.** They are
GrantSpider's acks on a correction it has already consumed, reachable only by
the GS token at `/internal/corrections/<id>/applied|gs-dismissed/`. The tool
refuses them locally, before any call — setting `applied` mails the submitter,
and an operator session must not be able to do that by accident.

## Step 3 — record the verdict, or the queue never drains

```bash
$AGTRIAGE record \
  --verdict feedback:1f4a3c2e-0000-4000-8000-000000000001:responded \
  --verdict correction:1f4a3c2e-0000-4000-8000-000000000002:rejected
```

One `--verdict KIND:ID:STATUS` per item, any number per call (the producer caps
a batch at 100). Every attempt lands in AG's append-only `ops_verdict_log`,
refusals included.

- **Partial success is normal.** Each item answers for itself: `ok` with the
  status it now sits at, or `REFUSED` with the outcome and the reason. The batch
  is not voided by one bad item.
- **Retry-safe.** The producer's state machines no-op a row already at the
  requested status, so re-running the same batch answers `recorded` again rather
  than a conflict. A half-finished record can simply be run again.
- **Exit 2 when any item failed**, so a scripted drain notices; the per-item
  lines are printed either way. Exit 1 only if the store could not be written.

Recording is the whole mechanism. An unrecorded item is at the head of the queue
again next sweep, and the queue never reaches zero. Verify before moving on:

```bash
$AGTRIAGE sweep    # the ones you ruled on should be gone
```

## Scope rules

- **Nathan's assigned work always goes first.** Surface the queue, do his work,
  then drain. A production fix must never wait behind a triage pass.
- **It is a pass, not a gate.** A partial drain recorded honestly beats a full
  drain that blocks the day.
- **A correction marked `reviewed` is a hand-off, not a fix.** The data change
  itself belongs to GrantSpider; file it there if it will not happen today.
- **Fixes flow through a worktree PR** like everything else (OS#90 — never
  commit to the primary checkout's `master`).
- **Zero LLM calls in the tool.** It decides what is *unread*; you decide what to
  do about it.

## Reporting

Two or three lines: what was scanned (the counts, not "ok"), how many items were
ruled on and how, and how many remain. On exit 1 or 2, report the breakage
loudly instead — an unreadable seam reported as a clean queue is the exact
failure this pass exists to prevent.

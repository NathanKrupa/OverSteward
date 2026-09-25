---
name: stage-health
description: "Sweep GrantSpider's stage-health ledger (`grantspider dq health --json`) and give every RED row a recorded verdict — fixed, filed, or known. Deterministic and zero-LLM. Invoke at the START of a session as the fifth session-start sweep, when Nathan says \"stage health\" / \"/stage-health\", or when asked whether the GS pipeline is still doing its work."
---

# /stage-health — is every GrantSpider stage still doing its work?

GS#2075 cut snapshot fetches from ~13–26k/day to ~1–8k/day for weeks and nothing
alerted: the nightly DQ snapshot measured *presence*, and nobody read it.
GrantSpider now keeps a per-stage **stage-health ledger** and judges it with
`grantspider dq health` (GS#2804). This sweep is the reader: it runs that
command, prints the per-stage table, and asks for a verdict on every RED row.
Nathan's requirement (2026-09-24): Claude checks it through this skill, never
through hand-rolled scripts or SQL.

Run from the **OverSteward** working tree:

```bash
export PYTHONPATH="$PWD/src"
SH=".venv/bin/python scripts/stage_health.py"
```

The sweep runs `<grantspider checkout>/.venv/bin/grantspider dq health --json`
from the checkout `registry.yaml` names as `local_path` for `grantspider` (the
one on `main`, what production runs). It is a **read-only** production read. The
producer's stderr is never echoed — a driver traceback is where a connection
string would leak.

**Fallback: `railway ssh` (OS#540).** Behind a VPN that black-holes port 5432,
the local read cannot reach Neon. When the local document is `unreadable` with
`database unreadable: OperationalError` (or `InterfaceError`), or the local
producer times out, the sweep retries **once** inside the production service:
`railway ssh --service grantspider --environment production -- grantspider dq
health --json`, run from the Railway-linked checkout (120 s timeout). Nothing
else is retried. A local `no_rows` (exit 2) is an answer, and so is any other
`unreadable`, e.g. a `thresholds:` error. Only the document's span of the
remote stdout is parsed, so Railway CLI notices never pass as the document.
Every headline names its route: `(… via: local)` or `(… via: railway-ssh)`. A
remote read measures production, not the laptop's view. Until GS#2842 ships the
thresholds and canary files in the production image, the remote route answers
exit 1 `thresholds: cannot read …`.

## Step 1 — sweep

```bash
$SH sweep            # the default 7-day window
$SH sweep --days 14
```

**The producer's exit code passes through unchanged. Do not collapse it, and
never pipe the sweep through `tail` or `head`** — the pipeline's status would be
the filter's, and a red sweep would read green.

- **0** — measured. The ledger was read; the verdict may still be RED. The
  headline names its count: `9 stages, 7 of 7 days, canaries not configured`.
  Configured canaries headline as `canaries: 12 of 12 evaluated, 0 failed`;
  any failure, an evaluated count that differs from the expected one, a failed
  count the producer did not report, or no canary rows at all reads
  `canaries RED: …` — report it even when the verdict is GREEN.
- **1** — could not read. The producer's database or thresholds, the document
  itself (no JSON, a `status`/`exit_code` that disagree, or any `schema` other
  than `1`), a producer that would not start, or the GitHub state of an issue a
  verdict points at. Also a failed `railway ssh` fallback (no `railway` CLI,
  not linked, SSH refused, a timeout, or no document on stdout). Its message
  names both the local failure and the fallback's, and it is **never** 2.
- **2** — no `stage_health` rows in the window: the `stage_health_snapshot`
  asset is not running. **This is a finding of its own, never a quiet morning** —
  report it. (Also: the registry names no GrantSpider checkout.)

## Step 2 — give every RED row a verdict

A RED row is keyed `rule@stage` (`rule` alone when it names no stage), exactly
as the sweep prints it. YELLOW findings and not-evaluated rules are context,
not queue items. Three verdicts, all terminal. **There is no `later`.**

| verdict | when | how long it holds |
|---|---|---|
| `fixed` | fixed in-session (the fix merged, or the stage restarted) | the ledger day it was recorded on — the next day's measurement is the proof, so a row still RED tomorrow is back |
| `filed` | real, bigger than this session | while the issue is open; prints `FILED→GS#n` |
| `known` | already tracked by an open issue | while the issue is open; prints `KNOWN→GS#n` |

```bash
# filed — open the issue first, labelled data-quality + ops; it is the real tracker
gh issue create --repo NathanKrupa/grantspider --label data-quality --label ops \
    --title "..." --body "..."
$SH record fetch_attempts_below_median@homepage_snapshot filed --ref GS#2851

# known — an open issue already covers it
$SH record ledger_stale known --ref GS#2805

# fixed — the ref is free text, e.g. the PR
$SH record bmf_stale@roster fixed --ref "GS PR#2860"
```

Refs are `GS#<n>`, `OS#<n>` or `AG#<n>`. A `filed`/`known` row whose issue has
closed — or never existed — is back in the queue with the reason printed beside
it. An issue whose state cannot be read fails the sweep (exit 1) rather than
printing its row as tracked.

## Step 3 — record, or the queue never drains

`record` reads the last measured sweep's snapshot, so it needs no producer call
and refuses a row that was not RED in that sweep. Verify before moving on:

```bash
$SH sweep    # the rows you ruled on now print under "Ruled on"
```

The ledger is `.claude/skills/stage-health/ledger.jsonl` (append-only; the last
line for a row wins) beside `pending.json`, the last sweep's RED rows. Both are
gitignored, local to the checkout the sweep runs in — as the Sentry ledger is.

## Scope rules

- **Nathan's assigned work always goes first.** A pass, not a gate.
- **Fixes flow through a GrantSpider worktree PR**, never the primary checkout.
- **Zero LLM calls in the tool.** It decides what is *unruled*; you decide what
  to do about it.

## Reporting

Two or three lines: the verdict and its count line, how many RED rows were ruled
on and how, how many remain. On exit 1 or 2, report the breakage loudly instead.

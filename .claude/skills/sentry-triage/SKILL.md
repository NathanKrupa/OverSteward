---
name: sentry-triage
description: "Drain the Sentry queue to inbox zero on *issues* — sweep every unresolved Sentry issue with no recorded verdict, then fix it, file it, or resolve it with a reason. Deterministic and zero-LLM. Invoke at the START of a session, when Nathan says \"sentry\" / \"/sentry-triage\", or when asked what production errors are outstanding."
---

# /sentry-triage — every Sentry issue read, none left unread

Steady state, agreed with Nathan 2026-08-10: **inbox zero on Sentry *issues*,
not zero events.** Every Sentry issue is fixed, filed as a repo issue, or
resolved-with-reason — never left sitting unread. Sentry's own email alerts are
Layer 0; they tell you something happened. This is the pull side, and it is what
makes "nothing new" a fact rather than an assumption.

Run from the **OverSteward** working tree:

```bash
export PYTHONPATH="$PWD/src"
TRIAGE=".venv/bin/python scripts/sentry_triage.py"
```

The token comes from `SENTRY_API_TOKEN`, read in-process from the repo-root
`.env` by the tool's own factory. **Never `source .env`, never put the token on a
command line** (credential-hygiene.md).

## Step 1 — sweep

```bash
$TRIAGE sweep
```

It enumerates the org's projects at runtime (no hardcoded slugs — GS#2187
renames `python` to `grantspider`), lists every unresolved issue, and subtracts
everything already ruled on.

**Exit codes carry meaning — do not collapse them.**

- **0** — a measured answer. Either a queue, or `Sentry ledger current — nothing to triage.`
- **1** — Sentry could not be read (auth, network, a 5xx). **Not** a clean sweep.
- **2** — not configured to look (`SENTRY_API_TOKEN` missing), or an impossible request.

"I found nothing" and "I could not look" print differently on purpose. A red
exit here is a finding to report, never a quiet morning.

## Step 2 — give every swept issue a verdict

One of three, all terminal. There is no "later" — "later" is how an inbox stops
being zero.

| verdict | when | what else to do |
|---|---|---|
| `fixed` | small enough to fix in-session | ship the fix, then `--resolve` |
| `filed` | real, but bigger than this session | open a repo issue in the **owning** repo with `gh` — that is the real tracker |
| `noise-resolved` | not a defect (retired cron, expected 404, third-party bot) | `--resolve` with the reason as the ref |

```bash
# filed — the repo issue is the durable record; the ledger just remembers the ruling
gh issue create --repo NathanKrupa/grantspider --title "..." --body "..."
$TRIAGE record PYTHON-9 filed --ref "GS#2166"

# fixed or noise — resolve in Sentry too
$TRIAGE record AIGRANTHELPER-2A fixed --ref "AG#1527" --resolve
$TRIAGE record AIGRANTHELPER-1W noise-resolved --ref "retired B2 cron, endpoint gone" --resolve
```

**Resolved, never ignored.** Ignoring silences a regression; resolving means the
issue reopens loudly if it happens again. `--resolve` posts the `--ref` text as a
Sentry comment first, then sets the status — so a Sentry failure can never leave
a ledger claiming a resolution that never happened.

`--resolve` is deliberately not automatic: a `filed` issue is still broken and
must stay unresolved in Sentry.

## Step 3 — record the verdict, or the queue never drains

Recording is the whole mechanism. An unrecorded issue is simply at the head of
the list again next sweep, and the queue never reaches zero — the same defect
the kaizen ledger exists to correct. `record` reads the last sweep's snapshot,
so it needs no network and works after the issue was resolved in Sentry.

Verify before moving on:

```bash
$TRIAGE sweep    # the ones you ruled on should be gone
```

## Scope rules

- **Nathan's assigned work always goes first.** Surface the queue, do his work,
  then drain. An urgent production fix must never wait behind a triage pass.
- **It is a pass, not a gate.** A partial drain recorded honestly beats a full
  drain that blocks the day.
- **Fixes flow through a worktree PR** like everything else (OS#90 — never commit
  to the primary checkout's `master`).
- **Zero LLM calls in the tool.** It decides what is *unread*; you decide what to
  do about it.

## Reporting

Two or three lines: how many were swept, how many were ruled on and how, and how
many remain. On exit 1 or 2, report the breakage loudly instead — an unreadable
Sentry reported as a clean queue is the exact failure this pass exists to
prevent.

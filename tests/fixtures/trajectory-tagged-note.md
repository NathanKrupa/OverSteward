---
date: 2026-08-21
repo: oversteward
pr: oversteward#000
branch: feat/example
issues:
  - oversteward#000
session_kind: in-session-pickup
duration: 30min
---

# Trajectory — a fully tagged note the gate must pass

## Context

A fixture standing in for a compliant note.

## Trajectory

Nothing happened; this is a fixture.

## What worked

- [tooling] Ran the gate against a fixture corpus — cheap and deterministic.

## What didn't  (cost: trivial | minutes | hours | blocked)

- [process][trivial] Nothing bit — why: fixtures do not surprise → remedy: none.

## What was learned

- [design] Tag lessons at capture time — the author knows the intent → promote: doctrine.
- [tooling] A wrapped bullet keeps its tag readable when the parser joins the
  continuation line before matching → promote: none.

## Tools

- `scripts/lint/trajectory_tags.py` [NEW] — the gate under test.

## Open threads

- None.

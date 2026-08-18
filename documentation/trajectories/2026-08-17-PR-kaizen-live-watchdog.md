---
date: 2026-08-17
repo: oversteward
pr: oversteward#TBD
branch: session/kaizen-live-watchdog
issues: []
session_kind: kaizen-promotion
duration: 15min
---

# Trajectory — kaizen: "a merged watchdog is not a live watchdog" → doctrine

## Context

Kaizen queue head (4x recurrence: OS#118, #244, #271, #351 — heartbeat
instrumentation unwired, gaudi gate merged-but-not-installed, hook matching
inert, the inert-control doctrine itself). The lesson kept being re-learned
because it lived only in trajectory notes.

## Trajectory

Promoted as the third shape in `shared/references/pr-workflow.md` § Inert
controls, alongside the two shapes landed by OS#297/#351: detection code, its
host install, and the instrumentation the probe reads are three separate
deliveries; verify all three (including a forced failure that visibly alerts)
before calling a supervisor deployed.

## What worked

- [process] The Inert-controls section is the natural accretion point for this
  family — a doctrine home that already exists gets the addition read.

## What didn't

- (nothing notable — small promotion)

## What was learned

- [process] Kaizen promotions are small; the cost is finding the *surface*,
  not writing the words.

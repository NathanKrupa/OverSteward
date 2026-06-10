---
name: Andon (observation / concern)
about: Pull the andon cord. Anyone can file this when they see something worth investigating.
title: "[andon] "
labels: andon
assignees: ""
---

<!--
The andon cord is the distributed-observation channel for the House of Krupa
estate. Anyone — Nathan, an agent, a user, a future analyst — can file an
andon to flag something worth investigating before it produces a real incident.

Andon issues are aggregated nightly into Fiscus's shared/andon.jsonl and
surfaced pre-aggregate in every relevant subject's weekly review.

Aim for short. The andon cord exists to PULL ATTENTION, not to document the
fix. Investigation happens after; the fix happens after that; the lesson lands
in shared/lessons.jsonl after that.
-->

## What did you observe?

One or two sentences. What stood out? What does not match expectation?

## Where / when?

- Subject(s) affected (pick from `Fiscus/subjects.yaml`):
- Repo / surface / endpoint:
- Time observed (UTC):
- Reproducible? yes / no / unclear

## Why it might matter

One paragraph. What's the worst case if this is a real problem? Is this a
known failure mode, a new one, or unclear?

## Severity hint

- [ ] critical — system unusable / data loss possible
- [ ] high — user-visible degradation
- [ ] medium — internal degradation, not yet user-visible
- [ ] low — curiosity / pattern worth tracking
- [ ] unknown

## What you tried (if anything)

Optional. Reproduction steps, log queries, hypotheses.

## Suggested next step

Optional. "Probably a real bug, file the postmortem if confirmed" / "Worth
querying telemetry for the past 4 weeks" / "Probably noise but worth tracking."

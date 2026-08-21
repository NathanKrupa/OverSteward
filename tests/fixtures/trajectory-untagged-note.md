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

# Trajectory — the note that must make the gate fail

This fixture is the gate's own negative proof (OS#327 rule 1): if the gate ever
returns clean against this file, the gate has stopped working. Every violation
class it carries is annotated below.

## Context

A fixture standing in for the 52%-untagged corpus.

## Trajectory

Nothing happened; this is a fixture.

## What worked

- No leading category tag at all — must be flagged.
- [tooling] This one is fine and must NOT be flagged.

## What didn't  (cost: trivial | minutes | hours | blocked)

- [oops][minutes] Category outside the vocabulary — must be flagged.

## What was learned

- [design] Category present, promote tag absent — must be flagged.
- [process] Promote target off-vocabulary → promote: sometime.
- [tooling] Promote tag buried mid-bullet → promote: memory, and then more prose.
- Neither tag present at all — must be flagged twice.
- [outcome] Fully tagged and must NOT be flagged → promote: none.

## Tools

- `scripts/lint/trajectory_tags.py` [used] — bullets here carry no tags and must not be judged.

## Open threads

- Also untagged, also outside the capture sections, also not judged.

# ABOUTME: The writer side of the governance pillar, scoped to the canonical shared/scripts/dev/ family.
# ABOUTME: plan = pure classification + gate verdicts; apply = orchestration; canon/runners = INNER readers.

"""Import from the submodule that owns the thing you want.

- ``plan`` — statuses, gate verdicts, the plan/report value objects, exit codes.
  Pure: no I/O, so every gate and classification test runs without git or gh.
- ``apply`` — one sync PR per context, over runners injected as a bundle.
- ``canon`` — canon's git history and each target's copies as they stand on origin.
- ``runners`` — one class per external system: git, gh, the target's ruff, make, the lock.
- ``render`` — text only.

Nothing is re-exported here on purpose: a flat alias surface would let a caller
reach the pure layer and the writer layer by the same import and lose the seam
the tests depend on.
"""

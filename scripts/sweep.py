ABOUTME: Identifies and proposes removal of stale persona skill files in managed repos.
ABOUTME: Only touches files matching persona-*.md naming convention (OverSteward-owned pattern).

# Phase 2 — stub. Implement after Phase 1 manual workflow is validated.
#
# Algorithm:
#   1. For each context, list files matching persona-*.md in skills_path
#   2. Cross-reference against personas_available in registry
#   3. If persona no longer listed:
#      a. Hash file vs. canonical template in shared/personas/
#      b. Hash match → propose deletion via PR (safe to sweep)
#      c. Hash differs → flag in report only (Nathan customized it — never auto-delete)

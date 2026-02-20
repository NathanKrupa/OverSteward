ABOUTME: Applies approved changes to target repos with safety gates.
ABOUTME: Never touches managed repos without dirty-tree check. Always branches, never pushes to main.

# Phase 2 — stub. Implement after Phase 1 manual workflow is validated.
#
# Safety gates (all must pass before any write):
#   1. git status on target repo — bail if dirty working tree
#   2. Check for existing oversteward/* branches/PRs — no stacking
#   3. Dry-run by default; --apply flag to execute
#   4. Always create branch: oversteward/sync-YYYY-MM-DD
#   5. Never push to main
#   6. Log all operations to reports/ before and after
#   7. Lockfile during execution

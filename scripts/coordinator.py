# ABOUTME: Orchestrator for the OverSteward sync workflow.
# ABOUTME: Runs gather -> diff -> analyze -> sow in bounded slices; invokes Claude for judgment calls.

# Phase 2 — stub. Implement after Phase 1 manual workflow is validated.
#
# Planned entry points:
#   python coordinator.py --report-only   # gather + diff + generate report, no changes
#   python coordinator.py --apply         # full pipeline with sow.py
#   python coordinator.py --sweep         # run sweep check only
#
# Deploy step (pipeline stage 1, before gather):
#   Mirror oversteward/shared/ to BOTH home directories:
#     - Windows: C:\Users\natha\.claude\shared\
#     - WSL2:    /home/natha/.claude/shared/  (writable from Windows as
#                \\wsl.localhost\Ubuntu-24.04\home\natha\.claude\shared\)
#   Both targets are mandatory — AG/GS (and any future WSL repo) resolve
#   @~/.claude/shared/... against their own host's home. See OVERSTEWARD.md
#   → "Dual-target deploy: Windows + WSL2" for rationale.

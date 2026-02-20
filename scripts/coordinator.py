ABOUTME: Orchestrator for the OverSteward sync workflow.
ABOUTME: Runs gather -> diff -> analyze -> sow in bounded slices; invokes Claude for judgment calls.

# Phase 2 — stub. Implement after Phase 1 manual workflow is validated.
#
# Planned entry points:
#   python coordinator.py --report-only   # gather + diff + generate report, no changes
#   python coordinator.py --apply         # full pipeline with sow.py
#   python coordinator.py --sweep         # run sweep check only

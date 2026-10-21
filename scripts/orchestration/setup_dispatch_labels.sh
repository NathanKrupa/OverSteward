#!/usr/bin/env bash
# ABOUTME: Idempotently upserts the dispatch label taxonomy on every dispatch_target repo + OverSteward.
# ABOUTME: Thin shell over `scripts/intake.py labels`; the taxonomy lives in oversteward.intake.labels.
#
# The label names, colours and descriptions are written once, in
# src/oversteward/intake/labels.py (DISPATCH_LABELS) — read them there. The
# repositories come from registry.yaml: every `dispatch_target: true` context,
# plus OverSteward. `gh label create --force` upserts, so a re-run is safe.
#
# Exit codes: 0 every label upserted, 1 a gh call failed (named on stderr),
# 2 the registry names no repository.
#
# Usage:
#   bash scripts/orchestration/setup_dispatch_labels.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"

# Import this tree's own source, not whatever checkout the shared venv's
# editable install happens to name.
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON" "$ROOT/scripts/intake.py" labels

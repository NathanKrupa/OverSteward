#!/usr/bin/env bash
# ABOUTME: Idempotently creates the dispatch-orchestration label taxonomy
# ABOUTME: on aigranthelper, grantspider, wphelper (closes ai-assistants #44).
#
# Labels created (5, identical across repos):
#   ready-for-agent    #0E8A16  Scoped with acceptance — can dispatch
#   needs-scoping      #FBCA04  Requires Nathan to scope before dispatch
#   needs-input        #D93F0B  Agent waiting on Nathan's answer
#   agent-in-progress  #5319E7  Agent actively working (auto-applied)
#   reject-close       #CFD3D7  Triaged as bad/obsolete
#
# Run any time: `gh label create --force` upserts (create-or-update).
#
# Usage:
#   bash scripts/orchestration/setup_dispatch_labels.sh
set -euo pipefail

REPOS=(aigranthelper grantspider wphelper)

declare -A LABELS=(
  ["ready-for-agent"]="0E8A16|Scoped with acceptance — can dispatch"
  ["needs-scoping"]="FBCA04|Requires Nathan to scope before dispatch"
  ["needs-input"]="D93F0B|Agent waiting on Nathan's answer"
  ["agent-in-progress"]="5319E7|Agent actively working (auto-applied)"
  ["reject-close"]="CFD3D7|Triaged as bad/obsolete"
)

for repo in "${REPOS[@]}"; do
  echo "=== NathanKrupa/$repo ==="
  for name in "${!LABELS[@]}"; do
    IFS='|' read -r color desc <<< "${LABELS[$name]}"
    gh label create "$name" \
      --repo "NathanKrupa/$repo" \
      --color "$color" \
      --description "$desc" \
      --force >/dev/null
    echo "  upserted: $name ($color)"
  done
done

echo
echo "Done. Dispatch-taxonomy labels are now consistent across all 3 target repos."

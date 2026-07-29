# ABOUTME: CLI for read-only governance state extraction (H2-3).
# ABOUTME: Thin wrapper — loads registry.yaml, calls oversteward.gather, emits JSON snapshot.

from __future__ import annotations

import json
import sys
from pathlib import Path


import yaml

from oversteward.gather import default_paths, gather_state


def main() -> int:
    paths = default_paths()
    registry_text = (paths["repo_root"] / "registry.yaml").read_text(encoding="utf-8")
    snapshot = gather_state(
        yaml.safe_load(registry_text), paths["canonical_shared"], paths["deploy_targets"]
    )
    json.dump(snapshot, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

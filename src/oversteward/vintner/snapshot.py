# ABOUTME: Persists the previous run's per-stage counts (gitignored JSON) so velocity Δ appears from the 2nd run on.
# ABOUTME: Pure file I/O with an injected path — no DB, no LLM. Corrupt/absent snapshot is treated as "no prior run".

from __future__ import annotations

import json
from pathlib import Path


def load_snapshot(path: Path) -> dict[str, int] | None:
    """Return the prior run's stage->count map, or None if absent/unreadable.

    A missing or corrupt snapshot is not an error — it means "first run",
    so velocity is simply omitted until the next run writes a clean snapshot.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    counts = data.get("counts") if isinstance(data, dict) else None
    if not isinstance(counts, dict):
        return None
    return {str(k): int(v) for k, v in counts.items() if isinstance(v, int)}


def save_snapshot(path: Path, counts: dict[str, int], generated_at: str) -> None:
    """Write the current run's counts for next run's velocity comparison."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"generated_at": generated_at, "counts": counts}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

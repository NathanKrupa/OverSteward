# ABOUTME: OverSteward keeps no Postgres test bench, and says so in its .worktree-bench (OS#716).
# ABOUTME: Read through the doctor's own parser, so a malformed declaration fails here, not at teardown.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCTOR = REPO_ROOT / "shared" / "scripts" / "dev" / "worktree_doctor.py"


def _doctor():
    spec = importlib.util.spec_from_file_location("worktree_doctor", DOCTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_oversteward_declares_no_bench() -> None:
    """Without it, every teardown here refuses whenever no sibling's Postgres is running."""
    doctor = _doctor()

    assert (REPO_ROOT / doctor.BENCH_DECLARATION).is_file()
    assert doctor.declares_no_bench(REPO_ROOT) is True

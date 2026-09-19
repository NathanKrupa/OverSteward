# ABOUTME: Pins the three OverSteward checks where "could not look" used to exit like "clean" (OS#384).
# ABOUTME: Each case is a negative fixture: the check must be red, or distinctly non-zero, when blind.

"""Rule 5 (`pr-workflow.md` § False greens): "found nothing" and "could not
look" must never print or exit the same.

Each test here drives the check into the blind state deliberately and asserts
the exit code is not the clean one. Without them the fix is unobservable — the
whole defect was that the blind path looked byte-for-byte like a clean run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEV = REPO_ROOT / "scripts" / "dev"
CANONICAL_DEV = REPO_ROOT / "shared" / "scripts" / "dev"

EXIT_CLEAN = 0
EXIT_COULD_NOT_LOOK = 2


def _run(script: Path, *args: str, env_extra: dict[str, str] | None = None):
    import os

    env = {**os.environ, **(env_extra or {})}
    # PATH is emptied by some cases to simulate a missing backend; keep the
    # interpreter reachable by invoking it absolutely.
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


class TestCheckWorktreeImports:
    """Finding 2: a package that cannot be imported exited 0, exactly like ok."""

    SCRIPT = DEV / "check_worktree_imports.py"

    def test_a_package_that_cannot_be_imported_is_could_not_look(self, tmp_path):
        result = _run(self.SCRIPT, "no_such_package_anywhere", "--root", str(tmp_path))
        assert result.returncode == EXIT_COULD_NOT_LOOK, result.stdout + result.stderr

    def test_the_blind_outcome_does_not_print_the_word_the_clean_one_prints(self, tmp_path):
        blind = _run(self.SCRIPT, "no_such_package_anywhere", "--root", str(tmp_path))
        clean = _run(self.SCRIPT, "pathlib", "--root", str(Path(sys.prefix)))
        assert "ok:" not in (blind.stdout + blind.stderr)
        # Whatever the clean run does, the two must be distinguishable.
        assert blind.returncode != clean.returncode or "ok:" not in clean.stdout

    def test_a_package_resolving_inside_the_tree_still_passes(self):
        result = _run(self.SCRIPT, "oversteward", "--root", str(REPO_ROOT))
        assert result.returncode == EXIT_CLEAN, result.stdout + result.stderr
        assert "ok:" in result.stdout


class TestSecretScan:
    """Finding 1: docker unavailable exited 0 — a commit certified by a scan that never ran."""

    SCRIPT = DEV / "secret_scan.py"

    def test_an_unavailable_backend_is_could_not_look_not_clean(self, tmp_path):
        # An empty PATH makes `docker` unfindable, which is the real shape of
        # the incident (a machine without docker).
        result = _run(self.SCRIPT, "--repo", str(tmp_path), env_extra={"PATH": ""})
        assert result.returncode == EXIT_COULD_NOT_LOOK, result.stdout + result.stderr

    def test_the_permissive_posture_must_be_asked_for_explicitly(self, tmp_path):
        result = _run(
            self.SCRIPT,
            "--repo",
            str(tmp_path),
            env_extra={"PATH": "", "SECRET_SCAN_ALLOW_UNAVAILABLE": "1"},
        )
        assert result.returncode == EXIT_CLEAN

    def test_the_permitted_skip_still_says_loudly_that_nothing_was_scanned(self, tmp_path):
        result = _run(
            self.SCRIPT,
            "--repo",
            str(tmp_path),
            env_extra={"PATH": "", "SECRET_SCAN_ALLOW_UNAVAILABLE": "1"},
        )
        combined = result.stdout + result.stderr
        assert "NOT SCANNED" in combined, combined

    def test_required_mode_still_fails_closed(self, tmp_path):
        result = _run(
            self.SCRIPT,
            "--repo",
            str(tmp_path),
            env_extra={"PATH": "", "SECRET_SCAN_REQUIRED": "1"},
        )
        assert result.returncode == EXIT_COULD_NOT_LOOK

    def test_required_beats_the_permissive_flag(self, tmp_path):
        """An escape hatch that can switch off CI's fail-closed is not an escape hatch."""
        result = _run(
            self.SCRIPT,
            "--repo",
            str(tmp_path),
            env_extra={
                "PATH": "",
                "SECRET_SCAN_REQUIRED": "1",
                "SECRET_SCAN_ALLOW_UNAVAILABLE": "1",
            },
        )
        assert result.returncode == EXIT_COULD_NOT_LOOK


class TestCanonicalCopiesMovedTogether:
    """Both scripts are canonical byte-copies; a one-sided edit is the drift bug."""

    @pytest.mark.parametrize("name", ["secret_scan.py", "check_worktree_imports.py"])
    def test_canonical_and_deployed_are_byte_identical(self, name):
        assert (CANONICAL_DEV / name).read_bytes() == (DEV / name).read_bytes(), (
            f"{name} drifted between shared/scripts/dev/ and scripts/dev/. "
            "Edit the canonical copy and byte-copy it across; never dual-edit."
        )

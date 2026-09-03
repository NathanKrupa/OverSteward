# ABOUTME: Pins the per-file gate's exit codes to gaudi 0.3.0's — 2 (incomplete) outranks 1 (findings).
# ABOUTME: The negative fixture is a stub gaudi that exits 2; the gate must not report it as a finding.

"""OS#461: `gaudi --exit-code` gained exit 2 = incomplete run in 0.3.0.

An incomplete run is a file the parser skipped, a pack that failed to load, or
a path no pack applies to — "could not look", not "looked and found nothing"
and not "looked and found something". The gate's own docstring already said 2
meant that, while `main()` collapsed every non-zero gaudi exit into 1, so a
skipped file was reported as a finding and a *fixed* finding would then read as
a pass while the file was still never parsed.

The stub gaudi below encodes its exit code in the name of the file it is asked
to check, so one fixture drives every combination including the mixed case.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "lint" / "gaudi_check_files.py"

_STUB_GAUDI = """#!/bin/sh
# Stand-in for `gaudi check --severity error --exit-code FILE`. The exit code
# is taken from the checked file's BASENAME so a single stub drives every case.
# Matching the whole path would be wrong: pytest names the tmp directory after
# the test, so a directory called ...test_incomplete... would tag every file
# inside it and the mixed-outcome cases would silently stop being mixed.
for target in "$@"; do :; done
case "${target##*/}" in
  *incomplete*) echo "gaudi: 1 file could not be parsed" >&2; exit 2 ;;
  *finding*)    echo "gaudi: STRUCT-010 sys.path mutation"; exit 1 ;;
  *crash*)      echo "gaudi: Traceback" >&2; exit 137 ;;
  *)            exit 0 ;;
esac
"""


@pytest.fixture
def gate_with_stub_gaudi(tmp_path):
    """A venv-shaped bin dir holding a real python and the stub gaudi.

    The gate resolves the gaudi beside its own interpreter (OS#424), so the
    only way to hand it a chosen exit code is to run it on an interpreter whose
    sibling is the stub.
    """
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python3").symlink_to(sys.executable)
    stub = venv_bin / "gaudi"
    stub.write_text(_STUB_GAUDI, encoding="utf-8")
    stub.chmod(0o755)

    def run(*names: str) -> subprocess.CompletedProcess[str]:
        paths = []
        for name in names:
            target = tmp_path / name
            target.write_text("VALUE = 1\n", encoding="utf-8")
            paths.append(str(target))
        return subprocess.run(
            [str(venv_bin / "python3"), str(GATE), *paths],
            capture_output=True,
            text=True,
            check=False,
        )

    return run


class TestExitCodePropagation:
    def test_an_incomplete_run_exits_2_not_1(self, gate_with_stub_gaudi):
        """The defect: a skipped file read as a finding."""
        result = gate_with_stub_gaudi("incomplete.py")
        assert result.returncode == 2, result.stdout + result.stderr

    def test_a_finding_still_exits_1(self, gate_with_stub_gaudi):
        result = gate_with_stub_gaudi("finding.py")
        assert result.returncode == 1, result.stdout + result.stderr

    def test_a_clean_run_exits_0(self, gate_with_stub_gaudi):
        result = gate_with_stub_gaudi("clean.py")
        assert result.returncode == 0, result.stdout + result.stderr

    @pytest.mark.parametrize(
        "names",
        [("finding.py", "incomplete.py"), ("incomplete.py", "finding.py")],
        ids=["finding-first", "incomplete-first"],
    )
    def test_incomplete_outranks_a_finding_in_either_order(
        self, gate_with_stub_gaudi, names
    ):
        """Fail closed: the worst outcome wins regardless of argv order."""
        result = gate_with_stub_gaudi(*names)
        assert result.returncode == 2, result.stdout + result.stderr

    def test_an_unrecognised_exit_code_is_treated_as_could_not_look(
        self, gate_with_stub_gaudi
    ):
        """A crashed gaudi looked at nothing; it must not read as a finding."""
        result = gate_with_stub_gaudi("crash.py")
        assert result.returncode == 2, result.stdout + result.stderr

    def test_the_incomplete_output_is_not_swallowed(self, gate_with_stub_gaudi):
        result = gate_with_stub_gaudi("incomplete.py")
        assert "could not be parsed" in result.stderr

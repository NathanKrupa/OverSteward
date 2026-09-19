# ABOUTME: Pins gaudi resolution to the interpreter's sibling and the loud exit when absent.
# ABOUTME: The negative fixture is a venv with no gaudi — the gate must be red, never silent.

"""OS#424 rec 5 / OS#429 deliverable 1: the commit-time error gate resolved the
wrong binary.

`shutil.which("gaudi")` found `~/.local/bin/gaudi`, a different installation on
a different interpreter, whose parser silently skipped files it could not read
while exiting 0 — output identical to a clean run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from oversteward.gaudi_binary import gaudi_binary

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "lint" / "gaudi_check_files.py"


@pytest.fixture
def fake_venv(tmp_path):
    """A venv-shaped bin dir whose `python` is a symlink, as every real one is."""
    system_bin = tmp_path / "usr" / "bin"
    system_bin.mkdir(parents=True)
    (system_bin / "python3.12").write_text("#!/bin/sh\n", encoding="utf-8")
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(system_bin / "python3.12")
    return venv_bin


class TestResolution:
    def test_finds_the_sibling_of_the_interpreter(self, fake_venv):
        (fake_venv / "gaudi").write_text("#!/bin/sh\n", encoding="utf-8")
        assert gaudi_binary(str(fake_venv / "python")) == fake_venv / "gaudi"

    def test_a_symlinked_interpreter_does_not_walk_out_of_the_venv(self, fake_venv):
        (fake_venv / "gaudi").write_text("#!/bin/sh\n", encoding="utf-8")
        found = gaudi_binary(str(fake_venv / "python"))
        assert found is not None and "usr/bin" not in str(found)

    def test_a_gaudi_on_path_is_never_adopted(self, fake_venv, monkeypatch, tmp_path):
        stranger = tmp_path / "elsewhere"
        stranger.mkdir()
        (stranger / "gaudi").write_text("#!/bin/sh\n", encoding="utf-8")
        monkeypatch.setenv("PATH", str(stranger))
        assert gaudi_binary(str(fake_venv / "python")) is None

    def test_this_repos_venv_has_its_own_gaudi(self):
        """The live assertion: this checkout's gate resolves a real binary."""
        found = gaudi_binary()
        assert found is not None, "no gaudi beside the running interpreter"
        assert found.parent == Path(sys.executable).parent


class TestGateBehaviour:
    def _run(self, *args, interpreter=None):
        return subprocess.run(
            [interpreter or sys.executable, str(GATE), *args],
            capture_output=True, text=True, check=False,
        )

    def test_a_clean_file_passes(self, tmp_path):
        clean = tmp_path / "clean.py"
        clean.write_text("VALUE = 1\n", encoding="utf-8")
        assert self._run(str(clean)).returncode == 0

    def test_a_file_with_an_architectural_error_is_red(self, tmp_path):
        bad = tmp_path / "bad.py"
        bad.write_text('import sys\nsys.path.insert(0, "/tmp")\n', encoding="utf-8")
        result = self._run(str(bad))
        assert result.returncode == 1, result.stdout + result.stderr

    def test_no_files_is_a_no_op(self):
        assert self._run().returncode == 0

    def test_an_interpreter_with_no_gaudi_beside_it_is_loud_not_silent(self, fake_venv):
        """The negative fixture: the gate must refuse, not certify nothing.

        A real python is symlinked into the gaudi-less venv so the gate actually
        runs and takes its own resolution path.
        """
        (fake_venv / "python3").symlink_to(sys.executable)
        target = fake_venv.parent.parent / "some.py"
        target.write_text("VALUE = 1\n", encoding="utf-8")
        result = self._run(str(target), interpreter=str(fake_venv / "python3"))
        assert result.returncode == 2, result.stdout + result.stderr
        assert "COULD NOT LOOK" in result.stderr

    def test_the_absent_case_never_shares_an_exit_code_with_a_clean_run(self, fake_venv):
        (fake_venv / "python3").symlink_to(sys.executable)
        target = fake_venv.parent.parent / "some.py"
        target.write_text("VALUE = 1\n", encoding="utf-8")
        absent = self._run(str(target), interpreter=str(fake_venv / "python3"))
        clean = self._run(str(target))
        assert absent.returncode != clean.returncode


def test_the_gate_no_longer_reaches_for_path():
    """Inert-prohibition check, on the AST rather than the text.

    A grep would match the docstring that *explains* the retired form, which is
    prose worth keeping — the rule is that the file must not CALL it.
    """
    import ast

    tree = ast.parse(GATE.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "which"
    ]
    assert not calls, (
        "gaudi_check_files.py still resolves gaudi through PATH "
        f"(line {calls[0].lineno}) — the form OS#424 retired"
    )

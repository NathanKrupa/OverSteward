# ABOUTME: Tests for scripts/backup_ready.py — the verdict text and exit code reach the caller.
# ABOUTME: Backup-Wsl.ps1 reads only the exit code, so 0/1/2 must pass through unaltered.

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import oversteward.backup
import oversteward.backup.readiness as readiness
from oversteward.backup.readiness import Blocker, Probe, ProbeError

REPO_ROOT = Path(__file__).resolve().parents[2]


def _module():
    spec = importlib.util.spec_from_file_location(
        "backup_ready", REPO_ROOT / "scripts" / "backup_ready.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _probes(*, blockers=(), error=None):
    def _run():
        if error is not None:
            raise error
        return list(blockers)

    return lambda: (Probe(name="processes", run=_run),)


@pytest.mark.parametrize(
    ("probes", "code", "headline"),
    [
        (_probes(), 0, "READY"),
        (_probes(blockers=[Blocker("processes", "pid 1422 claude")]), 1, "BUSY"),
        (_probes(error=ProbeError("ps: not found")), 2, "COULD NOT LOOK"),
    ],
)
def test_exit_code_and_verdict_pass_through(monkeypatch, capsys, probes, code, headline):
    module = _module()
    monkeypatch.setattr(readiness, "default_probes", probes)
    assert module.main([]) == code
    assert capsys.readouterr().out.startswith(headline)


def test_a_crash_outside_the_probes_is_could_not_look_never_busy(monkeypatch, capsys):
    module = _module()

    def _explode():
        raise RuntimeError("probe table broken")

    monkeypatch.setattr(readiness, "default_probes", _explode)
    assert module.main([]) == 2
    out = capsys.readouterr().out
    assert out.startswith("COULD NOT LOOK")
    assert "probe table broken" in out


def test_a_readiness_module_that_will_not_import_is_could_not_look(monkeypatch, capsys):
    # A broken shared venv, or a primary checkout that has not pulled the
    # service yet, must not exit 1 — Backup-Wsl.ps1 would log it as busy.
    module = _module()
    # Were the module reachable, these clean probes would make main() say READY.
    monkeypatch.setattr(readiness, "default_probes", _probes())
    monkeypatch.setitem(sys.modules, "oversteward.backup.readiness", None)
    monkeypatch.delattr(oversteward.backup, "readiness")
    assert module.main([]) == 2
    assert capsys.readouterr().out.startswith("COULD NOT LOOK")

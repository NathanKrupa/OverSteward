# ABOUTME: Tests for scripts/backup_ready.py — the verdict text and exit code reach the caller.
# ABOUTME: Backup-Wsl.ps1 reads only the exit code, so 0/1/2 must pass through unaltered.

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

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
    monkeypatch.setattr(module, "default_probes", probes)
    assert module.main([]) == code
    assert capsys.readouterr().out.startswith(headline)


def test_a_crash_outside_the_probes_is_could_not_look_never_busy(monkeypatch, capsys):
    module = _module()

    def _explode():
        raise RuntimeError("probe table broken")

    monkeypatch.setattr(module, "default_probes", _explode)
    assert module.main([]) == 2
    out = capsys.readouterr().out
    assert out.startswith("COULD NOT LOOK")
    assert "probe table broken" in out

# ABOUTME: Tests for scripts/service_liveness.py — registry parsing and exit-code mapping.
# ABOUTME: The three exit codes are the contract: measured / could-not-look / misconfigured.

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from oversteward.liveness.config import projects_from_registry

REPO_ROOT = Path(__file__).resolve().parents[2]

_EXIT_OK = 0
_EXIT_COULD_NOT_LOOK = 1
_EXIT_MISCONFIGURED = 2


def _module():
    spec = importlib.util.spec_from_file_location(
        "service_liveness", REPO_ROOT / "scripts" / "service_liveness.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestProjectsFromRegistry:
    def test_reads_only_contexts_carrying_a_railway_block(self):
        refs = projects_from_registry(
            {
                "contexts": [
                    {
                        "id": "with_railway",
                        "railway": {"project_id": "pid-1", "environment": "staging"},
                    },
                    {"id": "without_railway"},
                ]
            }
        )
        assert [(r.name, r.project_id, r.environment) for r in refs] == [
            ("with_railway", "pid-1", "staging")
        ]

    def test_environment_defaults_to_production(self):
        refs = projects_from_registry(
            {"contexts": [{"id": "gs", "railway": {"project_id": "pid"}}]}
        )
        assert refs[0].environment == "production"

    def test_an_empty_registry_yields_nothing(self):
        assert projects_from_registry({}) == []

    def test_the_real_registry_declares_at_least_one_project(self):
        # Guards the wiring: a registry that declares none makes the sweep exit 2
        # forever, which would read as "configured and clean".
        module = _module()
        assert projects_from_registry(module.load_registry()) != []


class TestExitCodes:
    def test_misconfigured_when_nothing_is_configured(self, monkeypatch):
        module = _module()
        monkeypatch.setattr(module, "projects_from_registry", lambda *_a, **_k: [])
        assert module.main([]) == _EXIT_MISCONFIGURED

    def test_could_not_look_when_railway_is_unreadable(self, monkeypatch):
        module = _module()
        from oversteward.liveness.client import RailwayUnavailableError

        def _explode(*_a, **_k):
            raise RailwayUnavailableError("railway exited 1")

        monkeypatch.setattr(module, "sweep", _explode)
        assert module.main([]) == _EXIT_COULD_NOT_LOOK

    def test_measured_answer_when_the_sweep_reads(self, monkeypatch, capsys):
        module = _module()
        from oversteward.liveness.models import LivenessReport, ServiceState

        monkeypatch.setattr(
            module,
            "sweep",
            lambda *_a, **_k: LivenessReport(
                states=(ServiceState("gs", "web", "SUCCESS", False),)
            ),
        )
        assert module.main([]) == _EXIT_OK
        # A clean estate states how many it checked, never a bare "ok".
        assert "1 service(s) accounted for" in capsys.readouterr().out

    @pytest.mark.parametrize(
        ("a", "b"), [(_EXIT_OK, _EXIT_COULD_NOT_LOOK), (_EXIT_COULD_NOT_LOOK, _EXIT_MISCONFIGURED)]
    )
    def test_the_three_codes_stay_distinct(self, a, b):
        assert a != b

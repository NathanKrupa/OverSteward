# ABOUTME: Tests for the liveness sweep service — reading projects, and refusing to guess.
# ABOUTME: The "could not look" vs "found nothing" distinction is the contract under test.

from __future__ import annotations

import json

import pytest

from oversteward.liveness.check import ProjectRef, sweep
from oversteward.liveness.client import (
    RailwayConfigError,
    RailwayUnavailableError,
    read_project,
)
from oversteward.liveness.models import Health

_GS = ProjectRef(name="grantspider", project_id="pid-1")
_AG = ProjectRef(name="aigranthelper", project_id="pid-2")


def _reader(mapping):
    def _read(name, _project_id, _environment):
        return mapping[name]
    return _read


class TestSweep:
    def test_combines_every_project(self):
        from oversteward.liveness.models import ServiceState

        report = sweep(
            [_GS, _AG],
            reader=_reader(
                {
                    "grantspider": (ServiceState("grantspider", "web", "SUCCESS", False),),
                    "aigranthelper": (ServiceState("aigranthelper", "cron", "CRASHED", True),),
                }
            ),
        )
        assert len(report.states) == 2
        assert [s.name for s in report.findings] == ["cron"]

    def test_no_projects_is_a_misconfiguration_not_a_clean_estate(self):
        with pytest.raises(RailwayConfigError):
            sweep([])

    def test_an_unreadable_project_propagates_rather_than_being_skipped(self):
        def _explode(_name, _pid, _env):
            raise RailwayUnavailableError("railway exited 1")

        # A partial sweep reported as complete is the failure this instrument removes.
        with pytest.raises(RailwayUnavailableError):
            sweep([_GS], reader=_explode)


class TestReadProject:
    def test_maps_the_cli_payload_onto_states(self):
        payload = json.dumps(
            [{"name": "web", "status": "SUCCESS", "deploymentStopped": False}]
        )
        states = read_project("gs", "pid", "production", runner=lambda _cmd: payload)
        assert states[0].project == "gs"
        assert states[0].health is Health.RUNNING

    def test_passes_both_project_and_environment(self):
        # --project without --environment makes the CLI fall back to the cwd's
        # linked project, which would silently sweep the wrong estate.
        seen: dict = {}

        def _runner(cmd):
            seen["cmd"] = list(cmd)
            return "[]"

        read_project("gs", "pid-1", "staging", runner=_runner)
        assert "--project" in seen["cmd"] and "pid-1" in seen["cmd"]
        assert "--environment" in seen["cmd"] and "staging" in seen["cmd"]

    def test_unparseable_json_is_unavailable_not_empty(self):
        with pytest.raises(RailwayUnavailableError):
            read_project("gs", "pid", "production", runner=lambda _cmd: "not json")

    def test_a_non_list_payload_is_unavailable(self):
        with pytest.raises(RailwayUnavailableError):
            read_project("gs", "pid", "production", runner=lambda _cmd: '{"error": "nope"}')

    def test_missing_fields_do_not_crash_the_sweep(self):
        states = read_project("gs", "pid", "production", runner=lambda _cmd: "[{}]")
        assert states[0].name == "<unnamed>"
        assert states[0].health is Health.UNKNOWN

# ABOUTME: Tests for the liveness sweep service — reading projects, and refusing to guess.
# ABOUTME: The "could not look" vs "found nothing" distinction is the contract under test.

from __future__ import annotations

import json

import pytest

from oversteward.liveness.check import ProjectRef, crash_line, sweep
from oversteward.liveness.client import (
    RailwayConfigError,
    RailwayUnavailableError,
    read_final_line,
    read_project,
)
from oversteward.liveness.models import Health, ServiceState

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
        assert states[0].deployment_id == ""

    def test_carries_the_latest_deployment_id(self):
        payload = json.dumps([{"name": "cron", "status": "CRASHED", "deploymentId": "dep-9"}])
        states = read_project("gs", "pid", "production", runner=lambda _cmd: payload)
        assert states[0].deployment_id == "dep-9"


def _log(*messages):
    return "\n".join(json.dumps({"message": m, "level": "error"}) for m in messages) + "\n"


_CRASHED = ServiceState("aigranthelper", "cron", "CRASHED", True, deployment_id="dep-9")


class TestReadFinalLine:
    def test_the_last_non_blank_message_is_the_final_line(self):
        raw = _log("starting", "Traceback ...", "CommandError: it broke", "   ")
        line = read_final_line("pid", "production", _CRASHED, runner=lambda _cmd: raw)
        assert line == "CommandError: it broke"

    def test_reads_that_deployments_logs_in_that_project_and_environment(self):
        seen: dict = {}

        def _runner(cmd):
            seen["cmd"] = list(cmd)
            return _log("x")

        read_final_line("pid-2", "staging", _CRASHED, runner=_runner)
        cmd = seen["cmd"]
        assert cmd[:3] == ["railway", "logs", "dep-9"]
        assert "--deployment" in cmd and "--json" in cmd and "--lines" in cmd
        assert cmd[cmd.index("--project") + 1] == "pid-2"
        assert cmd[cmd.index("--environment") + 1] == "staging"
        assert cmd[cmd.index("--service") + 1] == "cron"

    def test_no_log_lines_is_unavailable_not_an_empty_crash(self):
        with pytest.raises(RailwayUnavailableError, match="no log lines"):
            read_final_line("pid", "production", _CRASHED, runner=lambda _cmd: _log("", " "))

    def test_an_unparseable_log_line_is_unavailable(self):
        with pytest.raises(RailwayUnavailableError, match="unparseable"):
            read_final_line("pid", "production", _CRASHED, runner=lambda _cmd: "not json\n")

    def test_a_state_with_no_deployment_is_unavailable_without_asking_railway(self):
        def _runner(_cmd):
            raise AssertionError("railway was asked")

        state = ServiceState("aigranthelper", "cron", "CRASHED", True)
        with pytest.raises(RailwayUnavailableError, match="no deployment"):
            read_final_line("pid", "production", state, runner=_runner)


class TestCrashLine:
    def test_reads_the_states_own_project_and_environment(self):
        seen: list = []

        def _reader(project_id, environment, state):
            seen.append((project_id, environment, state))
            return "boom"

        project = ProjectRef(name="aigranthelper", project_id="pid-2", environment="staging")
        assert crash_line(project, _CRASHED, reader=_reader) == "boom"
        assert seen == [("pid-2", "staging", _CRASHED)]

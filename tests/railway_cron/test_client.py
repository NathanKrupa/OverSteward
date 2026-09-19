# ABOUTME: Tests for the Railway connector — what goes on argv vs stdin, and how a GraphQL error surfaces.
# ABOUTME: subprocess.run is replaced by a recorder; the CLI is never launched.

from __future__ import annotations

import json
import subprocess

import pytest

from oversteward.railway_cron import client
from oversteward.railway_cron.client import RailwayUnavailableError

_PATCH = {"services": {"new-1": {"variables": {"GSC_CREDENTIALS_JSON": {"value": '{"private_key":"hunter2"}'}}}}}


class _Recorder:
    """Stands in for subprocess.run: records argv and stdin, answers with a scripted result."""

    def __init__(self, stdout: str, *, returncode: int = 0, stderr: str = ""):
        self.calls: list[tuple[list[str], str | None]] = []
        self._result = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)

    def __call__(self, command, *, input=None, **_kwargs):
        self.calls.append((list(command), input))
        return self._result


class TestThePatchTravelsOnStdin:
    def test_argv_carries_the_stdin_marker_and_no_variable_value(self, monkeypatch):
        recorder = _Recorder(json.dumps({"data": {"environmentPatchCommit": "commit-1"}}))
        monkeypatch.setattr(client.subprocess, "run", recorder)

        client.apply_patch("env-1", _PATCH, message="m")

        argv, stdin = recorder.calls[0]
        assert "@-" in argv
        assert "hunter2" not in " ".join(argv)
        assert stdin is not None and "hunter2" in stdin
        assert json.loads(stdin)["patch"] == _PATCH

    def test_a_read_puts_its_variables_on_argv_and_nothing_on_stdin(self, monkeypatch):
        recorder = _Recorder(json.dumps({"data": {"environment": {"config": {"services": {}}}}}))
        monkeypatch.setattr(client.subprocess, "run", recorder)

        client.read_environment_config("env-1")

        argv, stdin = recorder.calls[0]
        assert stdin is None
        assert "decryptVariables: true" in argv[2]


class TestGraphQLErrorsSurface:
    def test_allow_errors_is_passed_so_the_message_is_readable(self, monkeypatch):
        recorder = _Recorder(json.dumps({"data": None, "errors": [{"message": "Project not found"}]}))
        monkeypatch.setattr(client.subprocess, "run", recorder)

        with pytest.raises(RailwayUnavailableError, match="Project not found"):
            client.read_project("0000")
        assert "--allow-errors" in recorder.calls[0][0]

    def test_a_non_zero_exit_relays_stderr_and_never_stdout(self, monkeypatch):
        recorder = _Recorder('{"secret":"hunter2"}', returncode=1, stderr="Unauthorized. Please login")
        monkeypatch.setattr(client.subprocess, "run", recorder)

        with pytest.raises(RailwayUnavailableError) as raised:
            client.read_project("p1")
        assert "Unauthorized" in str(raised.value)
        assert "hunter2" not in str(raised.value)

    def test_a_non_zero_exit_with_empty_stderr_still_never_relays_stdout(self, monkeypatch):
        recorder = _Recorder('{"secret":"hunter2"}', returncode=1, stderr="")
        monkeypatch.setattr(client.subprocess, "run", recorder)

        with pytest.raises(RailwayUnavailableError) as raised:
            client.read_project("p1")
        assert "hunter2" not in str(raised.value)

    def test_unreadable_json_is_an_error_not_an_empty_project(self, monkeypatch):
        monkeypatch.setattr(client.subprocess, "run", _Recorder("not json"))
        with pytest.raises(RailwayUnavailableError, match="unreadable JSON"):
            client.read_project("p1")

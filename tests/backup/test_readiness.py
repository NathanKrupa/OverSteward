# ABOUTME: Tests for the backup readiness service — busy, ready, and "could not look" verdicts.
# ABOUTME: Probes take an injected command runner, so no real process, unit or container is read.

from __future__ import annotations

from pathlib import Path

import pytest

from oversteward.backup.readiness import (
    EXIT_BUSY,
    EXIT_COULD_NOT_LOOK,
    EXIT_READY,
    ESTATE_JOB_UNITS,
    Blocker,
    Probe,
    ProbeError,
    assess,
    claude_processes,
    default_probes,
    docker_containers,
    render,
    run_command,
    systemd_jobs,
)


def _runner(output: str, calls: list | None = None):
    def _run(argv):
        if calls is not None:
            calls.append(list(argv))
        return output

    return _run


def _failing_runner(message: str):
    def _run(_argv):
        raise ProbeError(message)

    return _run


# --- the process probe ------------------------------------------------------

_PS_IDLE = """\
      1 systemd         /sbin/init
    412 bash            -bash
    977 python          /home/natha/OverSteward/.venv/bin/python scripts/backup_ready.py
   1040 code            /home/natha/.vscode-server/bin/code --open claude-notes.md
"""


class TestClaudeProcesses:
    def test_an_idle_box_has_no_blockers(self):
        assert claude_processes(run=_runner(_PS_IDLE)) == []

    def test_a_claude_cli_session_is_named_by_pid_and_command(self):
        ps = _PS_IDLE + "   1422 claude          /home/natha/.local/bin/claude --resume abc\n"
        blockers = claude_processes(run=_runner(ps))
        assert len(blockers) == 1
        assert blockers[0].probe == "processes"
        assert "1422" in blockers[0].detail
        assert "/home/natha/.local/bin/claude --resume abc" in blockers[0].detail

    def test_claude_is_matched_by_argv0_when_comm_differs(self):
        ps = _PS_IDLE + "   1500 MainThread      /home/natha/.local/bin/claude -p dream\n"
        blockers = claude_processes(run=_runner(ps))
        assert [b.detail.split()[1] for b in blockers] == ["1500"]

    def test_node_running_claude_code_is_a_session(self):
        ps = _PS_IDLE + (
            "   2001 node            node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js\n"
        )
        blockers = claude_processes(run=_runner(ps))
        assert len(blockers) == 1
        assert "2001" in blockers[0].detail

    def test_node_running_something_else_is_not_a_session(self):
        ps = _PS_IDLE + "   2002 node            node /home/natha/site/server.js\n"
        assert claude_processes(run=_runner(ps)) == []

    def test_a_mention_of_claude_in_an_argument_is_not_a_session(self):
        # The editor line in _PS_IDLE opens "claude-notes.md"; only the program counts.
        ps = _PS_IDLE + "   2003 grep            grep claude\n"
        assert claude_processes(run=_runner(ps)) == []

    def test_reads_pid_comm_and_full_args(self):
        calls: list = []
        claude_processes(run=_runner(_PS_IDLE, calls))
        assert calls == [["ps", "-eo", "pid=,comm=,args="]]

    def test_an_unreadable_process_table_raises(self):
        with pytest.raises(ProbeError):
            claude_processes(run=_failing_runner("ps: not found"))

    def test_an_empty_process_table_is_unreadable_not_idle(self):
        # A box always has at least init; empty output means the read failed.
        with pytest.raises(ProbeError):
            claude_processes(run=_runner(""))


# --- the systemd probe ------------------------------------------------------


def _write_unit(unit_dir: Path, name: str, service_type: str | None) -> None:
    body = "[Unit]\nDescription=x\n\n[Service]\n"
    if service_type is not None:
        body += f"Type={service_type}\n"
    body += "ExecStart=/bin/true\n"
    (unit_dir / name).write_text(body, encoding="utf-8")


def _show(*units: tuple[str, str, str]) -> str:
    return "\n\n".join(
        f"Id={uid}\nActiveState={active}\nSubState={sub}" for uid, active, sub in units
    ) + "\n"


def _systemctl(overrides: dict[str, tuple[str, str]] | None = None, calls: list | None = None):
    """A fake ``systemctl show`` answering every queried unit, idle unless overridden."""
    overrides = overrides or {}

    def _run(argv):
        if calls is not None:
            calls.append(list(argv))
        return _show(
            *((unit, *overrides.get(unit, ("inactive", "dead"))) for unit in argv[4:])
        )

    return _run


class TestSystemdJobs:
    def test_queries_the_estate_jobs_and_local_oneshots_but_not_always_on_units(
        self, tmp_path
    ):
        _write_unit(tmp_path, "vintage-press.service", "oneshot")
        _write_unit(tmp_path, "operator-supervisor.service", "simple")
        _write_unit(tmp_path, "implicit-simple.service", None)
        _write_unit(tmp_path, "nightly.timer", None)
        calls: list = []
        systemd_jobs(run=_systemctl(calls=calls), unit_dir=tmp_path)
        assert len(calls) == 1
        argv = calls[0]
        assert argv[:4] == ["systemctl", "--user", "show", "--property=Id,ActiveState,SubState"]
        queried = set(argv[4:])
        assert set(ESTATE_JOB_UNITS) <= queried
        assert "vintage-press.service" in queried
        assert "operator-supervisor.service" not in queried
        assert "implicit-simple.service" not in queried
        assert "nightly.timer" not in queried

    def test_the_estate_job_units_are_the_three_named_jobs(self):
        assert set(ESTATE_JOB_UNITS) == {
            "sync-repos.service",
            "dream-cycle.service",
            "sentry-triage.service",
        }

    def test_all_jobs_idle_is_no_blocker(self, tmp_path):
        output = _show(
            ("sync-repos.service", "inactive", "dead"),
            ("dream-cycle.service", "inactive", "dead"),
            ("sentry-triage.service", "failed", "failed"),
        )
        assert systemd_jobs(run=_runner(output), unit_dir=tmp_path) == []

    def test_a_running_oneshot_is_activating_and_blocks(self, tmp_path):
        run = _systemctl({"dream-cycle.service": ("activating", "start")})
        blockers = systemd_jobs(run=run, unit_dir=tmp_path)
        assert [b.probe for b in blockers] == ["systemd"]
        assert "dream-cycle.service" in blockers[0].detail
        assert "activating" in blockers[0].detail

    def test_an_active_running_unit_blocks(self, tmp_path):
        run = _systemctl({"sentry-triage.service": ("active", "running")})
        blockers = systemd_jobs(run=run, unit_dir=tmp_path)
        assert len(blockers) == 1
        assert "sentry-triage.service" in blockers[0].detail

    def test_a_finished_oneshot_that_remains_after_exit_does_not_block(self, tmp_path):
        run = _systemctl({"sync-repos.service": ("active", "exited")})
        assert systemd_jobs(run=run, unit_dir=tmp_path) == []

    def test_a_missing_unit_directory_still_checks_the_estate_jobs(self, tmp_path):
        calls: list = []
        systemd_jobs(run=_systemctl(calls=calls), unit_dir=tmp_path / "absent")
        assert set(calls[0][4:]) == set(ESTATE_JOB_UNITS)

    def test_a_running_local_oneshot_blocks(self, tmp_path):
        _write_unit(tmp_path, "vintage-press.service", "oneshot")
        run = _systemctl({"vintage-press.service": ("activating", "start")})
        blockers = systemd_jobs(run=run, unit_dir=tmp_path)
        assert [b.detail.split()[0] for b in blockers] == ["vintage-press.service"]

    def test_an_unreachable_user_manager_raises(self, tmp_path):
        with pytest.raises(ProbeError):
            systemd_jobs(run=_failing_runner("Failed to connect to bus"), unit_dir=tmp_path)

    def test_output_missing_a_queried_unit_is_unreadable(self, tmp_path):
        # systemctl show answers every unit it is asked about, even absent ones;
        # a short answer means the read was not what we asked for.
        output = _show(("sync-repos.service", "inactive", "dead"))
        with pytest.raises(ProbeError):
            systemd_jobs(run=_runner(output), unit_dir=tmp_path)


# --- the docker probe -------------------------------------------------------


class TestDockerContainers:
    def test_no_running_containers_is_no_blocker(self):
        assert docker_containers(run=_runner("")) == []

    def test_each_running_container_is_named(self):
        blockers = docker_containers(run=_runner("a1b2c3 gs-postgres\nd4e5f6 ag-redis\n"))
        assert [b.probe for b in blockers] == ["docker", "docker"]
        assert "gs-postgres" in blockers[0].detail
        assert "ag-redis" in blockers[1].detail

    def test_lists_only_running_containers(self):
        calls: list = []
        docker_containers(run=_runner("", calls))
        assert calls == [["docker", "ps", "--format", "{{.ID}} {{.Names}}"]]

    def test_an_unreachable_daemon_raises(self):
        with pytest.raises(ProbeError):
            docker_containers(run=_failing_runner("Cannot connect to the Docker daemon"))


# --- the command runner -----------------------------------------------------


class TestRunCommand:
    def test_returns_stdout_on_success(self):
        assert run_command(["printf", "hello"]) == "hello"

    def test_a_missing_tool_is_a_probe_error(self):
        with pytest.raises(ProbeError, match="not found"):
            run_command(["definitely-not-a-real-tool-581"])

    def test_a_nonzero_exit_is_a_probe_error_carrying_stderr(self):
        with pytest.raises(ProbeError, match="boom"):
            run_command(["sh", "-c", "echo boom >&2; exit 3"])


# --- assessing and rendering ------------------------------------------------


def _probe(name, blockers=(), error: Exception | None = None):
    def _run():
        if error is not None:
            raise error
        return list(blockers)

    return Probe(name=name, run=_run)


class TestAssess:
    def test_all_probes_clean_is_ready(self):
        report = assess([_probe("processes"), _probe("systemd"), _probe("docker")])
        assert report.exit_code == EXIT_READY == 0

    def test_any_blocker_is_busy(self):
        report = assess(
            [_probe("processes", [Blocker("processes", "pid 9 claude")]), _probe("docker")]
        )
        assert report.exit_code == EXIT_BUSY == 1
        assert report.blockers == (Blocker("processes", "pid 9 claude"),)

    def test_a_probe_error_is_could_not_look(self):
        report = assess([_probe("processes"), _probe("docker", error=ProbeError("no daemon"))])
        assert report.exit_code == EXIT_COULD_NOT_LOOK == 2
        assert report.failures[0].probe == "docker"
        assert "no daemon" in report.failures[0].reason

    def test_an_unexpected_exception_in_a_probe_is_could_not_look_not_a_crash(self):
        report = assess([_probe("processes", error=RuntimeError("parse fell over"))])
        assert report.exit_code == EXIT_COULD_NOT_LOOK

    def test_could_not_look_outranks_busy(self):
        # A sweep that could not see everything must say so even when it saw a blocker.
        report = assess(
            [
                _probe("processes", [Blocker("processes", "pid 9 claude")]),
                _probe("docker", error=ProbeError("no daemon")),
            ]
        )
        assert report.exit_code == EXIT_COULD_NOT_LOOK
        assert report.blockers

    def test_a_failing_probe_does_not_stop_the_others(self):
        report = assess(
            [
                _probe("processes", error=ProbeError("ps missing")),
                _probe("docker", [Blocker("docker", "c1 gs-postgres")]),
            ]
        )
        assert report.blockers == (Blocker("docker", "c1 gs-postgres"),)

    def test_no_probes_is_could_not_look_not_ready(self):
        assert assess([]).exit_code == EXIT_COULD_NOT_LOOK

    def test_default_probes_cover_processes_systemd_and_docker(self):
        assert [p.name for p in default_probes()] == ["processes", "systemd", "docker"]


class TestRender:
    def test_ready_names_the_probes_it_checked(self):
        text = render(assess([_probe("processes"), _probe("systemd"), _probe("docker")]))
        assert text.startswith("READY")
        assert "3 probes" in text
        for name in ("processes", "systemd", "docker"):
            assert name in text

    def test_busy_names_every_blocker(self):
        text = render(
            assess(
                [
                    _probe("processes", [Blocker("processes", "pid 1422 claude --resume")]),
                    _probe("docker", [Blocker("docker", "container a1 gs-postgres")]),
                ]
            )
        )
        assert text.startswith("BUSY")
        assert "pid 1422 claude --resume" in text
        assert "container a1 gs-postgres" in text

    def test_verdict_headlines_are_ascii_for_the_windows_log(self):
        # PowerShell decodes wsl.exe output in the OEM code page; non-ASCII garbles.
        reports = [
            assess([_probe("processes")]),
            assess([_probe("processes", [Blocker("processes", "pid 9 claude")])]),
            assess([_probe("docker", error=ProbeError("docker: not found"))]),
        ]
        for report in reports:
            assert render(report).isascii(), render(report)

    def test_could_not_look_names_the_probe_and_reason_and_any_blocker(self):
        text = render(
            assess(
                [
                    _probe("processes", [Blocker("processes", "pid 9 claude")]),
                    _probe("docker", error=ProbeError("docker: not found")),
                ]
            )
        )
        assert text.startswith("COULD NOT LOOK")
        assert "docker" in text and "docker: not found" in text
        assert "pid 9 claude" in text

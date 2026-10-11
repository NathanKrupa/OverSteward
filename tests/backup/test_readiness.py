# ABOUTME: Tests for the backup readiness service — busy, ready, and "could not look" verdicts.
# ABOUTME: Probes take an injected command runner, so no real process, unit or container is read.

from __future__ import annotations

import os
from pathlib import Path

import pytest

from oversteward.backup.readiness import (
    EXIT_BUSY,
    EXIT_COULD_NOT_LOOK,
    EXIT_READY,
    ESTATE_JOB_UNITS,
    TRANSCRIPT_WINDOW_SECONDS,
    Blocker,
    Probe,
    ProbeError,
    assess,
    claude_processes,
    default_probes,
    long_run_processes,
    docker_containers,
    project_dir_name,
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
      1     0 systemd         /sbin/init
    412     1 bash            -bash
    977     1 python          /home/natha/OverSteward/.venv/bin/python scripts/backup_ready.py
   1040     1 code            /home/natha/.vscode-server/bin/code --open claude-notes.md
"""


_NOW = 1_800_000_000.0
_SESSION_CWD = "/home/natha/OverSteward"
_SESSION_PROJECT = "-home-natha-OverSteward"

#: Measured 2026-10-11 on the live box: the shell Claude Code's Bash tool
#: spawns as a direct child of the session process.
_TOOL_SHELL = (
    "/bin/bash -c source /home/natha/.claude/shell-snapshots/snapshot-bash-1791727454865-357zp5.sh"
    " 2>/dev/null || true && eval 'pytest'"
)


def _transcript(projects: Path, project: str, age_minutes: float, name: str = "s.jsonl") -> Path:
    path = projects / project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")
    stamp = _NOW - age_minutes * 60
    os.utime(path, (stamp, stamp))
    return path


def _session(tmp_path: Path, age_minutes: float | None = None, cwd: str = _SESSION_CWD) -> dict:
    """Keyword arguments for claude_processes: a projects dir and a fixed clock and cwd."""
    projects = tmp_path / "projects"
    projects.mkdir(exist_ok=True)
    if age_minutes is not None:
        _transcript(projects, _SESSION_PROJECT, age_minutes)
    return {"projects_dir": projects, "read_cwd": lambda _pid: cwd, "now": lambda: _NOW}


_CLAUDE_ROW = "   1422     1 claude          /home/natha/.local/bin/claude --resume abc\n"


class TestClaudeProcesses:
    def test_an_idle_box_has_no_blockers(self, tmp_path):
        assert claude_processes(run=_runner(_PS_IDLE), **_session(tmp_path)) == []

    def test_a_working_claude_cli_session_is_named_by_pid_and_command(self, tmp_path):
        blockers = claude_processes(run=_runner(_PS_IDLE + _CLAUDE_ROW), **_session(tmp_path, 1))
        assert len(blockers) == 1
        assert blockers[0].probe == "processes"
        assert "1422" in blockers[0].detail
        assert "/home/natha/.local/bin/claude --resume abc" in blockers[0].detail

    def test_claude_is_matched_by_argv0_when_comm_differs(self, tmp_path):
        ps = _PS_IDLE + "   1500     1 MainThread      /home/natha/.local/bin/claude -p dream\n"
        blockers = claude_processes(run=_runner(ps), **_session(tmp_path, 1))
        assert [b.detail.split()[1] for b in blockers] == ["1500"]

    def test_node_running_claude_code_is_a_session(self, tmp_path):
        ps = _PS_IDLE + (
            "   2001     1 node            node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js\n"
        )
        blockers = claude_processes(run=_runner(ps), **_session(tmp_path, 1))
        assert len(blockers) == 1
        assert "2001" in blockers[0].detail

    def test_node_running_something_else_is_not_a_session(self, tmp_path):
        ps = _PS_IDLE + "   2002     1 node            node /home/natha/site/server.js\n"
        assert claude_processes(run=_runner(ps), **_session(tmp_path, 1)) == []

    def test_a_mention_of_claude_in_an_argument_is_not_a_session(self, tmp_path):
        # The editor line in _PS_IDLE opens "claude-notes.md"; only the program counts.
        ps = _PS_IDLE + "   2003     1 grep            grep claude\n"
        assert claude_processes(run=_runner(ps), **_session(tmp_path, 1)) == []

    def test_reads_pid_ppid_comm_and_full_args(self, tmp_path):
        calls: list = []
        claude_processes(run=_runner(_PS_IDLE, calls), **_session(tmp_path))
        assert calls == [["ps", "-eo", "pid=,ppid=,comm=,args="]]

    def test_an_unreadable_process_table_raises(self, tmp_path):
        with pytest.raises(ProbeError):
            claude_processes(run=_failing_runner("ps: not found"), **_session(tmp_path))

    def test_an_empty_process_table_is_unreadable_not_idle(self, tmp_path):
        # A box always has at least init; empty output means the read failed.
        with pytest.raises(ProbeError):
            claude_processes(run=_runner(""), **_session(tmp_path))


class TestClaudeSessionActivity:
    """An open session is busy only while it is working; an idle one is resumable."""

    def test_an_idle_open_session_is_not_busy(self, tmp_path):
        # Stale transcript, no tool child: the conversation is on disk.
        ps = _PS_IDLE + _CLAUDE_ROW
        assert claude_processes(run=_runner(ps), **_session(tmp_path, 600)) == []

    def test_a_transcript_written_within_the_window_is_busy(self, tmp_path):
        blockers = claude_processes(run=_runner(_PS_IDLE + _CLAUDE_ROW), **_session(tmp_path, 29))
        assert len(blockers) == 1
        assert "transcript" in blockers[0].detail

    def test_a_transcript_just_past_the_window_is_idle(self, tmp_path):
        assert claude_processes(run=_runner(_PS_IDLE + _CLAUDE_ROW), **_session(tmp_path, 31)) == []

    def test_the_window_is_thirty_minutes(self):
        assert TRANSCRIPT_WINDOW_SECONDS == 30 * 60

    def test_the_newest_transcript_decides_not_the_first_found(self, tmp_path):
        kwargs = _session(tmp_path, 600)
        _transcript(kwargs["projects_dir"], _SESSION_PROJECT, 2, name="zz-newer.jsonl")
        assert len(claude_processes(run=_runner(_PS_IDLE + _CLAUDE_ROW), **kwargs)) == 1

    def test_a_fresh_subagent_transcript_makes_the_session_busy(self, tmp_path):
        kwargs = _session(tmp_path, 600)
        _transcript(
            kwargs["projects_dir"],
            f"{_SESSION_PROJECT}/abc-session/subagents",
            3,
            name="agent-a1.jsonl",
        )
        assert len(claude_processes(run=_runner(_PS_IDLE + _CLAUDE_ROW), **kwargs)) == 1

    def test_a_fresh_non_transcript_file_does_not_count(self, tmp_path):
        kwargs = _session(tmp_path, 600)
        _transcript(kwargs["projects_dir"], _SESSION_PROJECT, 1, name="notes.md")
        assert claude_processes(run=_runner(_PS_IDLE + _CLAUDE_ROW), **kwargs) == []

    def test_another_projects_fresh_transcript_does_not_count(self, tmp_path):
        kwargs = _session(tmp_path, 600)
        _transcript(kwargs["projects_dir"], "-home-natha-grantspider", 1)
        assert claude_processes(run=_runner(_PS_IDLE + _CLAUDE_ROW), **kwargs) == []

    def test_a_running_tool_shell_child_is_busy_even_with_a_stale_transcript(self, tmp_path):
        ps = _PS_IDLE + _CLAUDE_ROW + f"   1600  1422 bash            {_TOOL_SHELL}\n"
        blockers = claude_processes(run=_runner(ps), **_session(tmp_path, 600))
        assert len(blockers) == 1
        assert "1422" in blockers[0].detail
        assert "tool command pid 1600" in blockers[0].detail

    def test_a_tool_shell_grandchild_is_busy(self, tmp_path):
        ps = (
            _PS_IDLE
            + _CLAUDE_ROW
            + "   1600  1422 node            node helper.js\n"
            + f"   1601  1600 bash            {_TOOL_SHELL}\n"
        )
        assert len(claude_processes(run=_runner(ps), **_session(tmp_path, 600))) == 1

    def test_a_tool_shell_under_another_process_does_not_make_this_session_busy(self, tmp_path):
        ps = _PS_IDLE + _CLAUDE_ROW + f"   1600   412 bash            {_TOOL_SHELL}\n"
        assert claude_processes(run=_runner(ps), **_session(tmp_path, 600)) == []

    def test_a_long_lived_mcp_helper_child_is_not_work(self, tmp_path):
        # An aigranthelper session runs stdio MCP servers (.mcp.json) for its whole life.
        ps = (
            _PS_IDLE
            + _CLAUDE_ROW
            + "   1600  1422 npm exec        npm exec @playwright/mcp@latest\n"
            + "   1601  1422 railway         railway mcp\n"
        )
        assert claude_processes(run=_runner(ps), **_session(tmp_path, 600)) == []

    def test_an_unreadable_cwd_is_could_not_look(self, tmp_path):
        def _no_cwd(_pid):
            raise PermissionError("cannot readlink /proc/1422/cwd")

        kwargs = _session(tmp_path, 600) | {"read_cwd": _no_cwd}
        with pytest.raises(ProbeError, match="1422"):
            claude_processes(run=_runner(_PS_IDLE + _CLAUDE_ROW), **kwargs)

    def test_a_missing_project_dir_is_could_not_look_not_idle(self, tmp_path):
        # A wrongly derived name would otherwise read every working session as idle.
        with pytest.raises(ProbeError, match=_SESSION_PROJECT):
            claude_processes(run=_runner(_PS_IDLE + _CLAUDE_ROW), **_session(tmp_path))

    def test_a_project_dir_without_transcripts_is_could_not_look(self, tmp_path):
        kwargs = _session(tmp_path)
        (kwargs["projects_dir"] / _SESSION_PROJECT).mkdir()
        with pytest.raises(ProbeError, match="no transcript"):
            claude_processes(run=_runner(_PS_IDLE + _CLAUDE_ROW), **kwargs)

    def test_a_tool_shell_needs_no_transcript_lookup(self, tmp_path):
        # Busy on the process evidence alone: nothing more needs reading.
        ps = _PS_IDLE + _CLAUDE_ROW + f"   1600  1422 bash            {_TOOL_SHELL}\n"
        assert len(claude_processes(run=_runner(ps), **_session(tmp_path))) == 1


class TestProjectDirName:
    @pytest.mark.parametrize(
        ("cwd", "name"),
        [
            ("/home/natha/OverSteward", "-home-natha-OverSteward"),
            ("/home/natha/Fiscus", "-home-natha-Fiscus"),
            (
                "/home/natha/OverSteward/.claude/worktrees/dispatch-490",
                "-home-natha-OverSteward--claude-worktrees-dispatch-490",
            ),
            ("/tmp/gs_h3 bench", "-tmp-gs-h3-bench"),
        ],
        ids=["repo", "case-kept", "dot-dir", "underscore-space"],
    )
    def test_names_the_dir_the_way_claude_code_does(self, cwd, name):
        assert project_dir_name(cwd) == name


# --- the detached long-run probe -------------------------------------------


class TestLongRunProcesses:
    def test_an_idle_box_has_no_blockers(self):
        assert long_run_processes(run=_runner(_PS_IDLE)) == []

    @pytest.mark.parametrize(
        "args",
        [
            "/home/natha/gs-crawl/.venv/bin/python -m grantspider irs drain-990pf --resume",
            "/home/natha/grantspider/.venv/bin/grantspider crawl websites --cohort cf",
            "bash /home/natha/grantspider/scripts/supervisor.sh",
            "/home/natha/grantspider/scripts/supervisor.sh --agents 16",
            "uv run --no-sync grantspider enrich-drain",
            "nohup /usr/bin/python3 -u -m grantspider crawl",
            "python -m grantspider.cli crawl",
            "env GS_AGENTS=16 grantspider enrich-drain",
        ],
        ids=[
            "python-m",
            "console-script",
            "bash-script",
            "script",
            "uv-run",
            "nohup-python",
            "python-m-submodule",
            "env-assignment",
        ],
    )
    def test_a_detached_grantspider_run_is_named(self, args):
        ps = _PS_IDLE + f"   5001     1 python          {args}\n"
        blockers = long_run_processes(run=_runner(ps))
        assert [b.probe for b in blockers] == ["long-runs"]
        assert blockers[0].detail == f"pid 5001 {args}"

    @pytest.mark.parametrize(
        "args",
        [
            "grep grantspider",
            "less /home/natha/grantspider/README.md",
            "/home/natha/.vscode-server/bin/node --folder /home/natha/grantspider",
            "python /home/natha/OverSteward/scripts/backup_ready.py",
            "tail -f /home/natha/grantspider/supervisor.sh.log",
        ],
        ids=["grep", "pager", "editor", "other-python", "tail-log"],
    )
    def test_a_mention_of_grantspider_is_not_a_run(self, args):
        ps = _PS_IDLE + f"   5002     1 x               {args}\n"
        assert long_run_processes(run=_runner(ps)) == []

    def test_an_unreadable_process_table_raises(self):
        with pytest.raises(ProbeError):
            long_run_processes(run=_failing_runner("ps: not found"))

    def test_an_empty_process_table_is_unreadable_not_idle(self):
        with pytest.raises(ProbeError):
            long_run_processes(run=_runner(""))


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

    def test_a_hung_tool_times_out_as_a_probe_error(self, monkeypatch):
        # A wedged `docker ps` must become "could not look", not a hung gate.
        import oversteward.backup.readiness as readiness

        monkeypatch.setattr(readiness, "_COMMAND_TIMEOUT_SECONDS", 0.2)
        with pytest.raises(ProbeError, match="timed out"):
            run_command(["sleep", "5"])

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

    def test_default_probes_cover_sessions_long_runs_systemd_and_docker(self):
        assert [p.name for p in default_probes()] == [
            "processes",
            "long-runs",
            "systemd",
            "docker",
        ]


class TestRender:
    def test_ready_claims_only_what_the_probes_checked(self):
        # READY means none of the probed work is running, not that nothing is.
        text = render(assess([_probe("processes")]))
        assert "nothing running" not in text
        assert "none of the probed work is running" in text

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

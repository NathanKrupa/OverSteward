# ABOUTME: MIDDLE service deciding whether a full WSL export may run — ready, busy, or could not look.
# ABOUTME: Probes take an injected command runner; a probe that cannot read is never a "ready".

"""Decide whether ``wsl --export`` may run now.

``wsl --export`` terminates every process in the distro to take its snapshot, so
the Windows-side ``Backup-Wsl.ps1`` asks this first and exports only on a clean
``0``. Four things count as work in progress: a *working* Claude Code session, a
detached estate long run (a GrantSpider drain, crawl or supervisor), an estate
job service mid-run, and a running docker container. Work outside those four,
such as an arbitrary ``nohup`` job, is not seen.

A Claude Code session left open but idle is not work: its conversation is on
disk and resumes after the export. A session is working when either

* a transcript in its project dir under ``~/.claude/projects/`` (recursive, so
  subagent transcripts count) was written within the last 30 minutes, or
* it has a descendant running a tool command. Measured on the live box
  2026-10-11: an idle VS Code session has no child processes at all, and one
  running a Bash tool command has a ``bash -c source
  ~/.claude/shell-snapshots/snapshot-bash-*.sh ...`` child. Long-lived helpers,
  such as the stdio MCP servers in aigranthelper's ``.mcp.json``, are children
  too, so "has a child" is not the test; the tool-shell signature is.

A session whose cwd or project dir cannot be read is "could not look", never idle.

Exit codes, the contract ``Backup-Wsl.ps1`` reads:

* **0** — ready: every probe read, none of the probed work is running.
* **1** — busy: every blocker found is named.
* **2** — could not look: a probe failed or its tool is missing. This outranks
  busy, because a sweep that did not see everything must say so. "Found
  nothing" and "could not look" never print or exit the same.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

EXIT_READY = 0
EXIT_BUSY = 1
EXIT_COULD_NOT_LOOK = 2

#: The estate's scheduled job services. Each is a oneshot that does real work
#: while active; a unit that is always on (operator-supervisor) is not a job.
ESTATE_JOB_UNITS: tuple[str, ...] = (
    "sync-repos.service",
    "dream-cycle.service",
    "sentry-triage.service",
)

#: Programs the estate runs detached for hours. Matched on the program a
#: command line runs, never on a mention of the name in its arguments.
ESTATE_LONG_RUNS = frozenset({"grantspider", "supervisor.sh"})

#: Interpreters and launchers looked through to find the program they run.
_LAUNCHERS = frozenset({"bash", "sh", "uv", "run", "nohup", "setsid", "env"})

DEFAULT_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

#: Where Claude Code keeps one transcript directory per working directory.
DEFAULT_PROJECTS_DIR = Path.home() / ".claude" / "projects"

#: A session whose transcripts were all written longer ago than this is idle.
TRANSCRIPT_WINDOW_SECONDS = 30 * 60

#: In the command line of the shell Claude Code's Bash tool spawns for each
#: command; absent from its long-lived helpers.
TOOL_SHELL_MARKER = "/.claude/shell-snapshots/snapshot-"

_COMMAND_TIMEOUT_SECONDS = 30
_BUSY_STATES = frozenset({"active", "activating"})


class ProbeError(Exception):
    """A probe could not read what it looks at — the "could not look" case."""


@dataclass(frozen=True, slots=True)
class Blocker:
    """One piece of work in progress that an export would kill."""

    probe: str
    detail: str


@dataclass(frozen=True, slots=True)
class ProbeFailure:
    """A probe that could not read, and why."""

    probe: str
    reason: str


@dataclass(frozen=True, slots=True)
class Probe:
    """A named check returning the blockers it found; raises when it cannot look."""

    name: str
    run: Callable[[], Sequence[Blocker]]


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    """The combined verdict of every probe."""

    probes: tuple[str, ...]
    blockers: tuple[Blocker, ...]
    failures: tuple[ProbeFailure, ...]

    @property
    def exit_code(self) -> int:
        if self.failures:
            return EXIT_COULD_NOT_LOOK
        if self.blockers:
            return EXIT_BUSY
        return EXIT_READY


Runner = Callable[[Sequence[str]], str]


def run_command(argv: Sequence[str]) -> str:
    """Run ``argv`` and return its stdout; raise :class:`ProbeError` on any failure."""
    try:
        proc = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ProbeError(f"{argv[0]}: not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"{argv[0]}: timed out after {_COMMAND_TIMEOUT_SECONDS}s") from exc
    if proc.returncode != 0:
        reason = proc.stderr.strip() or proc.stdout.strip() or "no output"
        raise ProbeError(f"{argv[0]} exited {proc.returncode}: {reason}")
    return proc.stdout


def _is_claude_session(comm: str, args: str) -> bool:
    argv0 = args.split(maxsplit=1)[0] if args else ""
    if comm == "claude" or os.path.basename(argv0) == "claude":
        return True
    return comm == "node" and "claude-code" in args


@dataclass(frozen=True, slots=True)
class _Proc:
    pid: str
    ppid: str
    comm: str
    args: str


def _process_table(run: Runner) -> list[_Proc]:
    """Every process; an empty table is an unreadable one."""
    output = run(["ps", "-eo", "pid=,ppid=,comm=,args="])
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        raise ProbeError("ps returned an empty process table")
    table = []
    for line in lines:
        parts = line.split(maxsplit=3)
        if len(parts) < 3:
            continue
        table.append(_Proc(parts[0], parts[1], parts[2], parts[3] if len(parts) > 3 else parts[2]))
    return table


def read_process_cwd(pid: str) -> str:
    """The working directory of a live process, from ``/proc``."""
    return os.readlink(f"/proc/{pid}/cwd")


def project_dir_name(cwd: str) -> str:
    """The ``~/.claude/projects/`` entry Claude Code names after a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def _tool_shell(session: _Proc, table: Sequence[_Proc]) -> _Proc | None:
    """A descendant of ``session`` running a tool command, if any."""
    children: dict[str, list[_Proc]] = {}
    for proc in table:
        children.setdefault(proc.ppid, []).append(proc)
    pending = list(children.get(session.pid, []))
    while pending:
        proc = pending.pop()
        if TOOL_SHELL_MARKER in proc.args:
            return proc
        pending.extend(children.get(proc.pid, []))
    return None


def _transcript_age(
    pid: str,
    projects_dir: Path,
    read_cwd: Callable[[str], str],
    now: Callable[[], float],
) -> float:
    """Seconds since the session's newest transcript was written; raises if unreadable."""
    try:
        cwd = read_cwd(pid)
    except OSError as exc:
        raise ProbeError(f"pid {pid}: cannot read cwd: {exc}") from exc
    project = projects_dir / project_dir_name(cwd)
    if not project.is_dir():
        raise ProbeError(f"pid {pid}: no project dir {project} for cwd {cwd}")
    try:
        newest = max((p.stat().st_mtime for p in project.rglob("*.jsonl")), default=None)
    except OSError as exc:
        raise ProbeError(f"pid {pid}: cannot read transcripts in {project}: {exc}") from exc
    if newest is None:
        raise ProbeError(f"pid {pid}: no transcript in {project}")
    return now() - newest


def claude_processes(
    run: Runner = run_command,
    *,
    projects_dir: Path = DEFAULT_PROJECTS_DIR,
    read_cwd: Callable[[str], str] = read_process_cwd,
    now: Callable[[], float] = time.time,
) -> list[Blocker]:
    """Every *working* Claude Code session, named by PID, command line and evidence."""
    table = _process_table(run)
    blockers = []
    for proc in table:
        if not _is_claude_session(proc.comm, proc.args):
            continue
        shell = _tool_shell(proc, table)
        if shell is not None:
            evidence = f"running tool command pid {shell.pid}"
        else:
            age = _transcript_age(proc.pid, projects_dir, read_cwd, now)
            if age >= TRANSCRIPT_WINDOW_SECONDS:
                continue
            evidence = f"transcript written {int(age // 60)} min ago"
        blockers.append(Blocker("processes", f"pid {proc.pid} {proc.args} ({evidence})"))
    return blockers


def _program(args: str) -> str:
    """The program a command line runs, looking through interpreters and launchers.

    ``python -m grantspider``, ``uv run grantspider``, ``nohup python -u -m
    grantspider`` and ``bash supervisor.sh`` all name their program past the
    launcher; ``grep grantspider`` names ``grep``.
    """
    tokens = args.split()
    i = 0
    while i < len(tokens):
        name = os.path.basename(tokens[i])
        if name == "-m" and i + 1 < len(tokens):
            return tokens[i + 1].split(".")[0]
        if (
            name.startswith("-")
            or name.startswith("python")
            or name in _LAUNCHERS
            or "=" in name
        ):
            i += 1
            continue
        return name
    return ""


def long_run_processes(run: Runner = run_command) -> list[Blocker]:
    """Every detached estate long run (a GS drain, crawl or supervisor), by PID and command.

    These are launched with ``setsid --fork nohup`` so they outlive the Claude
    session that started them, which puts them outside the session probe.
    """
    return [
        Blocker("long-runs", f"pid {proc.pid} {proc.args}")
        for proc in _process_table(run)
        if _program(proc.args) in ESTATE_LONG_RUNS
    ]


def _service_type(unit_file: Path) -> str:
    """The unit's ``Type=``; systemd's default when absent is ``simple``."""
    service_type = "simple"
    for line in unit_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() == "Type":
            service_type = value.strip()
    return service_type


def _job_units(unit_dir: Path) -> list[str]:
    units = list(ESTATE_JOB_UNITS)
    if unit_dir.is_dir():
        for unit_file in sorted(unit_dir.glob("*.service")):
            if unit_file.name not in units and _service_type(unit_file) == "oneshot":
                units.append(unit_file.name)
    return units


def _parse_show(output: str) -> dict[str, dict[str, str]]:
    states: dict[str, dict[str, str]] = {}
    for block in output.strip().split("\n\n"):
        fields = dict(
            line.split("=", 1) for line in block.strip().splitlines() if "=" in line
        )
        if "Id" in fields:
            states[fields["Id"]] = fields
    return states


def systemd_jobs(run: Runner = run_command, unit_dir: Path = DEFAULT_UNIT_DIR) -> list[Blocker]:
    """Every estate job service, or local oneshot, that is running right now."""
    units = _job_units(unit_dir)
    output = run(
        ["systemctl", "--user", "show", "--property=Id,ActiveState,SubState", *units]
    )
    states = _parse_show(output)
    missing = [unit for unit in units if unit not in states]
    if missing:
        raise ProbeError(f"systemctl show did not report {', '.join(missing)}")
    blockers = []
    for unit in units:
        active, sub = states[unit].get("ActiveState", ""), states[unit].get("SubState", "")
        # A oneshot with RemainAfterExit= reads "active/exited" once it has finished.
        if active in _BUSY_STATES and sub != "exited":
            blockers.append(Blocker("systemd", f"{unit} {active}/{sub}"))
    return blockers


def docker_containers(run: Runner = run_command) -> list[Blocker]:
    """Every running docker container, named by ID and name."""
    output = run(["docker", "ps", "--format", "{{.ID}} {{.Names}}"])
    return [
        Blocker("docker", f"container {line.strip()}")
        for line in output.splitlines()
        if line.strip()
    ]


def default_probes() -> tuple[Probe, ...]:
    """The probes the backup gate runs, against the live box."""
    return (
        Probe(name="processes", run=claude_processes),
        Probe(name="long-runs", run=long_run_processes),
        Probe(name="systemd", run=systemd_jobs),
        Probe(name="docker", run=docker_containers),
    )


def assess(probes: Sequence[Probe]) -> ReadinessReport:
    """Run every probe; one that fails is recorded and never stops the others."""
    blockers: list[Blocker] = []
    failures: list[ProbeFailure] = []
    if not probes:
        failures.append(ProbeFailure("assess", "no probes configured"))
    for probe in probes:
        try:
            blockers.extend(probe.run())
        except Exception as exc:  # noqa: BLE001 — any probe fault is "could not look"
            failures.append(ProbeFailure(probe.name, f"{type(exc).__name__}: {exc}"))
    return ReadinessReport(
        probes=tuple(p.name for p in probes),
        blockers=tuple(blockers),
        failures=tuple(failures),
    )


def render(report: ReadinessReport) -> str:
    """One headline naming the verdict, then every failure and blocker."""
    code = report.exit_code
    if code == EXIT_READY:
        return (
            f"READY - {len(report.probes)} probes clean ({', '.join(report.probes)}); "
            "none of the probed work is running"
        )
    if code == EXIT_BUSY:
        lines = [f"BUSY - {len(report.blockers)} blocker(s); export would kill them"]
    else:
        lines = [f"COULD NOT LOOK - {len(report.failures)} probe(s) failed; no export"]
        lines += [f"  could not look: {f.probe}: {f.reason}" for f in report.failures]
    lines += [f"  busy: {b.probe}: {b.detail}" for b in report.blockers]
    return "\n".join(lines)


__all__ = [
    "DEFAULT_PROJECTS_DIR",
    "DEFAULT_UNIT_DIR",
    "ESTATE_JOB_UNITS",
    "EXIT_BUSY",
    "EXIT_COULD_NOT_LOOK",
    "EXIT_READY",
    "ESTATE_LONG_RUNS",
    "TOOL_SHELL_MARKER",
    "TRANSCRIPT_WINDOW_SECONDS",
    "Blocker",
    "Probe",
    "ProbeError",
    "ProbeFailure",
    "ReadinessReport",
    "assess",
    "claude_processes",
    "long_run_processes",
    "project_dir_name",
    "read_process_cwd",
    "default_probes",
    "docker_containers",
    "render",
    "run_command",
    "systemd_jobs",
]

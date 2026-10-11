# ABOUTME: MIDDLE service deciding whether a full WSL export may run — ready, busy, or could not look.
# ABOUTME: Probes take an injected command runner; a probe that cannot read is never a "ready".

"""Decide whether ``wsl --export`` may run now.

``wsl --export`` terminates every process in the distro to take its snapshot, so
the Windows-side ``Backup-Wsl.ps1`` asks this first and exports only on a clean
``0``. Three things count as work in progress: a running Claude Code session, an
estate job service mid-run, and a running docker container.

Exit codes, the contract ``Backup-Wsl.ps1`` reads:

* **0** — ready: every probe read, nothing is running.
* **1** — busy: every blocker found is named.
* **2** — could not look: a probe failed or its tool is missing. This outranks
  busy, because a sweep that did not see everything must say so. "Found
  nothing" and "could not look" never print or exit the same.
"""

from __future__ import annotations

import os
import subprocess
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

DEFAULT_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

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


def claude_processes(run: Runner = run_command) -> list[Blocker]:
    """Every running Claude Code session, named by PID and command line."""
    output = run(["ps", "-eo", "pid=,comm=,args="])
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        raise ProbeError("ps returned an empty process table")
    blockers = []
    for line in lines:
        parts = line.split(maxsplit=2)
        if len(parts) < 2:
            continue
        pid, comm = parts[0], parts[1]
        args = parts[2] if len(parts) > 2 else comm
        if _is_claude_session(comm, args):
            blockers.append(Blocker("processes", f"pid {pid} {args}"))
    return blockers


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
            "nothing running"
        )
    if code == EXIT_BUSY:
        lines = [f"BUSY - {len(report.blockers)} blocker(s); export would kill them"]
    else:
        lines = [f"COULD NOT LOOK - {len(report.failures)} probe(s) failed; no export"]
        lines += [f"  could not look: {f.probe}: {f.reason}" for f in report.failures]
    lines += [f"  busy: {b.probe}: {b.detail}" for b in report.blockers]
    return "\n".join(lines)


__all__ = [
    "DEFAULT_UNIT_DIR",
    "ESTATE_JOB_UNITS",
    "EXIT_BUSY",
    "EXIT_COULD_NOT_LOOK",
    "EXIT_READY",
    "Blocker",
    "Probe",
    "ProbeError",
    "ProbeFailure",
    "ReadinessReport",
    "assess",
    "claude_processes",
    "default_probes",
    "docker_containers",
    "render",
    "run_command",
    "systemd_jobs",
]

# ABOUTME: INNER connector for Railway — reads service deployment state and crash lines via the CLI.
# ABOUTME: Transport only; what a state means for liveness is decided in models.py.

"""Read Railway service state, and the final log line of a deployment.

The CLI is the estate's standard connection procedure for Railway (the MCP
servers churn transport), so this shells out to ``railway service list --json``
and ``railway logs --json`` rather than reaching for the GraphQL API.

``--project`` requires ``--environment``, which is why both are always passed:
without the pair the CLI falls back to whatever directory it was invoked from,
and a sweep that silently reports on the wrong project is worse than one that
refuses.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence

from oversteward.liveness.models import ServiceState

#: Raised when Railway cannot be read — the "I could not look" case, which must
#: never be reported as "I found nothing".
class RailwayUnavailableError(RuntimeError):
    """Railway could not be reached, or answered with something unreadable."""


class RailwayConfigError(RuntimeError):
    """No projects were configured, so there was nothing to look at."""


_TIMEOUT_SECONDS = 120


def _run(command: Sequence[str]) -> str:
    """Execute ``command``, returning stdout; never echo the command on failure.

    ``check=True`` would re-raise argv into the traceback, which is how a token
    on a command line reaches a transcript. Nothing here carries a secret today,
    but the estate's credential-hygiene rule is about the shape, not the case.
    """
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            list(command),
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise RailwayUnavailableError("railway CLI not found on PATH") from None
    except subprocess.TimeoutExpired:
        raise RailwayUnavailableError(
            f"railway did not answer within {_TIMEOUT_SECONDS}s"
        ) from None
    if completed.returncode != 0:
        raise RailwayUnavailableError(
            f"railway exited {completed.returncode} running `railway {command[1]}`"
        )
    return completed.stdout


def read_project(
    project_name: str,
    project_id: str,
    environment: str,
    *,
    runner: Callable[[Sequence[str]], str] = _run,
) -> tuple[ServiceState, ...]:
    """Every service's deployment state for one project/environment."""
    raw = runner(
        [
            "railway",
            "service",
            "list",
            "--json",
            "--project",
            project_id,
            "--environment",
            environment,
        ]
    )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RailwayUnavailableError(
            f"railway sent unparseable JSON for {project_name}: {exc}"
        ) from None
    if not isinstance(payload, list):
        raise RailwayUnavailableError(
            f"railway sent {type(payload).__name__}, expected a list, for {project_name}"
        )
    return tuple(
        ServiceState(
            project=project_name,
            name=str(service.get("name") or "<unnamed>"),
            status=str(service.get("status") or ""),
            stopped=bool(service.get("deploymentStopped")),
            deployment_id=str(service.get("deploymentId") or ""),
        )
        for service in payload
    )


#: Log lines fetched to find the final one: enough to step over trailing blank lines.
_LOG_LINES = 20


def _messages(raw: str, service: str) -> list[str]:
    messages = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            raise RailwayUnavailableError(f"railway sent an unparseable log line for {service}") from None
        message = entry.get("message") if isinstance(entry, dict) else None
        if isinstance(message, str) and message.strip():
            messages.append(message.strip())
    return messages


def read_final_line(
    project_id: str,
    environment: str,
    state: ServiceState,
    *,
    runner: Callable[[Sequence[str]], str] = _run,
) -> str:
    """The last non-blank log message of the service's latest deployment.

    For a crashed one-shot this is normally the line it died on (measured on
    one crashed cron service, not on every shape of crash); a signature that
    misses it fails toward the alarm, never a mute. A deployment with no
    id, or logs with no message at all, raise rather than return an empty line:
    an empty line would read as "a crash that matched nothing", not as "could
    not look".
    """
    if not state.deployment_id:
        raise RailwayUnavailableError(f"railway named no deployment for {state.name}")
    raw = runner(
        [
            "railway",
            "logs",
            state.deployment_id,
            "--deployment",
            "--json",
            "--lines",
            str(_LOG_LINES),
            "--project",
            project_id,
            "--environment",
            environment,
            "--service",
            state.name,
        ]
    )
    messages = _messages(raw, state.name)
    if not messages:
        raise RailwayUnavailableError(f"railway sent no log lines for {state.name}")
    return messages[-1]


__all__ = ["RailwayConfigError", "RailwayUnavailableError", "read_final_line", "read_project"]

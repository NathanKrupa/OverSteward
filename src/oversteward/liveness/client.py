# ABOUTME: INNER connector for Railway — reads service deployment state via the CLI.
# ABOUTME: Transport only; what a state means for liveness is decided in models.py.

"""Read Railway service state.

The CLI is the estate's standard connection procedure for Railway (the MCP
servers churn transport), so this shells out to ``railway service list --json``
rather than reaching for the GraphQL API.

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
            f"railway exited {completed.returncode} reading services"
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
        )
        for service in payload
    )


__all__ = ["RailwayConfigError", "RailwayUnavailableError", "read_project"]

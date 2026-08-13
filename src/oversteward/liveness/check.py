# ABOUTME: MIDDLE service for the liveness sweep — reads every configured project, one report.
# ABOUTME: Refuses rather than reports when it could not look; that distinction is the point.

"""Sweep every configured Railway project for services that are not running.

The estate's observability is otherwise entirely pull-on-errors, and a process
that is not running raises no error. `embedding` sat CRASHED for two days in
August 2026 while the Sentry sweep reported inbox zero throughout (OS#353).

The contract this holds to is the one the Sentry pass already states: **"I found
nothing" and "I could not look" must never print the same.** A project that
cannot be read raises rather than contributing an empty list.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from oversteward.liveness.client import RailwayConfigError, read_project
from oversteward.liveness.models import LivenessReport


@dataclass(frozen=True, slots=True)
class ProjectRef:
    """A Railway project/environment pair the sweep should cover."""

    name: str
    project_id: str
    environment: str = "production"


def sweep(
    projects: Sequence[ProjectRef],
    *,
    reader: Callable[..., tuple] = read_project,
) -> LivenessReport:
    """Read every project and return one report.

    Raises :class:`RailwayConfigError` when asked to sweep nothing — an empty
    configuration is a misconfiguration, not a clean estate. Any project that
    cannot be read propagates :class:`RailwayUnavailableError` rather than being
    silently skipped: a partial sweep reported as complete is the failure mode
    this whole instrument exists to remove.
    """
    if not projects:
        raise RailwayConfigError(
            "no Railway projects configured — nothing to sweep. Add them to registry.yaml."
        )
    states: list = []
    for project in projects:
        states.extend(reader(project.name, project.project_id, project.environment))
    return LivenessReport(states=tuple(states))


__all__ = ["ProjectRef", "sweep"]

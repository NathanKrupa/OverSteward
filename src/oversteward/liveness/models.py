# ABOUTME: Typed shapes for the service-liveness sweep — one state per Railway service.
# ABOUTME: Classification lives here so the client stays a transport and the CLI stays thin.

"""What a service's deployment state means for liveness.

Railway reports a deployment ``status`` plus a ``deploymentStopped`` flag. Neither
alone answers "is this service alive": a scheduled one-shot legitimately ends
``SUCCESS`` **and** stopped, while a long-running service that is stopped is
down. :class:`Health` is that judgement, made once, here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: Railway statuses that mean the deployment ended badly.
_FAILED_STATUSES = frozenset({"CRASHED", "FAILED"})

#: Railway statuses that mean a deployment is mid-flight. Not a finding — asking
#: again in a minute is the correct response, not raising an alarm.
_IN_FLIGHT_STATUSES = frozenset(
    {"BUILDING", "DEPLOYING", "INITIALIZING", "QUEUED", "WAITING", "NEEDS_APPROVAL"}
)

#: Railway status for a deployment that came up cleanly.
_SUCCESS = "SUCCESS"


class Health(Enum):
    """The liveness verdict for one service."""

    RUNNING = "running"
    #: Ended cleanly and is stopped — the shape of a scheduled one-shot.
    COMPLETED = "completed"
    #: Ended badly. This is the finding the sweep exists to surface.
    DOWN = "down"
    #: A deployment is in progress; ask again shortly.
    IN_FLIGHT = "in-flight"
    #: A status this code has never seen. Reported, never assumed healthy —
    #: an unknown state and a good state must not print the same.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ServiceState:
    """One service's deployment state, as reported by Railway."""

    project: str
    name: str
    status: str
    stopped: bool

    @property
    def health(self) -> Health:
        if self.status in _FAILED_STATUSES:
            return Health.DOWN
        if self.status in _IN_FLIGHT_STATUSES:
            return Health.IN_FLIGHT
        if self.status == _SUCCESS:
            return Health.COMPLETED if self.stopped else Health.RUNNING
        return Health.UNKNOWN


@dataclass(frozen=True, slots=True)
class LivenessReport:
    """Every service state the sweep could read, across every project."""

    states: tuple[ServiceState, ...]

    @property
    def findings(self) -> tuple[ServiceState, ...]:
        """States an operator must act on: down, or in a state we cannot classify."""
        return tuple(s for s in self.states if s.health in (Health.DOWN, Health.UNKNOWN))


__all__ = ["Health", "LivenessReport", "ServiceState"]

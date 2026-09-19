# ABOUTME: MIDDLE layer — orchestrates one cron-service provisioning: read, plan, preview, create, commit, verify.
# ABOUTME: Railway calls are injected so the sequence is testable; a dry run touches nothing.

"""Provision a cron service, or show what provisioning would do.

The sequence is: read the project's services and environments, read the
target environment's config, build the patch against a sibling, print the
redacted preview, and — only with ``apply`` — create the service, commit the
patch, then **re-read the config and check the service carries the schedule
and every variable name**. A commit that answered is not the proof; the
read-back is.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from oversteward.railway_cron import client
from oversteward.railway_cron.plan import CronSpec, PlanError, build_patch
from oversteward.railway_cron.render import render_preview

#: A placeholder id for the dry run's preview — no service exists yet.
_PLANNED_ID = "<new>"


class VerifyError(RuntimeError):
    """The commit answered, but the re-read config does not show what was asked for."""


@dataclass(frozen=True)
class RailwayCalls:
    """The Railway operations the sequence needs, so a test can hand in fakes."""

    read_project: Callable[[str], tuple[list[dict[str, Any]], list[dict[str, Any]]]] = client.read_project
    read_config: Callable[[str], dict[str, Any]] = client.read_environment_config
    create_service: Callable[[str, str], str] = client.create_service
    apply_patch: Callable[..., None] = client.apply_patch


def provision(
    spec: CronSpec,
    *,
    project_id: str,
    environment: str,
    apply: bool,
    calls: RailwayCalls | None = None,
) -> str:
    """Plan (and with ``apply``, create and commit) the cron service; return the preview."""
    calls = calls or RailwayCalls()
    services, environments = calls.read_project(project_id)
    environment_id = _environment_id(environments, environment)
    config = calls.read_config(environment_id)
    planned = build_patch(config, services, spec, new_service_id=_PLANNED_ID)
    preview = render_preview(planned, _PLANNED_ID, spec)
    if not apply:
        return f"{preview}\n\n(dry run — nothing created; pass --apply to provision)"

    service_id = calls.create_service(project_id, spec.name)
    patch = {"services": {service_id: planned["services"][_PLANNED_ID]}}
    calls.apply_patch(environment_id, patch, message=f"provision cron {spec.name} (cloned from {spec.like})")
    _verify(calls.read_config(environment_id), service_id, spec)
    return f"{preview}\n\napplied: service {spec.name} = {service_id} in {environment}"


def _environment_id(environments: list[dict[str, Any]], name: str) -> str:
    for environment in environments:
        if environment.get("name") == name:
            return str(environment["id"])
    raise PlanError(f"no environment named {name!r} in this project")


def _verify(config: dict[str, Any], service_id: str, spec: CronSpec) -> None:
    """Refuse to report success unless the re-read config shows the schedule and every variable."""
    service = config.get("services", {}).get(service_id)
    if service is None:
        raise VerifyError(f"service {service_id} is absent from the re-read config")
    schedule = service.get("deploy", {}).get("cronSchedule")
    if schedule != spec.schedule:
        raise VerifyError(f"re-read cronSchedule is {schedule!r}, expected {spec.schedule!r}")
    missing = sorted(spec.variables.keys() - service.get("variables", {}).keys())
    if missing:
        raise VerifyError(f"re-read config lacks variables: {', '.join(missing)}")


__all__ = ["CronSpec", "PlanError", "RailwayCalls", "VerifyError", "provision"]

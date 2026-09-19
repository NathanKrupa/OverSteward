# ABOUTME: MIDDLE layer — builds the environment-config patch for a new cron service from a sibling's config.
# ABOUTME: Pure: takes the config Railway reported and a CronSpec, returns the patch; never talks to Railway.

"""Decide what a new cron service looks like.

Every AG cron service shares one shape — the same repo and branch as its
siblings, the same shared-variable references, ``restartPolicyType: NEVER``,
a start command and a schedule. Hand-building that in the dashboard is where
the drift comes from (a cron without ``SENTRY_DSN``, a cron pointed at the
wrong branch), so the patch is derived from a sibling that already runs and
only the parts that make this cron *this* cron are supplied.

The patch touches exactly one service. It never edits the sibling, never
edits shared variables, and never carries a key it was not asked for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: A cron service runs its start command to completion and exits; Railway
#: must not restart it, or a failed run loops until the next tick.
_RESTART_NEVER = "NEVER"


class PlanError(ValueError):
    """The spec cannot be turned into a patch — a name clash, a missing sibling."""


@dataclass(frozen=True)
class CronSpec:
    """What makes the new cron service distinct from the sibling it is cloned from."""

    name: str
    like: str
    start_command: str
    schedule: str
    variables: dict[str, str] = field(default_factory=dict)
    sealed: frozenset[str] = field(default_factory=frozenset)


def service_id_for(services: list[dict[str, Any]], name: str) -> str:
    """The id of the service called ``name`` in a ``railway service list`` reading."""
    for service in services:
        if service.get("name") == name:
            return str(service["id"])
    raise PlanError(f"no service named {name!r} in this project")


def adoptable_service_id(config: dict[str, Any], services: list[dict[str, Any]], name: str) -> str | None:
    """The id of an existing service called ``name`` that is still empty, else None.

    A service that exists but carries no source and no start command in this
    environment is what an earlier run leaves behind when it created the
    service and then failed to commit its config. Adopting it is the recovery
    path; a service that already *runs* under that name is a clash, and stays
    one.
    """
    for service in services:
        if service.get("name") != name:
            continue
        existing = config.get("services", {}).get(str(service["id"])) or {}
        if _is_configured(existing):
            raise PlanError(f"a service named {name!r} already exists and is configured in this environment")
        return str(service["id"])
    return None


def _is_configured(service: dict[str, Any]) -> bool:
    return bool(service.get("source")) or bool(service.get("deploy", {}).get("startCommand"))


def build_patch(
    config: dict[str, Any],
    services: list[dict[str, Any]],
    spec: CronSpec,
    *,
    new_service_id: str,
) -> dict[str, Any]:
    """The environment-config patch that configures ``new_service_id``.

    ``config`` is the environment's config (the shape ``railway environment
    config --json`` prints); ``services`` is the project's service list. The
    sibling's ``source``, ``build``, ``deploy`` and ``variables`` are copied
    verbatim — variable values included, because a ``${{shared.X}}`` reference
    and a template literal are both things the new service must carry
    unchanged — then the spec's start command, schedule and variables are laid
    over them.
    """
    adoptable_service_id(config, services, spec.name)
    sibling_id = service_id_for(services, spec.like)
    sibling = config.get("services", {}).get(sibling_id)
    if sibling is None:
        raise PlanError(f"sibling {spec.like!r} has no config in this environment")
    unreadable = sorted(
        name
        for name, entry in sibling.get("variables", {}).items()
        if entry.get("value") is None and name not in spec.variables
    )
    if unreadable:
        raise PlanError(
            f"sibling variable(s) with no readable value (sealed?): {', '.join(unreadable)} — "
            "supply each with --var-file or --var"
        )
    missing = sorted(spec.sealed - spec.variables.keys())
    if missing:
        raise PlanError(f"sealed but not set: {', '.join(missing)}")

    deploy = dict(sibling.get("deploy", {}))
    deploy.update(
        startCommand=spec.start_command,
        cronSchedule=spec.schedule,
        restartPolicyType=_RESTART_NEVER,
    )
    variables: dict[str, dict[str, Any]] = {
        name: dict(value) for name, value in sibling.get("variables", {}).items()
    }
    for name, value in spec.variables.items():
        entry: dict[str, Any] = {"value": value}
        if name in spec.sealed:
            entry["isSealed"] = True
        variables[name] = entry

    return {
        "services": {
            new_service_id: {
                "source": dict(sibling.get("source", {})),
                "build": dict(sibling.get("build", {})),
                "deploy": deploy,
                "variables": variables,
            }
        }
    }

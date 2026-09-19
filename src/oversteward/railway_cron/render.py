# ABOUTME: Renders a cron-service patch for an operator to read before it is applied.
# ABOUTME: Names every variable; prints references verbatim and literals only as a length, never a value.

from __future__ import annotations

from typing import Any

from oversteward.railway_cron.plan import CronSpec

#: A Railway variable reference (``${{shared.KEY}}``, ``${{Postgres.HOST}}``)
#: names another variable rather than holding a secret, so it is safe to show.
_REFERENCE_PREFIX = "${{"


def _describe(name: str, entry: dict[str, Any]) -> str:
    value = str(entry.get("value", ""))
    sealed = "sealed " if entry.get("isSealed") else ""
    if value.startswith(_REFERENCE_PREFIX) and value.endswith("}}"):
        shape = value
    else:
        shape = f"{sealed}literal ({len(value)} chars)"
    return f"    {name:<36} {shape}"


def render_preview(patch: dict[str, Any], service_id: str, spec: CronSpec) -> str:
    """The plan as an operator reads it: source, schedule, command, variable names."""
    service = patch["services"][service_id]
    source = service.get("source", {})
    deploy = service.get("deploy", {})
    lines = [
        f"service {spec.name} (cloned from {spec.like})",
        f"  source   {source.get('repo', '?')}@{source.get('branch', '?')}",
        f"  schedule {deploy.get('cronSchedule')}",
        f"  command  {deploy.get('startCommand')}",
        f"  restart  {deploy.get('restartPolicyType')}",
        f"  variables ({len(service.get('variables', {}))}):",
    ]
    lines.extend(_describe(name, entry) for name, entry in sorted(service.get("variables", {}).items()))
    return "\n".join(lines)

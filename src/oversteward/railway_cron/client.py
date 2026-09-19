# ABOUTME: INNER connector for Railway — reads a project's services and environments, an environment's config,
# ABOUTME: creates a service and commits a config patch. Transport only, through `railway api`; plan.py decides content.

"""Talk to Railway for the cron provisioner.

The CLI is the estate's standard connection for Railway, and ``railway api``
is the one subcommand that takes every id explicitly: ``railway environment
config`` and ``railway add`` read the *linked* project from the working
directory, so a tool built on them silently acts on whichever repo it was
launched from. Every call here names its project or environment id.

The patch travels to ``environmentPatchCommit`` as ``railway api`` variables
read from **stdin**, never as an argument: it carries variable values, and an
argv is what a process listing, a shell history and a traceback all print.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from typing import Any

_TIMEOUT_SECONDS = 120

#: A project's services and environments, by id and name.
_PROJECT = (
    "query ($id: String!) { project(id: $id) { "
    "services { edges { node { id name } } } "
    "environments { edges { node { id name } } } } }"
)

#: An environment's config — the same shape ``railway environment config --json``
#: prints. ``decryptVariables`` is what makes a ``${{shared.X}}`` reference and
#: a template literal readable so the sibling's variables can be copied verbatim.
_ENVIRONMENT_CONFIG = "query ($id: String!) { environment(id: $id) { config(decryptVariables: true) } }"

#: Creates the service in every non-fork environment of the project; its
#: config is patched afterwards, in the one environment asked for.
_CREATE_SERVICE = "mutation ($input: ServiceCreateInput!) { serviceCreate(input: $input) { id name } }"

#: Commits a config patch to one environment. ``EnvironmentConfig`` is a JSON scalar.
_PATCH_COMMIT = (
    "mutation ($environmentId: String!, $patch: EnvironmentConfig, $commitMessage: String) "
    "{ environmentPatchCommit(environmentId: $environmentId, patch: $patch, commitMessage: $commitMessage) }"
)


class RailwayUnavailableError(RuntimeError):
    """Railway could not be reached, or answered with something unreadable."""


def _run(command: Sequence[str], *, stdin: str | None = None) -> str:
    """Execute ``command`` and return stdout; never echo argv or stdin on failure."""
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            list(command),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise RailwayUnavailableError("railway CLI not found on PATH") from None
    except subprocess.TimeoutExpired:
        raise RailwayUnavailableError(f"railway did not answer within {_TIMEOUT_SECONDS}s") from None
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else "no output"
        raise RailwayUnavailableError(f"railway api exited {completed.returncode}: {tail}")
    return completed.stdout


def _query(document: str, variables: dict[str, Any], *, what: str, on_stdin: bool = False) -> dict[str, Any]:
    """Run one GraphQL document and return its ``data``; errors are loud, never partial."""
    encoded = json.dumps(variables)
    command = ["railway", "api", document, "--compact", "--variables", "@-" if on_stdin else encoded]
    text = _run(command, stdin=encoded if on_stdin else None)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RailwayUnavailableError(f"railway returned unreadable JSON for {what}: {exc}") from None
    if payload.get("errors"):
        first = payload["errors"][0]
        raise RailwayUnavailableError(f"{what} failed: {first.get('message', first)}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RailwayUnavailableError(f"{what} answered without data")
    return data


def _nodes(connection: dict[str, Any]) -> list[dict[str, Any]]:
    return [edge["node"] for edge in connection.get("edges", []) if edge.get("node")]


def read_project(project_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """``(services, environments)`` of the project — each a list of ``{id, name}``."""
    project = _query(_PROJECT, {"id": project_id}, what="project").get("project") or {}
    return _nodes(project.get("services", {})), _nodes(project.get("environments", {}))


def read_environment_config(environment_id: str) -> dict[str, Any]:
    """Every service's source, build, deploy and variables in the environment."""
    environment = _query(_ENVIRONMENT_CONFIG, {"id": environment_id}, what="environment config")
    config = (environment.get("environment") or {}).get("config")
    if not isinstance(config, dict):
        raise RailwayUnavailableError("environment config is not an object")
    return config


def create_service(project_id: str, name: str) -> str:
    """Create an empty service called ``name`` and return its id."""
    data = _query(_CREATE_SERVICE, {"input": {"projectId": project_id, "name": name}}, what="serviceCreate")
    try:
        return str(data["serviceCreate"]["id"])
    except (KeyError, TypeError):
        raise RailwayUnavailableError("serviceCreate answered without a service id") from None


def apply_patch(environment_id: str, patch: dict[str, Any], *, message: str) -> None:
    """Commit ``patch`` to the environment's config. The patch goes on stdin."""
    data = _query(
        _PATCH_COMMIT,
        {"environmentId": environment_id, "patch": patch, "commitMessage": message},
        what="environmentPatchCommit",
        on_stdin=True,
    )
    if not data.get("environmentPatchCommit"):
        raise RailwayUnavailableError("environmentPatchCommit answered without a commit id")

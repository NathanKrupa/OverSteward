# ABOUTME: Intake orchestration — which repositories intake covers, and reading their open issues.
# ABOUTME: Takes the registry and a reader as arguments; a partial read is an error, never a report.

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from oversteward.board.config import RepoRef, repos_from_registry
from oversteward.intake.models import IntakeIssue

#: The control plane's own registry id; intake covers it whether or not it is a dispatch target.
CONTROL_PLANE_ID = "oversteward"


def repos_for(registry: dict[str, Any]) -> list[RepoRef]:
    """Every dispatch-target repository plus OverSteward, each once, in registry order."""
    repos = repos_from_registry(registry)
    if any(r.id == CONTROL_PLANE_ID for r in repos):
        return repos
    control_plane = [
        c for c in registry.get("contexts") or [] if c.get("id") == CONTROL_PLANE_ID
    ]
    if not control_plane:
        raise ValueError(f"registry has no {CONTROL_PLANE_ID!r} context")
    return repos + repos_from_registry({"contexts": [{**control_plane[0], "dispatch_target": True}]})


def read_repo(repo: RepoRef, list_issues: Callable[[str], list[dict]]) -> list[IntakeIssue]:
    return [IntakeIssue.from_gh(repo.id, raw) for raw in list_issues(repo.full_name)]


def read_repos(
    repos: Iterable[RepoRef], list_issues: Callable[[str], list[dict]]
) -> list[IntakeIssue]:
    """Every open issue in every repository; the first unreadable one raises."""
    issues: list[IntakeIssue] = []
    for repo in repos:
        issues += read_repo(repo, list_issues)
    return issues

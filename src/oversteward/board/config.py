# ABOUTME: Maps registry.yaml contexts onto the GitHub repositories the board reads.
# ABOUTME: Pure — takes loaded registry data, never a path, so nothing here opens a file.

"""Which repositories the Estate Board covers.

Every context marked ``dispatch_target: true`` is on the board — the same set
``/project-status`` and ``/questions`` sweep. The GitHub ``owner/name`` comes
from the context's ``repo`` URL, not its registry ``id``: OverSteward's id is
``oversteward`` but its repository is ``NathanKrupa/OverSteward``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_GITHUB_URL = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")


@dataclass(frozen=True, slots=True)
class RepoRef:
    """One repository on the board: its registry id and its GitHub ``owner/name``."""

    id: str
    full_name: str

    @property
    def name(self) -> str:
        return self.full_name.split("/", 1)[1]


def _context_id(context: dict[str, Any]) -> str:
    return context.get("id") or context.get("name") or "<unnamed>"


def _github_ref(context: dict[str, Any]) -> RepoRef | None:
    """The context's repository, or ``None`` when its ``repo`` is not a GitHub https URL."""
    match = _GITHUB_URL.match(context.get("repo") or "")
    if match is None:
        return None
    return RepoRef(id=_context_id(context), full_name=f"{match[1]}/{match[2]}")


def repos_from_registry(registry: dict[str, Any]) -> list[RepoRef]:
    """Every dispatch-target context, in registry order."""
    refs: list[RepoRef] = []
    for context in registry.get("contexts") or []:
        if not context.get("dispatch_target"):
            continue
        ref = _github_ref(context)
        if ref is None:
            raise ValueError(
                f"dispatch target {_context_id(context)!r} has no GitHub https repo URL: "
                f"{context.get('repo')!r}"
            )
        refs.append(ref)
    return refs


def github_repos_from_registry(registry: dict[str, Any]) -> list[RepoRef]:
    """Every context whose ``repo`` is a GitHub https URL, in registry order.

    Wider than :func:`repos_from_registry`: a context need not be a dispatch
    target to ship work. A context whose ``repo`` is not a GitHub https URL has
    no pull requests to read, so it is skipped rather than refused.
    """
    refs = (_github_ref(context) for context in registry.get("contexts") or [])
    return [ref for ref in refs if ref is not None]


__all__ = ["RepoRef", "github_repos_from_registry", "repos_from_registry"]

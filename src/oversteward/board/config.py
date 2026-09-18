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


def repos_from_registry(registry: dict[str, Any]) -> list[RepoRef]:
    """Every dispatch-target context, in registry order."""
    refs: list[RepoRef] = []
    for context in registry.get("contexts") or []:
        if not context.get("dispatch_target"):
            continue
        context_id = context.get("id") or context.get("name") or "<unnamed>"
        match = _GITHUB_URL.match(context.get("repo") or "")
        if match is None:
            raise ValueError(
                f"dispatch target {context_id!r} has no GitHub https repo URL: "
                f"{context.get('repo')!r}"
            )
        refs.append(RepoRef(id=context_id, full_name=f"{match[1]}/{match[2]}"))
    return refs


__all__ = ["RepoRef", "repos_from_registry"]

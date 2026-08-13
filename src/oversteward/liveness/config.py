# ABOUTME: Maps registry.yaml contexts onto the Railway projects the sweep covers.
# ABOUTME: Pure — takes loaded registry data, never a path, so nothing here opens a file.

"""Which Railway projects the liveness sweep should read.

A context opts in by carrying a ``railway:`` block:

```yaml
    railway:
      project_id: <project-uuid>
      environment: production
```

This takes the already-loaded registry rather than a path. Reading the file is
the outer script's job against its own fixed location — a config loader that
accepts an arbitrary path is a path-traversal surface for no benefit, since
there is exactly one registry.
"""

from __future__ import annotations

from typing import Any

from oversteward.liveness.check import ProjectRef

#: Default Railway environment when a context does not name one.
DEFAULT_ENVIRONMENT = "production"


def projects_from_registry(registry: dict[str, Any]) -> list[ProjectRef]:
    """Every context carrying a ``railway:`` block, as sweepable project refs."""
    refs: list[ProjectRef] = []
    for context in registry.get("contexts") or []:
        railway = context.get("railway")
        if not railway:
            continue
        refs.append(
            ProjectRef(
                name=context.get("id") or context.get("name") or "<unnamed>",
                project_id=railway["project_id"],
                environment=railway.get("environment", DEFAULT_ENVIRONMENT),
            )
        )
    return refs


__all__ = ["DEFAULT_ENVIRONMENT", "projects_from_registry"]

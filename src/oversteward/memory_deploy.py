# ABOUTME: Mirrors the dream-cycle memory store into each machine's ~/.claude auto-load dirs.
# ABOUTME: Pure path-injectable service — encoding, registry parsing, and *.md copy/prune. No CLI.

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROJECTS_BASE = Path.home() / ".claude" / "projects"


def encode_project_dir(local_path: str) -> str:
    """Dash-encode a local checkout path the way Claude Code names its project dirs.

    Leading ``/`` becomes a leading ``-``; every other ``/`` becomes ``-``.
    Case is preserved (``/home/natha/OverSteward`` -> ``-home-natha-OverSteward``).
    """
    return local_path.replace("/", "-")


def target_project_dir(local_path: str, projects_base: Path | None = None) -> Path:
    """Return the ``~/.claude/projects/<dash-encoded>/memory`` auto-load dir for a checkout."""
    base = projects_base if projects_base is not None else DEFAULT_PROJECTS_BASE
    return base / encode_project_dir(local_path) / "memory"


def managed_targets(
    registry_path: Path, projects_base: Path | None = None
) -> dict[str, Path]:
    """Map each managed context id with a ``local_path`` to its memory auto-load dir."""
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    targets: dict[str, Path] = {}
    for ctx in data.get("contexts", []):
        local_path = ctx.get("local_path")
        if not local_path:
            continue
        targets[ctx["id"]] = target_project_dir(local_path, projects_base)
    return targets


def _copy_markdown(
    source_files: dict[str, Path],
    target_files: dict[str, Path],
    target_dir: Path,
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    written: list[str] = []
    unchanged: list[str] = []
    for name, src in source_files.items():
        src_text = src.read_text(encoding="utf-8")
        existing = target_files.get(name)
        if existing is not None and existing.read_text(encoding="utf-8") == src_text:
            unchanged.append(name)
            continue
        written.append(name)
        if not dry_run:
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / name).write_text(src_text, encoding="utf-8")
    return written, unchanged


def _prune_extras(
    source_files: dict[str, Path], target_files: dict[str, Path], target_dir: Path, dry_run: bool
) -> list[str]:
    pruned: list[str] = []
    for name in target_files:
        if name not in source_files:
            pruned.append(name)
            if not dry_run:
                (target_dir / name).unlink()
    return pruned


def mirror(
    source_memory_dir: Path,
    target_dir: Path,
    *,
    dry_run: bool = False,
    prune: bool = False,
) -> dict[str, Any]:
    """Mirror all ``*.md`` from source into target.

    Creates ``target_dir`` if missing. ``prune`` (default OFF) removes target
    ``*.md`` files absent from source. ``dry_run`` computes the report without
    touching the filesystem. Returns a per-target report with file lists + counts.
    """
    source_files = {p.name: p for p in sorted(source_memory_dir.glob("*.md"))}
    target_files = (
        {p.name: p for p in sorted(target_dir.glob("*.md"))} if target_dir.is_dir() else {}
    )

    written, unchanged = _copy_markdown(source_files, target_files, target_dir, dry_run)
    pruned = _prune_extras(source_files, target_files, target_dir, dry_run) if prune else []

    return {
        "target": str(target_dir),
        "written": sorted(written),
        "unchanged": sorted(unchanged),
        "pruned": sorted(pruned),
        "counts": {
            "written": len(written),
            "unchanged": len(unchanged),
            "pruned": len(pruned),
        },
        "dry_run": dry_run,
    }

# ABOUTME: Tests on registry.yaml's `references_always_on` — each declared reference is a real canonical file,
# ABOUTME: and the repos whose sessions load an estate-map slice declare their own.

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "shared" / "references"

#: The repo sessions that load their estate-map slice through the managed block (OS#640).
SLICE_SESSIONS = ("aigranthelper", "grantspider")


def _registry() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "registry.yaml").read_text(encoding="utf-8"))


def _declared(registry: dict[str, Any]) -> dict[str, list[str]]:
    return {
        ctx["id"]: list(ctx.get("references_always_on") or [])
        for ctx in registry["contexts"]
    }


def unresolved_references(registry: dict[str, Any], references: Path) -> list[str]:
    """`<context>: <path>` for each declared reference that names no file under `references`."""
    return [
        f"{cid}: {path}"
        for cid, paths in _declared(registry).items()
        for path in paths
        if not (references / path).is_file()
    ]


def test_every_declared_reference_is_a_canonical_file():
    assert unresolved_references(_registry(), REFERENCES) == []


def test_a_reference_to_a_file_that_does_not_exist_is_reported(tmp_path):
    (tmp_path / "estate-map").mkdir()
    (tmp_path / "estate-map" / "grantspider.md").write_text("x", encoding="utf-8")
    registry = {
        "contexts": [
            {"id": "grantspider", "references_always_on": ["estate-map/grantspider.md"]},
            {"id": "aigranthelper", "references_always_on": ["estate-map/aigranthelpr.md"]},
            {"id": "fiscus"},
        ]
    }
    assert unresolved_references(registry, tmp_path) == [
        "aigranthelper: estate-map/aigranthelpr.md"
    ]


def test_a_reference_naming_a_directory_is_reported(tmp_path):
    (tmp_path / "estate-map").mkdir()
    registry = {"contexts": [{"id": "x", "references_always_on": ["estate-map"]}]}
    assert unresolved_references(registry, tmp_path) == ["x: estate-map"]


def test_slice_sessions_declare_their_own_slice():
    declared = _declared(_registry())
    for cid in SLICE_SESSIONS:
        assert f"estate-map/{cid}.md" in declared[cid], (
            f"registry.yaml `{cid}` does not declare its estate-map slice in references_always_on"
        )

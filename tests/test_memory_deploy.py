# ABOUTME: Tests for src/oversteward/memory_deploy.py + scripts/deploy_memory.py.
# ABOUTME: Encoding, registry parsing, and *.md mirror/prune — all against temp roots, never ~/.claude.

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from oversteward.memory_deploy import (
    encode_project_dir,
    managed_targets,
    mirror,
    target_project_dir,
)


def _load_cli():
    script_path = Path(__file__).resolve().parent.parent / "scripts" / "deploy_memory.py"
    spec = importlib.util.spec_from_file_location("oversteward_deploy_memory_cli", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- encoding -------------------------------------------------------------


def test_encode_project_dir_leading_dash_and_slash_to_dash():
    assert encode_project_dir("/home/natha/grantspider") == "-home-natha-grantspider"


def test_encode_project_dir_preserves_case():
    assert encode_project_dir("/home/natha/OverSteward") == "-home-natha-OverSteward"


def test_target_project_dir_appends_memory_under_injected_base(tmp_path):
    target = target_project_dir("/home/natha/OverSteward", projects_base=tmp_path)
    assert target == tmp_path / "-home-natha-OverSteward" / "memory"


# --- managed_targets ------------------------------------------------------


def _write_registry(tmp_path: Path) -> Path:
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        "version: 2\n"
        "contexts:\n"
        '  - name: "OverSteward"\n'
        "    id: oversteward\n"
        '    local_path: "/home/natha/OverSteward"\n'
        '  - name: "GrantSpider"\n'
        "    id: grantspider\n"
        '    local_path: "/home/natha/grantspider"\n'
        '  - name: "Obsidian"\n'
        "    id: home-obsidian\n",
        encoding="utf-8",
    )
    return registry


def test_managed_targets_includes_only_contexts_with_local_path(tmp_path):
    registry = _write_registry(tmp_path)
    base = tmp_path / "projects"
    targets = managed_targets(registry, projects_base=base)
    assert set(targets) == {"oversteward", "grantspider"}
    assert targets["grantspider"] == base / "-home-natha-grantspider" / "memory"


# --- mirror ---------------------------------------------------------------


@pytest.fixture
def source_memory(tmp_path):
    src = tmp_path / "steward-memory" / "memory"
    src.mkdir(parents=True)
    (src / "a.md").write_text("alpha", encoding="utf-8")
    (src / "b.md").write_text("beta", encoding="utf-8")
    (src / "ignore.txt").write_text("not markdown", encoding="utf-8")
    return src


def test_mirror_writes_all_markdown_and_creates_target(source_memory, tmp_path):
    target = tmp_path / "projects" / "-home-natha-OverSteward" / "memory"
    report = mirror(source_memory, target)
    assert report["counts"]["written"] == 2
    assert (target / "a.md").read_text(encoding="utf-8") == "alpha"
    assert not (target / "ignore.txt").exists()


def test_mirror_is_idempotent(source_memory, tmp_path):
    target = tmp_path / "out" / "memory"
    mirror(source_memory, target)
    report = mirror(source_memory, target)
    assert report["counts"]["written"] == 0
    assert report["counts"]["unchanged"] == 2


def test_mirror_rewrites_changed_file(source_memory, tmp_path):
    target = tmp_path / "out" / "memory"
    mirror(source_memory, target)
    (source_memory / "a.md").write_text("alpha-v2", encoding="utf-8")
    report = mirror(source_memory, target)
    assert report["written"] == ["a.md"]
    assert (target / "a.md").read_text(encoding="utf-8") == "alpha-v2"


def test_mirror_dry_run_writes_nothing(source_memory, tmp_path):
    target = tmp_path / "out" / "memory"
    report = mirror(source_memory, target, dry_run=True)
    assert report["counts"]["written"] == 2
    assert report["dry_run"] is True
    assert not target.exists()


def test_mirror_prune_off_by_default_keeps_extras(source_memory, tmp_path):
    target = tmp_path / "out" / "memory"
    target.mkdir(parents=True)
    (target / "stale.md").write_text("orphan", encoding="utf-8")
    report = mirror(source_memory, target)
    assert report["counts"]["pruned"] == 0
    assert (target / "stale.md").exists()


def test_mirror_prune_removes_extras_when_enabled(source_memory, tmp_path):
    target = tmp_path / "out" / "memory"
    target.mkdir(parents=True)
    (target / "stale.md").write_text("orphan", encoding="utf-8")
    report = mirror(source_memory, target, prune=True)
    assert report["pruned"] == ["stale.md"]
    assert not (target / "stale.md").exists()


def test_mirror_prune_dry_run_keeps_extras(source_memory, tmp_path):
    target = tmp_path / "out" / "memory"
    target.mkdir(parents=True)
    (target / "stale.md").write_text("orphan", encoding="utf-8")
    report = mirror(source_memory, target, prune=True, dry_run=True)
    assert report["pruned"] == ["stale.md"]
    assert (target / "stale.md").exists()


# --- CLI ------------------------------------------------------------------


def test_cli_parse_args_defaults():
    cli = _load_cli()
    args = cli.parse_args([])
    assert args.source == "/home/natha/steward-memory/memory"
    assert args.targets == "all"
    assert args.dry_run is False
    assert args.prune is False
    assert args.pull is False


def test_cli_parse_args_flags():
    cli = _load_cli()
    args = cli.parse_args(["--source", "/tmp/m", "--targets", "oversteward", "--dry-run", "--prune"])
    assert args.source == "/tmp/m"
    assert args.targets == "oversteward"
    assert args.dry_run is True
    assert args.prune is True


def test_cli_select_targets_all():
    cli = _load_cli()
    all_targets = {"oversteward": Path("/o"), "grantspider": Path("/g")}
    assert cli.select_targets("all", all_targets) == all_targets


def test_cli_select_targets_oversteward_only():
    cli = _load_cli()
    all_targets = {"oversteward": Path("/o"), "grantspider": Path("/g")}
    assert cli.select_targets("oversteward", all_targets) == {"oversteward": Path("/o")}


def test_cli_select_targets_comma_list_ignores_unknown():
    cli = _load_cli()
    all_targets = {"oversteward": Path("/o"), "grantspider": Path("/g")}
    selected = cli.select_targets("grantspider,bogus", all_targets)
    assert selected == {"grantspider": Path("/g")}

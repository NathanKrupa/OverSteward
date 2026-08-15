# ABOUTME: Tests for the split-brain memory reconciler (OS#195) — divergence bands, union, variant sidecars, symlink, dry-run.
# ABOUTME: Uses ONLY tmp_path fixture directories — NEVER the live ~/.claude harness path or steward-memory repo.

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from oversteward.dream.reconcile import (
    STEWARD_VARIANT_SUFFIX,
    classify_divergence,
    reconcile,
)

_FRONT = "---\nname: {name}\ndescription: {desc}\nmetadata:\n  type: feedback\n---\n\n{body}\n"


def _write(directory: Path, name: str, *, desc: str = "d", body: str = "b") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(_FRONT.format(name=Path(name).stem, desc=desc, body=body), encoding="utf-8")
    return path


@pytest.fixture
def stores(tmp_path: Path) -> tuple[Path, Path]:
    """A harness + steward pair exercising all four divergence bands."""
    harness = tmp_path / "harness"
    steward = tmp_path / "steward"
    # identical
    _write(harness, "same.md", desc="same", body="identical")
    _write(steward, "same.md", desc="same", body="identical")
    # diverged
    _write(harness, "drift.md", desc="drift", body="HARNESS version")
    _write(steward, "drift.md", desc="drift", body="STEWARD version")
    # harness-only (manual write never carried in)
    _write(harness, "manual.md", desc="manual fact", body="only in harness")
    # steward-only (dream write never loaded)
    _write(steward, "dreamt.md", desc="dreamt fact", body="only in steward")
    return harness, steward


def test_classify_divergence_four_bands(stores: tuple[Path, Path]) -> None:
    harness, steward = stores
    report = classify_divergence(harness, steward)
    assert report.identical == ["same.md"]
    assert report.diverged == ["drift.md"]
    assert report.harness_only == ["manual.md"]
    assert report.steward_only == ["dreamt.md"]


def test_classify_excludes_index_and_review(tmp_path: Path) -> None:
    harness, steward = tmp_path / "h", tmp_path / "s"
    _write(harness, "fact.md")
    _write(steward, "fact.md")
    (harness / "MEMORY.md").write_text("# index\n", encoding="utf-8")
    (steward / "MEMORY_REVIEW.md").write_text("# review\n", encoding="utf-8")
    report = classify_divergence(harness, steward)
    assert report.identical == ["fact.md"]
    assert "MEMORY.md" not in (report.diverged + report.harness_only + report.steward_only)
    assert "MEMORY_REVIEW.md" not in (report.steward_only + report.harness_only)


def _read(directory: Path, name: str) -> str:
    return (directory / name).read_text(encoding="utf-8")


def test_dry_run_mutates_nothing(stores: tuple[Path, Path], tmp_path: Path) -> None:
    harness, steward = stores
    before_harness = {p.name: p.read_bytes() for p in harness.iterdir()}
    before_steward = {p.name: p.read_bytes() for p in steward.iterdir()}
    plan = reconcile(harness, steward, backup_root=tmp_path / "bk", apply=False)
    assert plan.applied is False
    assert plan.backup_path is None
    assert plan.symlinked is False
    assert {p.name: p.read_bytes() for p in harness.iterdir()} == before_harness
    assert {p.name: p.read_bytes() for p in steward.iterdir()} == before_steward
    assert not (tmp_path / "bk").exists()
    # the plan still describes the intended work
    assert plan.unioned == ["manual.md"]
    assert plan.variant_sidecars == [f"drift{STEWARD_VARIANT_SUFFIX}"]


def test_apply_unions_harness_only_into_steward(stores: tuple[Path, Path], tmp_path: Path) -> None:
    harness, steward = stores
    reconcile(harness, steward, backup_root=tmp_path / "bk", apply=True)
    assert (steward / "manual.md").exists()
    assert _read(steward, "manual.md") == _read(harness, "manual.md")


def test_apply_diverged_keeps_both_versions(stores: tuple[Path, Path], tmp_path: Path) -> None:
    harness, steward = stores
    harness_drift = _read(harness, "drift.md")
    steward_drift = _read(steward, "drift.md")
    reconcile(harness, steward, backup_root=tmp_path / "bk", apply=True)
    # canonical = harness version
    assert _read(steward, "drift.md") == harness_drift
    # steward's prior version preserved as a sidecar
    sidecar = steward / f"drift{STEWARD_VARIANT_SUFFIX}"
    assert sidecar.exists()
    assert sidecar.read_text(encoding="utf-8") == steward_drift


def test_apply_creates_timestamped_backup(stores: tuple[Path, Path], tmp_path: Path) -> None:
    harness, steward = stores
    plan = reconcile(
        harness,
        steward,
        backup_root=tmp_path / "bk",
        apply=True,
        now=datetime(2026, 7, 5, 13, 30, 0),
    )
    assert plan.backup_path is not None
    assert plan.backup_path.exists()
    assert plan.backup_path.name == "memory-reconcile-20260705-133000.tar.gz"
    import tarfile

    with tarfile.open(plan.backup_path) as tar:
        names = tar.getnames()
    assert any(n.startswith("harness") for n in names)
    assert any(n.startswith("steward") for n in names)


def test_apply_regenerates_memory_index(stores: tuple[Path, Path], tmp_path: Path) -> None:
    harness, steward = stores
    reconcile(harness, steward, backup_root=tmp_path / "bk", apply=True)
    # MEMORY.md is now the lean standing-orders layer (OS#203); every fact's recall
    # hook is preserved in the full on-demand index alongside it.
    assert (steward / "MEMORY.md").exists()
    text = (steward / "MEMORY_FULL.md").read_text(encoding="utf-8")
    # every unified fact indexed, including the carried-in harness-only fact
    assert "manual.md" in text
    assert "dreamt.md" in text
    assert "drift.md" in text
    # the variant sidecar is a reconciler backup, NOT a live fact (OS#203): it is
    # excluded from enumeration, so it never appears in the index.
    assert f"drift{STEWARD_VARIANT_SUFFIX}" not in text


def test_apply_establishes_symlink(stores: tuple[Path, Path], tmp_path: Path) -> None:
    harness, steward = stores
    plan = reconcile(harness, steward, backup_root=tmp_path / "bk", apply=True)
    assert plan.symlinked is True
    assert harness.is_symlink()
    assert harness.resolve() == steward.resolve()
    # loading through the symlink now sees the unified store
    assert (harness / "dreamt.md").exists()
    assert (harness / "manual.md").exists()


def test_symlink_is_idempotent(stores: tuple[Path, Path], tmp_path: Path) -> None:
    harness, steward = stores
    reconcile(harness, steward, backup_root=tmp_path / "bk", apply=True)
    steward_files_after_first = sorted(p.name for p in steward.iterdir())
    # a second run through the now-symlinked harness path must be a clean no-op
    plan = reconcile(harness, steward, backup_root=tmp_path / "bk2", apply=True)
    assert plan.symlinked is True
    assert harness.is_symlink()
    assert harness.resolve() == steward.resolve()
    # no duplicate sidecars, no divergence work the second time
    assert plan.divergence.diverged == []
    assert plan.divergence.harness_only == []
    assert sorted(p.name for p in steward.iterdir()) == steward_files_after_first


def test_report_lists_all_diverged_for_review(stores: tuple[Path, Path], tmp_path: Path) -> None:
    harness, steward = stores
    plan = reconcile(harness, steward, backup_root=tmp_path / "bk", apply=False)
    report = plan.to_report()
    assert "drift.md" in report
    assert "manual.md" in report
    assert "DRY RUN" in report


def _load_cli():
    import importlib.util

    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "dream" / "reconcile_stores.py"
    )
    spec = importlib.util.spec_from_file_location("reconcile_stores_cli", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_dry_run_is_default_and_mutates_nothing(
    stores: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness, steward = stores
    before = {p.name: p.read_bytes() for p in steward.iterdir()}
    cli = _load_cli()
    rc = cli.main(
        [
            "--harness-path",
            str(harness),
            "--steward-dir",
            str(steward),
            "--backup-root",
            str(tmp_path / "bk"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert {p.name: p.read_bytes() for p in steward.iterdir()} == before
    assert not harness.is_symlink()


def test_cli_apply_performs_reconciliation(
    stores: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness, steward = stores
    cli = _load_cli()
    rc = cli.main(
        [
            "--harness-path",
            str(harness),
            "--steward-dir",
            str(steward),
            "--backup-root",
            str(tmp_path / "bk"),
            "--apply",
        ]
    )
    assert rc == 0
    assert "APPLIED" in capsys.readouterr().out
    assert harness.is_symlink()
    assert (steward / "manual.md").exists()

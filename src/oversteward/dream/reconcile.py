# ABOUTME: One-time reconciliation of the split-brain memory stores (OS#195) — union + variant-sidecar + symlink.
# ABOUTME: Dry-run-default, non-destructive: back up both dirs, carry harness-only facts into steward, preserve diverged both-ways.

"""Reconcile the two divergent memory stores onto one git-backed store (OS#195).

Two physical memory directories drifted apart:

- **HARNESS** — the directory the Claude harness auto-loads each session
  (``~/.claude/projects/-home-natha-OverSteward/memory/``). Curated, hand-written.
- **STEWARD** — the git-backed store the dream engine writes
  (``DEFAULT_STORE_PATH`` in :mod:`oversteward.dream.consolidate`). The richer
  superset, NOT auto-loaded.

The fix keeps STEWARD as the single canonical git-backed store and makes the
HARNESS path a symlink into it, so there is one physical store that the dream
writes, manual writes follow, and the harness loads.

This module is the deterministic, non-destructive reconciler around that cutover.
Everything is INJECTABLE (fixture directories in tests; the live paths only from
operator-run code). Nothing here touches the live paths on import. The default is
a **dry run** that computes and reports the plan but mutates nothing; ``apply``
performs the backup, the union, the variant sidecars, the ``MEMORY.md`` regen,
and the symlink.

Divergence bands (by filename across the two stores):

- **identical** — same filename, byte-identical content. No action.
- **harness_only** — a manual fact never carried into steward. Copied INTO
  steward (union; never deleted).
- **steward_only** — a dream write never loaded. Already in steward; no action.
- **diverged** — same filename, different content. The HARNESS (curated) version
  becomes canonical in steward; steward's prior version is preserved alongside as
  ``<stem>.steward-variant.md``. Nothing is auto-picked silently — every diverged
  file is listed in the reconciliation report for human review.
"""

from __future__ import annotations

import shutil
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .consolidate import MemoryStore

# Sidecar suffix for a steward file's prior content when the harness version is
# taken as canonical for a diverged pair — nothing is lost.
STEWARD_VARIANT_SUFFIX = ".steward-variant.md"

# Root-level non-fact files (index + review surface) are not reconciled as facts.
_NON_FACT_FILES = frozenset({"MEMORY.md", "MEMORY_REVIEW.md"})


@dataclass
class DivergenceReport:
    """The 4-way filename classification across the harness + steward stores."""

    identical: list[str] = field(default_factory=list)
    diverged: list[str] = field(default_factory=list)
    harness_only: list[str] = field(default_factory=list)
    steward_only: list[str] = field(default_factory=list)

    def to_lines(self) -> list[str]:
        """Human-readable summary block for the plan / report."""
        return [
            f"identical:     {len(self.identical)}",
            f"diverged:      {len(self.diverged)}",
            f"harness-only:  {len(self.harness_only)}",
            f"steward-only:  {len(self.steward_only)}",
        ]


@dataclass
class ReconcilePlan:
    """The computed, not-yet-applied reconciliation plan (OS#195).

    ``applied`` is False for a dry run and True after :func:`reconcile` mutates.
    ``backup_path`` is the timestamped tar (None until a real backup is taken).
    ``symlinked`` records whether the harness path now points into steward.
    """

    divergence: DivergenceReport
    unioned: list[str] = field(default_factory=list)
    variant_sidecars: list[str] = field(default_factory=list)
    backup_path: Path | None = None
    symlinked: bool = False
    applied: bool = False

    def to_report(self) -> str:
        """Render the full plan + divergence report for stdout / the PR body."""
        header = "APPLIED" if self.applied else "DRY RUN — nothing mutated"
        lines = [f"# Memory store reconciliation ({header})", ""]
        lines.append("## Divergence")
        lines.extend(self.divergence.to_lines())
        lines.append("")
        lines.append(f"## Union — harness-only facts carried into steward ({len(self.unioned)})")
        lines.extend(f"- {name}" for name in self.unioned)
        lines.append("")
        lines.append(
            f"## Diverged — harness kept canonical, steward preserved as sidecar "
            f"({len(self.divergence.diverged)})"
        )
        lines.extend(
            f"- {name} (steward prior → {Path(name).stem}{STEWARD_VARIANT_SUFFIX})"
            for name in self.divergence.diverged
        )
        lines.append("")
        lines.append("## Wiring")
        lines.append(f"- backup: {self.backup_path if self.backup_path else '(none — dry run)'}")
        lines.append(f"- harness symlink established: {self.symlinked}")
        return "\n".join(lines) + "\n"


def _fact_files(directory: Path) -> dict[str, Path]:
    """Map ``filename -> path`` for every fact file in ``directory`` (index excluded)."""
    if not directory.is_dir():
        return {}
    return {
        p.name: p
        for p in sorted(directory.glob("*.md"))
        if p.name not in _NON_FACT_FILES
    }


def classify_divergence(harness_dir: Path, steward_dir: Path) -> DivergenceReport:
    """Classify every fact filename across the two stores into the 4 bands."""
    harness = _fact_files(harness_dir)
    steward = _fact_files(steward_dir)
    report = DivergenceReport()
    for name in sorted(set(harness) | set(steward)):
        in_h, in_s = name in harness, name in steward
        if in_h and in_s:
            h_text = harness[name].read_text(encoding="utf-8")
            s_text = steward[name].read_text(encoding="utf-8")
            (report.identical if h_text == s_text else report.diverged).append(name)
        elif in_h:
            report.harness_only.append(name)
        else:
            report.steward_only.append(name)
    return report


def _resolve_harness_dir(harness_path: Path) -> Path:
    """The real directory the harness path refers to (follows an existing symlink)."""
    return harness_path.resolve() if harness_path.is_symlink() else harness_path


def _backup(harness_dir: Path, steward_dir: Path, backup_root: Path, stamp: str) -> Path:
    """Write a single timestamped tar of BOTH directories, returning its path."""
    backup_root.mkdir(parents=True, exist_ok=True)
    tar_path = backup_root / f"memory-reconcile-{stamp}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        if harness_dir.is_dir():
            tar.add(harness_dir, arcname="harness")
        if steward_dir.is_dir():
            tar.add(steward_dir, arcname="steward")
    return tar_path


def _apply_union_and_variants(
    harness_dir: Path, steward_dir: Path, plan: ReconcilePlan
) -> None:
    """Carry harness-only facts in; for diverged, keep harness + sidecar steward."""
    harness = _fact_files(harness_dir)
    steward = _fact_files(steward_dir)
    steward_dir.mkdir(parents=True, exist_ok=True)
    for name in plan.divergence.harness_only:
        shutil.copy2(harness[name], steward_dir / name)
    for name in plan.divergence.diverged:
        sidecar = f"{Path(name).stem}{STEWARD_VARIANT_SUFFIX}"
        shutil.copy2(steward[name], steward_dir / sidecar)
        shutil.copy2(harness[name], steward_dir / name)


def _establish_symlink(harness_path: Path, steward_dir: Path) -> bool:
    """Point ``harness_path`` at ``steward_dir`` idempotently; True if now linked.

    If already the correct symlink, no-op. A real directory at the harness path is
    assumed already backed up + emptied by the caller; here it is removed and
    replaced with the symlink.
    """
    target = steward_dir.resolve()
    if harness_path.is_symlink() and harness_path.resolve() == target:
        return True
    if harness_path.is_symlink() or harness_path.exists():
        if harness_path.is_dir() and not harness_path.is_symlink():
            shutil.rmtree(harness_path)
        else:
            harness_path.unlink()
    harness_path.parent.mkdir(parents=True, exist_ok=True)
    harness_path.symlink_to(target, target_is_directory=True)
    return True


def _build_plan(divergence: DivergenceReport) -> ReconcilePlan:
    """The dry-run plan derived purely from the divergence classification."""
    return ReconcilePlan(
        divergence=divergence,
        unioned=list(divergence.harness_only),
        variant_sidecars=[
            f"{Path(name).stem}{STEWARD_VARIANT_SUFFIX}" for name in divergence.diverged
        ],
    )


def reconcile(
    harness_path: Path,
    steward_dir: Path,
    *,
    backup_root: Path,
    apply: bool = False,
    now: datetime | None = None,
) -> ReconcilePlan:
    """Compute (dry run) or perform (``apply``) the store reconciliation (OS#195).

    Dry run (default) classifies divergence and returns the plan WITHOUT touching
    any directory. ``apply`` backs up both dirs → unions harness-only facts →
    preserves each diverged pair as canonical + sidecar → regenerates
    ``MEMORY.md`` → symlinks the harness path into steward (idempotent). A re-run
    through an existing symlink resolves divergence to empty and no-ops.
    """
    harness_dir = _resolve_harness_dir(harness_path)
    plan = _build_plan(classify_divergence(harness_dir, steward_dir))
    if not apply:
        return plan
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    plan.backup_path = _backup(harness_dir, steward_dir, backup_root, stamp)
    _apply_union_and_variants(harness_dir, steward_dir, plan)
    MemoryStore(steward_dir).regenerate_index()
    plan.symlinked = _establish_symlink(harness_path, steward_dir)
    plan.applied = True
    return plan

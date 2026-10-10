# ABOUTME: OverSteward's own deployed copies of shared/ sources are relative symlinks into shared/ (OS#576).
# ABOUTME: Pins the link set against git's index, and that shared/ itself carries no link to leak.

"""Inside OverSteward, a deployed copy of a ``shared/`` source is a link, not a copy.

Other repos still receive real bytes (sow and the ``~/.claude/shared`` deploy
copy file contents out of ``shared/``). Here, a link makes "edit one, copy
across" impossible to get wrong, so the pair tests that used to prove each copy
byte-identical are replaced by this one: every deployed path the rules below
name is a relative symlink resolving to its canonical file inside ``shared/``.

The expected set is derived from rules, not listed by hand, so a new card or
family member is expected to be linked the moment it is deployed here. Paths
that deliberately stay regular files are named below with the reason, and each
exception is itself checked, so it cannot outlive its reason unnoticed.

Not derived by the rules but kept as copies, and checked in ``KEPT_AS_COPIES``:
``scripts/tools/generate_tool_registry.py`` and
``scripts/workflows/generate_workflow_registry.py`` locate the project root from
their *resolved* ``__file__``, so as links into ``shared/scripts/`` they would
take ``shared/`` for the root.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from oversteward.dev_family import canonical_family, deployed_relpath

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED = REPO_ROOT / "shared"

# Deployed copies that are ahead of their shared/ source. Linking them would roll
# them back; reconcile the pair first. Each must still differ, or it should be a link.
DRIFTED_COPIES = {
    ".claude/skills/answer/SKILL.md": "shared/skills/answer/SKILL.md",
    ".claude/skills/questions/SKILL.md": "shared/skills/questions/SKILL.md",
}

# Byte-identical copies kept as regular files on purpose.
KEPT_AS_COPIES = {
    # gitleaks reads its config from the scan root, and the canonical, estate-wide
    # test_secret_scan.py pins the root file as a byte-copy.
    ".gitleaks.toml": "shared/scripts/dev/.gitleaks.toml",
    # Both find the project root from their resolved __file__; a link would make it shared/.
    "scripts/tools/generate_tool_registry.py": "shared/scripts/tools/generate_tool_registry.py",
    "scripts/workflows/generate_workflow_registry.py": (
        "shared/scripts/workflows/generate_workflow_registry.py"
    ),
}


def _present(rel: str) -> bool:
    path = REPO_ROOT / rel
    return path.is_symlink() or path.exists()


def expected_links() -> dict[str, str]:
    """Deployed path -> canonical path, both repo-relative."""
    links: dict[str, str] = {}
    for card in sorted((SHARED / "agents").glob("*.md")):
        links[f".claude/agents/{card.name}"] = f"shared/agents/{card.name}"
    for member in canonical_family(SHARED):
        links[deployed_relpath(member)] = f"shared/scripts/dev/{member}"
    for source in sorted((SHARED / "skills").rglob("*")):
        rel = source.relative_to(SHARED / "skills")
        if source.is_file() and len(rel.parts) > 1:
            links[f".claude/skills/{rel.as_posix()}"] = f"shared/skills/{rel.as_posix()}"
    excluded = DRIFTED_COPIES.keys() | KEPT_AS_COPIES.keys()
    return {
        deployed: canonical
        for deployed, canonical in links.items()
        if deployed not in excluded and _present(deployed)
    }


EXPECTED = expected_links()


def test_the_rules_find_links_at_all() -> None:
    """A derived guard over an empty set passes vacuously."""
    families = {deployed.split("/")[0] + "/" + deployed.split("/")[1] for deployed in EXPECTED}
    assert {".claude/agents", ".claude/hooks", ".claude/skills", "scripts/dev", "tests/dev"} <= (
        families
    )


@pytest.mark.parametrize("deployed", sorted(EXPECTED))
def test_each_deployed_copy_is_a_relative_link_into_shared(deployed: str) -> None:
    path = REPO_ROOT / deployed
    canonical = REPO_ROOT / EXPECTED[deployed]
    assert path.is_symlink(), (
        f"{deployed} is a regular file. Inside OverSteward it must be a relative symlink to "
        f"{EXPECTED[deployed]} — edit the canonical file, never a copy (OS#576)."
    )
    target = os.readlink(path)
    assert not os.path.isabs(target), f"{deployed} -> {target} is absolute; it must be relative"
    assert path.resolve() == canonical.resolve(), f"{deployed} -> {target} is not {canonical}"
    assert canonical.is_file() and not canonical.is_symlink(), f"{canonical} is not a real file"


def test_git_records_exactly_the_expected_links() -> None:
    """A stray link anywhere else in the tree is a link nothing above vouches for."""
    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-s"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    tracked_links = {line.split("\t", 1)[1] for line in listed if line.startswith("120000 ")}
    assert tracked_links == set(EXPECTED)


def test_shared_carries_no_symlinks() -> None:
    """shared/ is what gets copied into other repos and Claude homes; it must hold bytes."""
    links = [
        str(Path(root, name).relative_to(REPO_ROOT))
        for root, dirs, files in os.walk(SHARED)
        for name in dirs + files
        if Path(root, name).is_symlink()
    ]
    assert links == []


@pytest.mark.parametrize("deployed", sorted(DRIFTED_COPIES))
def test_a_drifted_copy_is_still_drifted(deployed: str) -> None:
    """Once the pair is reconciled, the copy should become a link instead."""
    copy, canonical = REPO_ROOT / deployed, REPO_ROOT / DRIFTED_COPIES[deployed]
    assert not copy.is_symlink()
    assert copy.read_bytes() != canonical.read_bytes(), (
        f"{deployed} now matches {DRIFTED_COPIES[deployed]}: drop it from DRIFTED_COPIES and link it."
    )


@pytest.mark.parametrize("deployed", sorted(KEPT_AS_COPIES))
def test_a_kept_copy_is_a_byte_identical_regular_file(deployed: str) -> None:
    copy, canonical = REPO_ROOT / deployed, REPO_ROOT / KEPT_AS_COPIES[deployed]
    assert not copy.is_symlink()
    assert copy.read_bytes() == canonical.read_bytes()

# ABOUTME: Derives the registered PreToolUse hooks from settings.json and checks HOOK_MEMBERS (OS#378).
# ABOUTME: A hand-maintained list beside a machine-readable one drifts; this makes the drift loud.

"""OS#378: `guard_trunk_pull.py` was a registered hook absent from `HOOK_MEMBERS`.

`deployed_relpath` therefore looked for it under `scripts/dev/`, where it will
never be, so the family audit reported it `absent` in every repo, permanently —
a broken instrument reading as a quiet backlog.

The one-line fix is not the interesting part. The interesting part is that
nothing would have caught the next one, so this derives the answer from
`.claude/settings.json` (the file that decides what actually runs) rather than
from a second hand-written list.
"""

from __future__ import annotations

import json
import re
import stat
import subprocess
from pathlib import Path

import pytest

from oversteward.dev_family import HOOK_MEMBERS, deployed_relpath

REPO_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
CANONICAL_DEV = REPO_ROOT / "shared" / "scripts" / "dev"
DEPLOYED_HOOKS = REPO_ROOT / ".claude" / "hooks"

_HOOK_SCRIPT = re.compile(r"\.claude/hooks/([A-Za-z0-9_]+\.py)")


def registered_hook_scripts() -> set[str]:
    """Every `.claude/hooks/*.py` this repo's settings actually invoke."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            found.update(_HOOK_SCRIPT.findall(node))

    walk(settings.get("hooks", {}))
    return found


def test_settings_registers_hooks_at_all() -> None:
    """A derived guard over an empty set passes vacuously."""
    assert registered_hook_scripts(), "no hooks found in .claude/settings.json"


@pytest.mark.parametrize("script", sorted(registered_hook_scripts()))
def test_every_registered_hook_is_a_known_hook_member(script: str) -> None:
    """The guard OS#378 asks for: a registered hook missing here is invisible forever."""
    canonical = CANONICAL_DEV / script
    if not canonical.is_file():
        pytest.skip(f"{script} is not a canonical shared/scripts/dev/ member")
    assert script in HOOK_MEMBERS, (
        f"{script} is a registered PreToolUse hook and a canonical family member, but is "
        f"not in dev_family.HOOK_MEMBERS. deployed_relpath() therefore looks for it at "
        f"{deployed_relpath(script)!r}, where it will never be, and the family audit "
        f"reports it absent in every repo forever (OS#378)."
    )


@pytest.mark.parametrize("member", sorted(HOOK_MEMBERS))
def test_every_hook_member_deploys_into_claude_hooks(member: str) -> None:
    assert deployed_relpath(member) == f".claude/hooks/{member}"


@pytest.mark.parametrize("member", sorted(HOOK_MEMBERS))
def test_every_hook_member_is_executable_on_both_sides(member: str) -> None:
    """OS#378's second drift: the canonical guard_trunk_pull.py was 100644.

    Read from the index, not the filesystem: the mode git records is the one
    that travels to every other repo, and a local umask can mask a wrong one.
    """
    for path in (f"shared/scripts/dev/{member}", f".claude/hooks/{member}"):
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-s", path],
            capture_output=True, text=True, check=True,
        )
        if not result.stdout.strip():
            pytest.skip(f"{path} is not tracked")
        mode = result.stdout.split()[0]
        assert mode == "100755", (
            f"{path} is mode {mode}; every guard in this family is 100755. "
            "A hook git records as non-executable is a hook a fresh clone cannot run."
        )


@pytest.mark.parametrize("member", sorted(HOOK_MEMBERS))
def test_every_hook_member_exists_on_both_sides_and_is_byte_identical(member: str) -> None:
    canonical = CANONICAL_DEV / member
    deployed = DEPLOYED_HOOKS / member
    assert canonical.is_file(), f"shared/scripts/dev/{member} is missing"
    assert deployed.is_file(), f".claude/hooks/{member} is missing"
    assert canonical.read_bytes() == deployed.read_bytes(), (
        f"{member} drifted between canonical and deployed; edit one and copy."
    )


def test_the_filesystem_bit_matches_the_recorded_mode() -> None:
    """Belt and braces: a tracked 100755 whose working copy lost the bit still fails to run."""
    for member in sorted(HOOK_MEMBERS):
        path = CANONICAL_DEV / member
        assert path.stat().st_mode & stat.S_IXUSR, f"{path} is not executable on disk"

#!/usr/bin/env python3
# ABOUTME: PreToolUse(Bash) guard — refuse env-mutating uv commands when .venv is a shared symlink.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/.claude/hooks/.
"""Block environment mutation from a worktree that borrows another tree's venv.

``new-session.sh`` symlinks a session worktree's ``.venv`` at the primary
checkout's, so the two trees share one environment. uv resolves the venv root
through that symlink as *the worktree's* path and stamps it into every console
script's shebang and into the editable install's ``__editable__*.pth``. The
shared venv then points at a tree that will be removed. Nothing announces it,
and nothing fails until the worktree is pruned — at which point every entry
point in every checkout on that venv is broken, with an error that looks like a
bad install rather than a cross-tree collision.

So: refuse the uv verbs that rewrite a venv in place (``sync``, ``venv``,
``add``, ``remove``, ``pip install``, ``pip uninstall``, ``lock --upgrade``)
when this tree's ``.venv`` is a symlink resolving outside the tree. Reads and
executions are untouched — ``uv run`` and ``uv pip list/show/freeze`` are fine,
and a tree with a real ``.venv`` directory (every primary checkout) never trips
the guard.

The escape hatch matches the family convention
(``CLAUDE_ALLOW_MAIN_GIT=1``): ``CLAUDE_ALLOW_SHARED_VENV_MUTATION=1``, honored
either exported in the session or as a genuine leading assignment on the
guarded command. It is deliberately its own variable — the two guards protect
unrelated things and one must not wave the other through.

Decision logic is split into pure functions so it is unit-tested without git.
"""

import json
import os
import re
import subprocess  # list-form argv, no shell; cwd is the only input
import sys
from pathlib import Path

_OVERRIDE_VAR = "CLAUDE_ALLOW_SHARED_VENV_MUTATION"

# A uv verb only at a command position — start of line or after a shell
# separator (``; & | && ||``), with an optional leading run of environment
# assignments (``VAR=x``). This skips string mentions (echo / grep / test data)
# that merely contain "uv sync", which would otherwise false-positive.
_SEP = r"(?:^|[\n;&|])\s*"  # start-of-line or after a shell separator
_ASSIGN = r"(?:\w+=\S+\s+)*"  # a run of ``VAR=value`` env assignments
_AT_CMD = _SEP + _ASSIGN

# Verb label -> the shape that identifies it. ``uv lock`` alone only rewrites
# the lockfile; only ``--upgrade`` re-resolves and re-installs.
_MUTATING_VERBS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(_AT_CMD + pattern))
    for label, pattern in (
        ("uv pip install", r"uv\s+pip\s+install\b"),
        ("uv pip uninstall", r"uv\s+pip\s+uninstall\b"),
        ("uv sync", r"uv\s+sync\b"),
        ("uv add", r"uv\s+add\b"),
        ("uv remove", r"uv\s+remove\b"),
        ("uv venv", r"uv\s+venv\b"),
        ("uv lock --upgrade", r"uv\s+lock\b[^\n;&|]*--upgrade\b"),
    )
)

# The inline escape hatch: the override var set to 1 as a real leading
# assignment on the guarded uv command. Matching it as a command-position
# prefix — not a bare substring — is what stops a quoted mention
# (``echo "CLAUDE_ALLOW_SHARED_VENV_MUTATION=1"``) waving the guard through.
_OVERRIDE_PREFIX = re.compile(_SEP + _ASSIGN + rf"{_OVERRIDE_VAR}=1\s+" + _ASSIGN + r"uv\b")


def mutating_verb(command: str) -> str | None:
    """The env-mutating uv verb ``command`` invokes, or None if it invokes none."""
    for label, pattern in _MUTATING_VERBS:
        if pattern.search(command):
            return label
    return None


def is_env_mutating(command: str) -> bool:
    """True if ``command`` runs a uv verb that rewrites a venv in place."""
    return mutating_verb(command) is not None


def shared_venv_target(tree_root: str) -> str | None:
    """Where this tree's ``.venv`` symlink lands, if it lands outside the tree.

    None covers every safe shape: no tree root, no ``.venv``, a real ``.venv``
    directory (a primary checkout), or a symlink pointing back inside the tree.
    """
    if not tree_root:
        return None
    venv = Path(tree_root) / ".venv"
    if not venv.is_symlink():
        return None
    target = venv.resolve()
    root = Path(tree_root).resolve()
    if target == root or root in target.parents:
        return None
    return str(target)


def venv_is_shared(tree_root: str) -> bool:
    """True if this tree's ``.venv`` is a symlink resolving outside the tree."""
    return shared_venv_target(tree_root) is not None


def has_override(command: str) -> bool:
    """True if the override is exported, or set as a leading assignment on ``command``."""
    if os.environ.get(_OVERRIDE_VAR) == "1":
        return True
    return bool(_OVERRIDE_PREFIX.search(command))


def blocked_venv(command: str, tree_root: str) -> str | None:
    """The borrowed venv ``command`` would mutate, or None if it must be allowed.

    Returning the venv rather than a bare verdict lets the refusal name the tree
    that actually owns the environment, which is the whole point of the message.
    """
    if not is_env_mutating(command) or has_override(command):
        return None
    return shared_venv_target(tree_root)


def refusal_message(verb: str, target: str) -> str:
    """The refusal — names the consequence, not just the rule."""
    return (
        f"BLOCKED — `{verb}` in a tree whose .venv is not its own.\n\n"
        f"This tree's .venv is a symlink to:\n    {target}\n\n"
        "uv would rewrite that SHARED venv's console-script shebangs and its\n"
        "editable-install pointer to THIS tree's path — silently breaking every\n"
        "entry point for every checkout on that venv the moment this tree is\n"
        "removed. The damage stays invisible until then, so the eventual failure\n"
        "looks like a bad install rather than a cross-tree collision.\n\n"
        "Run it from the checkout that owns the venv instead, or override:\n"
        f"    {_OVERRIDE_VAR}=1 <your uv command>\n"
    )


def _tree_root(cwd: str) -> str:
    try:
        result = subprocess.run(  # list-form argv, no shell
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:  # any failure → do not block
        return ""
    return result.stdout.strip()


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:  # unparseable input → don't block
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = (event.get("tool_input") or {}).get("command", "") or ""
    verb = mutating_verb(command)
    if verb is None:
        return 0  # the cheap check first — most commands never reach git
    target = blocked_venv(command, _tree_root(event.get("cwd") or os.getcwd()))
    if target is None:
        return 0
    sys.stderr.write(refusal_message(verb, target))
    return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# ABOUTME: PreToolUse(Bash) guard — refuse a pull that would rewrite a protected branch.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/.claude/hooks/.
"""Block ``git pull <remote> <ref>`` aimed at a branch other than the one checked out.

``git pull`` merges the fetched ref into **whatever branch is currently checked
out**, regardless of what that branch is named. So a hygiene pull aimed at a
repo's *default* branch, run in a checkout sitting on a *different* trunk
branch, silently fast-forwards the wrong pointer. grantspider's local ``main``
was moved onto a ``staging`` tip three times in one evening this way — valid
fast-forward, exit 0, no warning:

    ec4132a7 main@{08-10 21:56}: pull --ff-only origin staging: Fast-forward

Scope is deliberately narrow. The hazard is a *protected* branch being
rewritten; pulling upstream into a feature branch (``git pull origin staging``
on ``feat/x``) is an ordinary and correct idiom. Guarding that too would fire
constantly in worktrees, and a guard that cries wolf gets overridden
reflexively — which leaves the real case unguarded. So: block only when the
checked-out branch is itself protected and the pull names a different ref.

This is defence in depth, not the control. Hooks see only Claude Code's Bash
tool — a terminal, a Makefile, direnv or a script all bypass it. Detection and
repair live in ``sync_repos.py``, which is what actually carries the load.

Decision logic is split into pure functions so it is unit-tested without git.
"""

import json
import os
import re
import subprocess  # list-form argv, no shell; cwd is the only input
import sys

# Env vars that wave the guard through — same names the sibling guards honour,
# so an operator learns one escape hatch rather than three.
_OVERRIDE_VARS = ("CLAUDE_ALLOW_MAIN_GIT", "GS_ALLOW_MAIN_GIT")

# Branches whose pointer is load-bearing: a promotion target, a deploy source,
# or an integration trunk. Rewriting one silently is the whole hazard.
_PROTECTED = frozenset({"main", "master", "staging"})

# ``git`` only at a command position — start of line, after a shell separator
# (``; & | && ||``), or after a substitution/grouping opener — with an optional
# leading run of ``VAR=value`` assignments. Mirrors guard_main_worktree.py so a
# quoted mention ("echo 'git pull ...'") is not mistaken for a command.
#
# DUPLICATE — ``guard_main_worktree.py`` and ``check_destructive_command.py``
# carry byte-identical copies of these two lines. They are NOT shared: each hook
# is a standalone byte-copy deployed into other repos' ``.claude/hooks/``, where
# a sibling import would not resolve. A change here must be made in all three.
_SEP = r"(?:^|[\n;&|`(])\s*"  # start-of-line, shell separator, or substitution opener
_ASSIGN = r"(?:\w+=\S+\s+)*"  # a run of ``VAR=value`` env assignments
_AT_CMD = _SEP + _ASSIGN

# ``git pull`` at a command position, then any run of option flags, then the
# first bare word: the remote. The word after that, if present, is the refspec.
_PULL = re.compile(
    _AT_CMD + r"git\s+pull\b(?P<rest>[^\n;&|]*)",
)
_FLAG = re.compile(r"^-")

# A refspec that cannot name a real branch is prose, not a command. git forbids
# space ~ ^ : ? * [ \ in a ref name, and documentation placeholders (``<ref>``)
# and quoted fragments carry characters no ref ever has. Without this the guard
# fires on its own documentation: a backtick counts as a command-substitution
# opener, so "`git pull <remote> <ref>`" in a commit message or a Markdown table
# reads as a command at a command position. A guard that blocks prose gets
# overridden reflexively, which is exactly how the real case goes unguarded.
_IMPLAUSIBLE_REF = re.compile(r"""[<>`'"~^:?*\[\\]""")

_OVERRIDE_NAMES = "|".join(_OVERRIDE_VARS)
_OVERRIDE_PREFIX = re.compile(
    _SEP + _ASSIGN + rf"(?:{_OVERRIDE_NAMES})=1\s+" + _ASSIGN + r"git\s+pull\b"
)

_MESSAGE = (
    "BLOCKED — this pull would rewrite a protected branch.\n\n"
    "`git pull <remote> <ref>` merges into whatever branch is CHECKED OUT,\n"
    "whatever it is named. You are on {branch!r} and pulling {target!r}, so this\n"
    "would move {branch!r} onto {target!r}'s tip — silently, as a valid\n"
    "fast-forward. That is how grantspider's `main` ended up on a staging\n"
    "commit three times in one evening.\n\n"
    "To refresh {branch!r} from its own remote:\n"
    "    git merge --ff-only origin/{branch}\n\n"
    "To pick up {target!r} without moving the branch pointer:\n"
    "    git fetch origin {target}\n\n"
    "To sync every managed checkout safely:\n"
    "    scripts/dev/sync_repos.py\n\n"
    "Deliberate one-off: prefix the command with\n"
    "    CLAUDE_ALLOW_MAIN_GIT=1 <your git command>\n"
)


def pull_target(command: str) -> str | None:
    """The refspec a ``git pull`` names, or ``None``.

    ``None`` covers every safe shape: not a pull at all, a bare ``git pull``
    (which follows the branch's own configured upstream and so can never target
    a foreign ref), or a remote with no refspec.
    """
    match = _PULL.search(command)
    if not match:
        return None
    words = [w for w in match.group("rest").split() if not _FLAG.match(w)]
    # words[0] is the remote, words[1] the refspec. No refspec → upstream pull.
    if len(words) < 2:
        return None
    target = words[1]
    if _IMPLAUSIBLE_REF.search(target) or _IMPLAUSIBLE_REF.search(words[0]):
        return None  # prose or a placeholder, not a runnable pull
    return target


def is_protected(branch: str) -> bool:
    """True if rewriting ``branch``'s pointer is load-bearing."""
    return branch in _PROTECTED


def has_override(command: str) -> bool:
    """True if an override var is set in the environment or as a genuine
    leading assignment on the guarded ``git pull``.

    A bare substring (``echo "CLAUDE_ALLOW_MAIN_GIT=1"``) does not count — the
    assignment must sit at a command position in front of the ``git``.
    """
    if any(os.environ.get(var) == "1" for var in _OVERRIDE_VARS):
        return True
    return bool(_OVERRIDE_PREFIX.search(command))


def should_block(command: str, *, current_branch: str) -> bool:
    """True when this pull would rewrite a protected branch with a foreign ref."""
    if has_override(command):
        return False
    if not is_protected(current_branch):
        return False
    target = pull_target(command)
    return target is not None and target != current_branch


def _current_branch(cwd: str) -> str:
    try:
        result = subprocess.run(  # list-form argv, no shell
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
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
    if pull_target(command) is None:  # cheap reject before shelling out to git
        return 0
    cwd = event.get("cwd") or os.getcwd()
    branch = _current_branch(cwd)
    if not should_block(command, current_branch=branch):
        return 0
    sys.stderr.write(_MESSAGE.format(branch=branch, target=pull_target(command)))
    return 2


if __name__ == "__main__":
    sys.exit(main())

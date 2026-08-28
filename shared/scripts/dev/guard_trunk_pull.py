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

The command line is *lexed*, not pattern-matched, so a pull counts only where
the shell would run it: as the argv of a simple command. A quoted mention — a
commit message, a ``gh issue comment --body``, a heredoc documenting this very
hazard — is an argument, never an invocation, and must not be refused
(OS#401). Lexing is also *stricter* than the regex it replaced: the refspec
plausibility filter now reads the token after the lexer has removed its
quotes, so ``git pull origin 'staging'`` is caught exactly like the bare form
instead of being written off as prose.

This is defence in depth, not the control. Hooks see only Claude Code's Bash
tool — a terminal, a Makefile, direnv or a script all bypass it. Detection and
repair live in ``sync_repos.py``, which is what actually carries the load.

Decision logic is split into pure functions so it is unit-tested without git.
"""

import json
import os
import re
import shlex
import subprocess  # list-form argv, no shell; cwd is the only input
import sys

# Env vars that wave the guard through — same names the sibling guards honour,
# so an operator learns one escape hatch rather than three.
_OVERRIDE_VARS = ("CLAUDE_ALLOW_MAIN_GIT", "GS_ALLOW_MAIN_GIT")

# Branches whose pointer is load-bearing: a promotion target, a deploy source,
# or an integration trunk. Rewriting one silently is the whole hazard.
_PROTECTED = frozenset({"main", "master", "staging"})

# ---------------------------------------------------------------------------
# Shell lexing — a pull counts only where the shell would run it.
#
# DUPLICATE — ``guard_main_worktree.py`` and ``guard_shared_venv.py`` carry
# byte-identical copies of this lexer (``_SEPARATORS``, ``_BACKTICK``,
# ``_ASSIGNMENT`` and the four functions below). It is NOT shared: each hook is
# a standalone byte-copy deployed into other repos' ``.claude/hooks/``, where a
# sibling import would not resolve. A change here must be made in all three.
# ---------------------------------------------------------------------------

# Tokens that end one simple command and start the next, so the token after
# them sits in command position. Grouping and substitution parens count.
_SEPARATORS = frozenset({";", ";;", "&", "&&", "|", "||", "|&", "(", ")", "{", "}"})

# A backtick opens or closes a command substitution, so it ends one simple
# command and starts another exactly as ``;`` does. Unlike the separators
# above it never arrives as a token of its own: it is not shell punctuation to
# the lexer, so ``git pull`` in backticks lexes as ["`git", "pull`"] and the
# split has to be made on the token's own text.
_BACKTICK = "`"

# A leading ``VAR=value`` on a command sets that command's environment; it does
# not displace the command position, so a run of them is skipped over.
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")


def _lex(text: str) -> list[str] | None:
    """``text`` as shell tokens, or None if a quote is left open."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _token_runs(command: str) -> list[list[str]] | None:
    """Tokens of ``command``, one run per line, so a newline ends a command.

    A quote still open at end of line means the quoting spans lines — a
    heredoc, a multi-line PR body — so the whole command is lexed as one unit
    instead, keeping that quoted text a single token rather than reading its
    contents as commands. None means no lexing succeeded at all.
    """
    runs: list[list[str]] = []
    for line in command.splitlines():
        tokens = _lex(line)
        if tokens is None:
            whole = _lex(command)
            return None if whole is None else [whole]
        runs.append(tokens)
    return runs


def _simple_commands(tokens: list[str]) -> list[list[str]]:
    """``tokens`` split at shell separators — one argv per simple command.

    Backticks separate too, and are split out of the token that carries them
    (see :data:`_BACKTICK`). A *quoted* backtick survives that split as prose:
    the lexer has already collapsed ``echo "`git pull`"`` to the single token
    ```git pull```, whose interior space is inside the token, so splitting it
    yields the one word ``git pull`` — never the two-word ``git`` argv a pull
    matches.

    Environment assignments already collected in the enclosing command carry
    into the substitution, so an explicit override written outside a backtick
    still reads as that command's override instead of being stranded in the
    outer argv.
    """
    argvs: list[list[str]] = [[]]

    def _open_command() -> None:
        """Start the next argv, inheriting the current one's assignments."""
        carried, _ = _split_assignments(argvs[-1])
        argvs.append(list(carried))

    for token in tokens:
        if token in _SEPARATORS:
            argvs.append([])
        elif _BACKTICK in token:
            for index, fragment in enumerate(token.split(_BACKTICK)):
                if index:
                    _open_command()
                if fragment:
                    argvs[-1].append(fragment)
        else:
            argvs[-1].append(token)
    return [argv for argv in argvs if argv]


def _split_assignments(argv: list[str]) -> tuple[list[str], list[str]]:
    """``argv`` as (its leading environment assignments, the command it runs)."""
    index = 0
    while index < len(argv) and _ASSIGNMENT.match(argv[index]):
        index += 1
    return argv[:index], argv[index:]


def _invocations(command: str) -> list[tuple[list[str], list[str]]] | None:
    """Every simple command in ``command`` as (env assignments, argv).

    None means the text could not be lexed, which callers treat as
    un-analysable rather than as safe.
    """
    runs = _token_runs(command)
    if runs is None:
        return None
    return [
        _split_assignments(argv) for tokens in runs for argv in _simple_commands(tokens)
    ]


# ---------------------------------------------------------------------------
# Unlexable fallback.
#
# A command with an unbalanced quote is text no shell would run either, but the
# safe direction for a guard is to evaluate it rather than wave it through, so
# the original command-position regex stays as the fallback for that one case.
#
# DUPLICATE — ``guard_main_worktree.py`` and ``check_destructive_command.py``
# carry byte-identical copies of these three lines, for the same reason as the
# lexer above. A change here must be made in all three.
# ---------------------------------------------------------------------------
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
# carry characters no ref ever has. Without this the guard fires on its own
# documentation: ``git pull <remote> <ref>`` in a commit message or a Markdown
# table lexes into ``<`` and ``>`` tokens that no branch could be named. A guard
# that blocks prose gets overridden reflexively, which is exactly how the real
# case goes unguarded.
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


def _is_pull(argv: list[str]) -> bool:
    """True if ``argv`` invokes ``git pull``."""
    return argv[:2] == ["git", "pull"]


def _refspec(words: list[str]) -> str | None:
    """The refspec named by a pull's non-flag arguments, or None.

    ``words[0]`` is the remote and ``words[1]`` the refspec. Fewer than two
    means the pull follows the branch's own configured upstream, which can
    never target a foreign ref.
    """
    if len(words) < 2:
        return None
    target = words[1]
    if _IMPLAUSIBLE_REF.search(target) or _IMPLAUSIBLE_REF.search(words[0]):
        return None  # a placeholder or prose fragment, not a runnable pull
    return target


def _unlexable_pull_target(command: str) -> str | None:
    """The pre-lexer verdict, used only where the text could not be lexed."""
    match = _PULL.search(command)
    if not match:
        return None
    return _refspec([w for w in match.group("rest").split() if not _FLAG.match(w)])


def pull_target(command: str) -> str | None:
    """The refspec a ``git pull`` names, or ``None``.

    ``None`` covers every safe shape: not a pull at all, a bare ``git pull``
    (which follows the branch's own configured upstream and so can never target
    a foreign ref), a remote with no refspec, and a pull named only inside
    quoted text.
    """
    invocations = _invocations(command)
    if invocations is None:
        return _unlexable_pull_target(command)
    for _assignments, argv in invocations:
        if not _is_pull(argv):
            continue
        target = _refspec([w for w in argv[2:] if not _FLAG.match(w)])
        if target is not None:
            return target
    return None


def is_protected(branch: str) -> bool:
    """True if rewriting ``branch``'s pointer is load-bearing."""
    return branch in _PROTECTED


def _inline_override(assignments: list[str]) -> bool:
    """True if this invocation's own ``VAR=value`` prefix carries an override."""
    for assignment in assignments:
        name, _, value = assignment.partition("=")
        if name in _OVERRIDE_VARS and value == "1":
            return True
    return False


def has_override(command: str) -> bool:
    """True if an override var is set in the environment or as a genuine
    leading assignment on the guarded ``git pull``.

    A quoted mention (``echo "CLAUDE_ALLOW_MAIN_GIT=1"``) or a prefix on some
    *other* command does not count — the assignment must be the pull's own.
    """
    if any(os.environ.get(var) == "1" for var in _OVERRIDE_VARS):
        return True
    invocations = _invocations(command)
    if invocations is None:
        return bool(_OVERRIDE_PREFIX.search(command))
    return any(
        _is_pull(argv) and _inline_override(assignments)
        for assignments, argv in invocations
    )


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

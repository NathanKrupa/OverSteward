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
when this tree's ``.venv`` is a symlink resolving outside the tree. Reads are
untouched — ``uv pip list/show/freeze`` are fine — and a tree with a real
``.venv`` directory (every primary checkout) never trips the guard.

``uv run`` is refused too, which is the least obvious entry on that list.
Running a command is not the mutation; the *sync* uv performs first is.
``uv run`` syncs the project environment before it executes anything — that is
why uv documents ``--no-sync`` and ``UV_NO_SYNC`` — so a bare ``uv run`` from a
borrowing tree rebinds the shared venv exactly as ``uv sync`` would, for a
command as harmless-looking as a test run. Observed in the wild: a repo's
shared venv bound to a throwaway dispatch checkout under ``/tmp`` while its
primary checkout silently imported that agent's source. An invocation that
disables the sync (``uv run --no-sync``, or ``UV_NO_SYNC=1`` set on the command
or exported — ``new-session.sh`` writes it into a shared-venv worktree's
``.envrc``) mutates nothing and is allowed.

The escape hatch matches the family convention
(``CLAUDE_ALLOW_MAIN_GIT=1``): ``CLAUDE_ALLOW_SHARED_VENV_MUTATION=1``, honored
either exported in the session or as a genuine leading assignment on the
guarded command. It is deliberately its own variable — the two guards protect
unrelated things and one must not wave the other through.

The command line is *lexed*, not pattern-matched, so a verb counts only where
the shell would run it: as the argv of a simple command. A quoted mention —
``grep "uv sync" file``, a PR body, a heredoc — is an argument, never an
invocation, and must not be refused. Refusing read-only inspection is worse
than useless: it teaches people to reach for the override to run a ``grep``,
which spends the override's meaning on nothing.

Decision logic is split into pure functions so it is unit-tested without git.
"""

import json
import os
import re
import shlex
import subprocess  # list-form argv, no shell; cwd is the only input
import sys
from pathlib import Path
from typing import NamedTuple

_OVERRIDE_VAR = "CLAUDE_ALLOW_SHARED_VENV_MUTATION"

# uv's own opt-out for the implicit sync ``uv run`` performs.
_NO_SYNC_VAR = "UV_NO_SYNC"

# What uv reads as "yes" for a boolean flag taken from the environment. An
# empty or unrecognised value leaves the flag off, so the sync still happens
# and the guard must still refuse.
_TRUE_VALUES = frozenset({"1", "y", "yes", "t", "true", "on"})

# Tokens that end one simple command and start the next, so the token after
# them sits in command position. Grouping and substitution parens count.
_SEPARATORS = frozenset({";", ";;", "&", "&&", "|", "||", "|&", "(", ")", "{", "}"})

# A leading ``VAR=value`` on a command sets that command's environment; it does
# not displace the command position, so a run of them is skipped over.
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")


class _Verb(NamedTuple):
    """One guarded uv invocation: how to recognise it, and what stands it down."""

    label: str
    prefix: tuple[str, ...]  # the argv immediately after ``uv``
    required_flag: str | None = None  # counts only when the argv also carries this
    no_sync_flag: str | None = None  # this flag disables the sync it would do
    no_sync_var: str | None = None  # this variable, set true, disables it


# ``uv lock`` alone only rewrites the lockfile; only ``--upgrade`` (and
# ``--upgrade-package``) re-resolves and re-installs. ``uv run`` syncs the
# project environment before running the command, so it belongs here unless the
# invocation explicitly turns that sync off.
_MUTATING_VERBS: tuple[_Verb, ...] = (
    _Verb("uv pip install", ("pip", "install")),
    _Verb("uv pip uninstall", ("pip", "uninstall")),
    _Verb("uv sync", ("sync",)),
    _Verb("uv add", ("add",)),
    _Verb("uv remove", ("remove",)),
    _Verb("uv venv", ("venv",)),
    _Verb("uv lock --upgrade", ("lock",), required_flag="--upgrade"),
    _Verb("uv run", ("run",), no_sync_flag="--no-sync", no_sync_var=_NO_SYNC_VAR),
)


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
    """``tokens`` split at shell separators — one argv per simple command."""
    argvs: list[list[str]] = [[]]
    for token in tokens:
        if token in _SEPARATORS:
            argvs.append([])
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


def _variable_value(name: str, assignments: list[str]) -> str | None:
    """``name`` as this invocation sees it: its own leading assignment, else the session's.

    A ``VAR=value`` prefix on the command wins over an export, and the last such
    prefix wins over an earlier one — which is what the shell itself does.
    """
    value = None
    for assignment in assignments:
        key, _, candidate = assignment.partition("=")
        if key == name:
            value = candidate
    return os.environ.get(name) if value is None else value


def _reads_as_true(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _TRUE_VALUES


def _sync_disabled(verb: _Verb, assignments: list[str], args: list[str]) -> bool:
    """True if this invocation explicitly turns off the sync ``verb`` would do.

    The flag is matched anywhere in the arguments rather than only within uv's
    own option region. The guard exists to catch an *accidental* sync; anyone
    who writes ``--no-sync`` on the line has said what they want, and anyone who
    means to sync from a borrowing tree has the override.
    """
    if verb.no_sync_flag is not None and verb.no_sync_flag in args:
        return True
    if verb.no_sync_var is None:
        return False
    return _reads_as_true(_variable_value(verb.no_sync_var, assignments))


def _verb_of(assignments: list[str], argv: list[str]) -> str | None:
    """The env-mutating verb ``argv`` invokes, or None if it mutates nothing."""
    if argv[:1] != ["uv"]:
        return None
    args = argv[1:]
    for verb in _MUTATING_VERBS:
        if tuple(args[: len(verb.prefix)]) != verb.prefix:
            continue
        if verb.required_flag is not None and not any(
            arg.startswith(verb.required_flag) for arg in args
        ):
            continue
        if _sync_disabled(verb, assignments, args):
            continue
        return verb.label
    return None


def _unlexable_verb(command: str) -> str | None:
    """A conservative scan for text no lexer could parse — err toward refusing."""
    for verb in _MUTATING_VERBS:
        phrase = r"\buv\s+" + r"\s+".join(verb.prefix) + r"\b"
        if not re.search(phrase, command):
            continue
        if verb.required_flag is not None and verb.required_flag not in command:
            continue
        if verb.no_sync_flag is not None and verb.no_sync_flag in command:
            continue
        if verb.no_sync_var is not None and (
            f"{verb.no_sync_var}=" in command
            or _reads_as_true(os.environ.get(verb.no_sync_var))
        ):
            continue
        return verb.label
    return None


def mutating_verb(command: str) -> str | None:
    """The env-mutating uv verb ``command`` invokes, or None if it invokes none."""
    invocations = _invocations(command)
    if invocations is None:
        return _unlexable_verb(command)
    for assignments, argv in invocations:
        verb = _verb_of(assignments, argv)
        if verb is not None:
            return verb
    return None


def is_env_mutating(command: str) -> bool:
    """True if ``command`` runs a uv verb that syncs or rewrites a venv in place."""
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
    """True if the override is exported, or set as a leading assignment on ``command``.

    Reading it off the invocation's own assignments — not as a substring — is
    what stops a quoted mention (``echo "CLAUDE_ALLOW_SHARED_VENV_MUTATION=1"``)
    waving the guard through.
    """
    if os.environ.get(_OVERRIDE_VAR) == "1":
        return True
    for assignments, argv in _invocations(command) or []:
        if argv[:1] == ["uv"] and f"{_OVERRIDE_VAR}=1" in assignments:
            return True
    return False


def blocked_venv(command: str, tree_root: str) -> str | None:
    """The borrowed venv ``command`` would mutate, or None if it must be allowed.

    Returning the venv rather than a bare verdict lets the refusal name the tree
    that actually owns the environment, which is the whole point of the message.
    """
    if not is_env_mutating(command) or has_override(command):
        return None
    return shared_venv_target(tree_root)


# Verb-specific remedy, shown when the same work has a cheaper route than the
# override. A guard that blocks without naming the alternative teaches people to
# reach for the override, which spends its meaning on ordinary work.
_REMEDIES: dict[str, str] = {
    "uv run": (
        "`uv run` syncs the project environment before it runs anything, so the\n"
        "sync above happens even for a read-only command like a test run. Use the\n"
        "venv's own entry point, which never syncs:\n"
        "    .venv/bin/<tool> <args>              # preferred in a worktree\n"
        "or run uv with the sync turned off:\n"
        "    uv run --no-sync <command>\n"
        f"    {_NO_SYNC_VAR}=1 uv run <command>            # or export it (.envrc does)"
    ),
}


def refusal_message(verb: str, target: str) -> str:
    """The refusal — names the consequence and the way out, not just the rule."""
    paragraphs = [
        f"BLOCKED — `{verb}` in a tree whose .venv is not its own.",
        f"This tree's .venv is a symlink to:\n    {target}",
        "uv would rewrite that SHARED venv's console-script shebangs and its\n"
        "editable-install pointer to THIS tree's path — silently breaking every\n"
        "entry point for every checkout on that venv the moment this tree is\n"
        "removed. The damage stays invisible until then, so the eventual failure\n"
        "looks like a bad install rather than a cross-tree collision.",
        *([_REMEDIES[verb]] if verb in _REMEDIES else []),
        "Run it from the checkout that owns the venv instead, or override:\n"
        f"    {_OVERRIDE_VAR}=1 <your uv command>",
    ]
    return "\n\n".join(paragraphs) + "\n"


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

#!/usr/bin/env python3
# ABOUTME: PreToolUse(Bash) guard — hard-deny hook evasion; ask before destructive commands.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/.claude/hooks/.
"""Two-tier PreToolUse(Bash) guard for destructive and hook-evasion commands.

Two decision classes, checked in this priority order:

1. **Hook-evasion / secret-staging (``deny`` — hard block).** Estate invariant
   I-3: an agent NEVER bypasses git hooks and NEVER blind-stages the tree.
   ``git ... --no-verify``, ``git ... --no-gpg-sign``, ``--admin`` (gh/git),
   ``core.hooksPath`` pointed at ``/dev/null`` or emptied, ``git add -A`` /
   ``git add .``, and staging a real secret file (``git add`` of
   ``.env*`` / ``*.pem`` / ``*.key`` / ``credentials*``). These are never
   legitimate for a dispatch agent, so they are hard-denied — NOT downgradable
   to an ask. This class is checked FIRST so a destructive-pattern match can
   never soften the decision to ``ask``. Placeholder dotenv files
   (``.env.example`` / ``.env.sample`` / ``.env.template`` / ``.env.dist``)
   carry no real values and are legitimately committed — they are carved out.

2. **Destructive-but-sometimes-legitimate (``ask`` — confirm gate).**
   Encodes the pattern table of ``shared/skills/careful.md``: file-system
   destruction (``rm`` of a tree that is not a build artifact, ``shred``/
   ``wipe``), hard-to-reverse git (force push, hard reset, ``clean -f``,
   ``branch -D``, whole-tree discard, rebase), destructive SQL
   (``DROP``/``TRUNCATE``/``DELETE`` without ``WHERE``, ``manage.py flush``),
   container/infra teardown (``docker system prune -a``, ``docker volume rm``,
   ``kubectl delete``), and package-management footguns (``pip install``
   outside a venv, ``npm install -g``).

On a class-2 match the hook does NOT hard-deny — ``careful.md`` is a confirm
gate, not a wall. It emits an ``ask`` permission decision on stdout with a
structured risk explanation. Claude Code surfaces that as a confirmation prompt:
in an interactive session Nathan approves or rejects; in an autonomous/operator
context an unanswered ``ask`` blocks the command. Both match the intent.

``careful.md``'s Safe Exceptions (build-artifact deletes, ``git stash``,
``git branch -d``, ``docker system prune`` without ``-a``) pass through cleanly
— exit 0, no prompt.

**Both tiers decide from lexed argv, not from the raw command string** (OS#402).
A command counts only where the shell would run it, and a flag counts only where
the shell would pass it. That fixes two opposite defects of the pattern scan it
replaces:

* Prose stopped being a command. A ``gh issue comment`` whose heredoc body
  merely *documents* a dangerous command produced a hard ``deny`` an operator
  could not approve past — the body is one argument token after lexing.
* A quoted flag started being a flag. ``git commit -m msg "--no-verify"`` and
  a force-delete whose flags are quoted are real invocations the raw scan read
  as text and let through. Masking quoted regions — the cheap fix for the
  first defect — would have deepened this one, which is why it was not taken.

Lexing is stricter in two further ways. A leading wrapper (``env``,
``command``, ``exec``, ``sudo``, ``nohup``, ``time``) is stripped, so
``env git commit --no-verify`` is the ``git`` invocation it really is. And the
script argument of ``sh -c`` / ``bash -c`` is analysed as a command in its own
right, so quoted text that the shell *will* execute is not mistaken for the
inert quoted text this rewrite deliberately stands down on.

Text with an unbalanced quote cannot be lexed. That is text no shell would run
either, but the safe direction for a guard is to evaluate it rather than wave
it through, so the quote characters are dropped and the result lexed again —
the stricter reading, in which anything hidden by the broken quoting is read as
a command.

Decision logic is split into pure functions so it is unit-tested without a
shell. This is an estate-canonical byte-copy (ratchet treaty): improve here and
redeploy; never edit the ``.claude/hooks/`` copy in isolation.
"""

from __future__ import annotations

import json
import re
import shlex
import sys

# ---------------------------------------------------------------------------
# Shell lexing — a command counts only where the shell would run it.
#
# DUPLICATE — ``guard_main_worktree.py``, ``guard_shared_venv.py`` and
# ``guard_trunk_pull.py`` carry byte-identical copies of this lexer
# (``_SEPARATORS``, ``_BACKTICK``, ``_ASSIGNMENT`` and the four functions
# below). It is NOT shared: each hook is a standalone byte-copy deployed into
# other repos' ``.claude/hooks/``, where a sibling import would not resolve. A
# change here must be made in all four — ``tests/dev/test_hook_lexer_drift.py``
# is what notices when it was not.
# ---------------------------------------------------------------------------

# Tokens that end one simple command and start the next, so the token after
# them sits in command position. Grouping and substitution parens count.
_SEPARATORS = frozenset({";", ";;", "&", "&&", "|", "||", "|&", "(", ")", "{", "}"})

# A backtick opens or closes a command substitution, so it ends one simple
# command and starts another exactly as ``;`` does. Unlike the separators
# above it never arrives as a token of its own: it is not shell punctuation to
# the lexer, so ``rm -rf x`` in backticks lexes as ["`rm", "-rf", "x`"] and the
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
    the lexer has already collapsed ``echo "`rm -rf x`"`` to the single token
    ```rm -rf x```, whose interior spaces are inside the token, so splitting it
    yields the one word ``rm -rf x`` — never the multi-word ``rm`` argv the
    destructive rules match.

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
# Unlexable fallback, wrappers, and nested shells.
# ---------------------------------------------------------------------------

# Quote characters, dropped when the text as written cannot be lexed at all.
_QUOTE_CHARS = str.maketrans("", "", "\"'")

# A leading word that runs another command rather than being one. Stripping it
# exposes the real invocation, so ``env git commit --no-verify`` is the ``git``
# command the shell will run and not an ``env`` the rules do not know.
_WRAPPERS = frozenset({"env", "command", "exec", "sudo", "nohup", "time", "builtin"})
# Wrapper options that consume the token after them as their value, so the
# wrapped program sits one token further along (``sudo -u nathan rm ...``,
# ``env -u NAME ...``). Without this the value reads as the program and the
# real command is never inspected.
_WRAPPER_VALUE_FLAGS = frozenset({"-u", "-g", "-p", "-C", "-h", "-r", "-t", "-T", "-U", "-S"})

# ``sh -c '<script>'`` hands the shell text to execute. That text IS a command,
# so it is analysed as one — otherwise standing down on quoted text (the whole
# point of lexing) would open a bypass for the one quoted form that does run.
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
_SCRIPT_FLAGS = frozenset({"-c", "-lc", "-ic", "-xc"})
_MAX_SHELL_DEPTH = 3


def _basename(token: str) -> str:
    """The final path segment of ``token`` — ``/usr/bin/rm`` is still ``rm``."""
    return token.rsplit("/", 1)[-1]


def _command_name(argv: list[str]) -> str:
    """The program ``argv`` runs, path stripped."""
    return _basename(argv[0]) if argv else ""


def _unwrap(argv: list[str]) -> list[str]:
    """``argv`` with any leading wrapper words and their options removed."""
    while argv and _command_name(argv) in _WRAPPERS:
        rest = argv[1:]
        while rest and (_ASSIGNMENT.match(rest[0]) or rest[0].startswith("-")):
            consumed = 2 if rest[0] in _WRAPPER_VALUE_FLAGS and len(rest) > 1 else 1
            rest = rest[consumed:]
        argv = rest
    return argv


def _shell_script(argv: list[str]) -> str | None:
    """The script text ``argv`` hands to a shell to execute, or None."""
    if _command_name(argv) not in _SHELLS:
        return None
    for index, token in enumerate(argv[1:], start=1):
        if token in _SCRIPT_FLAGS and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _fallback_invocations(command: str) -> list[tuple[list[str], list[str]]]:
    """Argv for text no lexer accepts — quotes dropped so nothing hides in them.

    An unbalanced quote is text no shell would run either, but the safe
    direction for a guard is to evaluate it rather than wave it through. With
    the quote characters removed the same lexer usually succeeds, and anything
    that was hiding inside the broken quoting reads as a command instead of an
    argument. Whitespace splitting is the last resort, for text even that
    cannot lex.
    """
    stripped = command.translate(_QUOTE_CHARS)
    invocations = _invocations(stripped)
    if invocations is not None:
        return invocations
    return [
        _split_assignments(line.split())
        for line in stripped.splitlines()
        if line.split()
    ]


def _expand(argvs: list[list[str]], depth: int) -> list[list[str]]:
    """``argvs`` unwrapped, plus the argv of any script handed to a shell."""
    expanded: list[list[str]] = []
    for raw in argvs:
        argv = _unwrap(raw)
        if not argv:
            continue
        expanded.append(argv)
        script = _shell_script(argv)
        if script is not None and depth < _MAX_SHELL_DEPTH:
            expanded.extend(_expand(_argvs_of(script), depth + 1))
    return expanded


def _argvs_of(command: str) -> list[list[str]]:
    """The argv of every simple command in ``command``, before expansion."""
    invocations = _invocations(command)
    if invocations is None:
        invocations = _fallback_invocations(command)
    return [argv for _assignments, argv in invocations]


def _all_argvs(command: str) -> list[list[str]]:
    """Every command the shell would run, as argv the rules can inspect."""
    return _expand(_argvs_of(command), depth=0)


# ---------------------------------------------------------------------------
# Argument inspection helpers, shared by both rule tables.
# ---------------------------------------------------------------------------


def _short_flags(argv: list[str]) -> str:
    """Every letter carried by a short-option token in ``argv``."""
    letters = []
    for token in argv[1:]:
        if token.startswith("-") and not token.startswith("--") and len(token) > 1:
            letters.append(token[1:])
    return "".join(letters)


def _has_short_flag(argv: list[str], letter: str) -> bool:
    """True if a short option in ``argv`` carries ``letter`` (case-sensitive)."""
    return letter in _short_flags(argv)


def _operands(argv: list[str]) -> list[str]:
    """The non-flag arguments of ``argv`` — its targets."""
    return [token for token in argv[1:] if token != "--" and not token.startswith("-")]


def _is_verb(argv: list[str], program: str, *verbs: str) -> bool:
    """True if ``argv`` runs ``program`` with ``verbs`` as its leading words."""
    if _command_name(argv) != program:
        return False
    return argv[1 : 1 + len(verbs)] == list(verbs)


# Program and option names the rule tables repeat.
_GIT = "git"
_FORCE_FLAG = "--force"
_INSTALL_VERB = "install"


# ---------------------------------------------------------------------------
# Class 2 — destructive-but-sometimes-legitimate detectors (``ask``).
# ---------------------------------------------------------------------------

# Build-artifact directories that a recursive delete may target without a
# prompt (careful.md Safe Exceptions). Matched as whole path segments so a
# stray ``build_prod_data`` is NOT treated as the safe ``build``.
_SAFE_RM_TARGETS = (
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
)
# ``*.egg-info`` is a glob rather than a fixed name.
_SAFE_EGG_INFO = re.compile(r"^[\w.-]*\.egg-info$")


def _all_safe_rm_targets(argv: list[str]) -> bool:
    """True if every target of this ``rm`` is a recognized build artifact.

    An ``rm`` with no explicit target (e.g. a bare glob resolved by the shell)
    is not classifiable as safe here — callers only reach this after deciding a
    prompt is otherwise warranted, so unknown → not-safe (fall through to ask).
    """
    targets = _operands(argv)
    if not targets:
        return False
    for target in targets:
        stripped = target.rstrip("/")
        if stripped.startswith("./"):
            stripped = stripped[2:]
        if stripped in _SAFE_RM_TARGETS:
            continue
        if _SAFE_EGG_INFO.match(_basename(stripped)):
            continue
        return False
    return True


def _is_rm(argv: list[str]) -> bool:
    """True if ``argv`` runs ``rm``."""
    return _command_name(argv) == "rm"


def _rm_recursive(argv: list[str]) -> bool:
    """True if this ``rm`` was asked to descend into directories."""
    return _has_short_flag(argv, "r") or _has_short_flag(argv, "R") or "--recursive" in argv


def _rm_forced(argv: list[str]) -> bool:
    """True if this ``rm`` was asked to suppress every confirmation."""
    return _has_short_flag(argv, "f") or _FORCE_FLAG in argv


def _rm_destructive(argv: list[str]) -> bool:
    """A forced recursive delete that is NOT confined to build artifacts."""
    return (
        _is_rm(argv)
        and _rm_recursive(argv)
        and _rm_forced(argv)
        and not _all_safe_rm_targets(argv)
    )


def _rm_r_destructive(argv: list[str]) -> bool:
    """A recursive delete that is NOT confined to build artifacts."""
    return _is_rm(argv) and _rm_recursive(argv) and not _all_safe_rm_targets(argv)


def _rm_glob(argv: list[str]) -> bool:
    """An ``rm`` whose targets are chosen by an unexpanded glob."""
    return _is_rm(argv) and any("*" in operand for operand in _operands(argv))


def _shred(argv: list[str]) -> bool:
    """A tool whose whole purpose is unrecoverable destruction."""
    return _command_name(argv) in {"shred", "wipe"}


def _git_push_force(argv: list[str]) -> bool:
    """A push that overwrites remote history (``--force-with-lease`` is safe)."""
    return _is_verb(argv, _GIT, "push") and (
        _FORCE_FLAG in argv[2:] or "-f" in argv[2:]
    )


def _git_reset_hard(argv: list[str]) -> bool:
    return _is_verb(argv, _GIT, "reset") and "--hard" in argv[2:]


def _git_clean_force(argv: list[str]) -> bool:
    return _is_verb(argv, _GIT, "clean") and (
        _has_short_flag(argv, "f") or _FORCE_FLAG in argv[2:]
    )


def _git_branch_force_delete(argv: list[str]) -> bool:
    return _is_verb(argv, _GIT, "branch") and "-D" in argv[2:]


def _git_discard_all(argv: list[str]) -> bool:
    """``git checkout .`` / ``git restore .`` — the whole working tree."""
    return (
        _command_name(argv) == _GIT
        and argv[1:2] in (["checkout"], ["restore"])
        and "." in argv[2:]
    )


def _git_rebase(argv: list[str]) -> bool:
    return _is_verb(argv, _GIT, "rebase")


def _docker_prune_all(argv: list[str]) -> bool:
    return _is_verb(argv, "docker", "system", "prune") and (
        _has_short_flag(argv, "a") or "--all" in argv[3:]
    )


def _docker_volume_rm(argv: list[str]) -> bool:
    return _is_verb(argv, "docker", "volume", "rm")


def _kubectl_delete(argv: list[str]) -> bool:
    return _is_verb(argv, "kubectl", "delete")


def _npm_install_global(argv: list[str]) -> bool:
    return (
        _command_name(argv) == "npm"
        and argv[1:2] in ([_INSTALL_VERB], ["i"])
        and (_has_short_flag(argv, "g") or "--global" in argv[2:])
    )


# ``pip``/``pip3`` directly, or ``python -m pip``.
_PIP_NAME = re.compile(r"pip[0-9.]*")
_PYTHON_NAME = re.compile(r"python[0-9.]*")
# A path that places the interpreter inside an isolated environment.
_VENV_PIP_PATH = re.compile(r"(?:\.?venv|virtualenv|env)/bin/pip")


def _is_pip_install(argv: list[str]) -> bool:
    """True if ``argv`` installs a package with pip."""
    name = _command_name(argv)
    if _PIP_NAME.fullmatch(name) and _INSTALL_VERB in argv[1:]:
        return True
    return bool(
        _PYTHON_NAME.fullmatch(name)
        and argv[1:3] == ["-m", "pip"]
        and _INSTALL_VERB in argv[3:]
    )


def _pip_outside_venv(argv: list[str]) -> bool:
    """True if a ``pip install`` runs and no venv marker is present.

    careful.md flags ``pip install`` OUTSIDE a virtual environment. An
    explicitly venv-qualified invocation (``.venv/bin/pip``, ``uv pip``,
    ``pipx``, a ``--user`` install) is in-scope of an isolated environment and
    passes through. A venv-managing front end (``uv``, ``poetry`` ...) is
    ``argv[0]`` in its own right, so pip is not the program being run and this
    detector never fires on it. Heuristic and conservative: when unsure, ask.
    """
    if not _is_pip_install(argv):
        return False
    if _VENV_PIP_PATH.search(argv[0]):
        return False
    return "--user" not in argv


# Database ------------------------------------------------------------------
# A pure text search/print tool leading a command treats SQL keywords as DATA,
# not a statement to run. When such a tool runs and NO database client appears
# anywhere in the command, the SQL detectors stand down (``grep 'DROP TABLE'
# migrations/`` is not a destructive op).
_TEXT_TOOLS = frozenset(
    {
        "grep", "egrep", "fgrep", "rg", "ack", "cat", "less", "more",
        "head", "tail", "awk", "sed", "echo", "printf",
    }
)
# A database client anywhere in the command — as the program run, or as an
# argument to one (``docker exec -it db psql`` is a real shape). This is a
# *suppressor's escape clause*, not a detector: a miss here does not lose one
# detection, it inverts the verdict on a command the shell is about to run
# (OS#307). So it is read across every token of every command, not just argv[0].
_DB_CLIENTS = frozenset(
    {
        "psql", "mysql", "sqlite", "sqlite3", "mongo", "redis-cli",
        "clickhouse-client", "dbshell", "db_scratch", "alembic",
    }
)
# Clients spelled as two words. Each pair is (program, subcommand).
_DB_CLIENT_PAIRS = (("cockroach", "sql"), ("db", "scratch"), ("manage.py", "dbshell"))

_SQL_DROP_TRUNCATE = re.compile(r"\b(?:DROP\s+(?:TABLE|DATABASE)|TRUNCATE)\b", re.IGNORECASE)


def _statement(argv: list[str]) -> str:
    """``argv`` rejoined as the text the SQL detectors read.

    The tokens are one command's real arguments, so a quoted statement is
    rejoined exactly as it was written and a mention inside some *other*
    command's argument cannot bleed into it.
    """
    return " ".join(argv)


def _runs_db_client(argvs: list[list[str]]) -> bool:
    """True if any token of any command names a database client."""
    for argv in argvs:
        words = [_basename(token) for token in argv]
        for index, word in enumerate(words):
            if word in _DB_CLIENTS:
                return True
            if (word, *words[index + 1 : index + 2]) in _DB_CLIENT_PAIRS:
                return True
    return False


def _is_sql_data_only(argvs: list[list[str]]) -> bool:
    """True if SQL keywords here are inert data (text tool, no DB client).

    The ``not`` is what makes this the one place where a *narrow* pattern is the
    unsafe direction. Everywhere else a missed match means one command is not
    flagged; here it means the guard concludes the SQL is being printed.
    """
    leads_with_text_tool = any(_command_name(argv) in _TEXT_TOOLS for argv in argvs)
    return leads_with_text_tool and not _runs_db_client(argvs)


def _sql_delete_without_where(statement: str) -> bool:
    """True if a ``DELETE FROM <table>`` has no ``WHERE`` clause before its end."""
    for match in re.finditer(r"\bDELETE\s+FROM\s+[\w.\"'`]+", statement, re.IGNORECASE):
        tail = statement[match.end():]
        # The statement ends at the next ``;`` (or end of string).
        stmt_end = tail.find(";")
        clause = tail if stmt_end == -1 else tail[:stmt_end]
        if not re.search(r"\bWHERE\b", clause, re.IGNORECASE):
            return True
    return False


def _drop_truncate_exec(argvs: list[list[str]]) -> bool:
    """A DROP/TRUNCATE actually executed (not searched/printed as text)."""
    if _is_sql_data_only(argvs):
        return False
    return any(_SQL_DROP_TRUNCATE.search(_statement(argv)) for argv in argvs)


def _delete_no_where(argvs: list[list[str]]) -> bool:
    """A ``DELETE FROM`` with no ``WHERE`` clause, executed (not inert text)."""
    if _is_sql_data_only(argvs):
        return False
    return any(_sql_delete_without_where(_statement(argv)) for argv in argvs)


def _manage_flush(argv: list[str]) -> bool:
    """``manage.py flush`` — Django's delete-every-row command."""
    for index, token in enumerate(argv):
        if _basename(token) == "manage.py" and argv[index + 1 : index + 2] == ["flush"]:
            return True
    return False


# Each rule's detector is a predicate over every argv in the command. Most
# rules read one command at a time, so ``_any_argv`` lifts a single-argv
# predicate into that shape; the SQL rules need the whole command (a client in
# one pipeline stage governs SQL written in another) and take it directly.
def _any_argv(predicate: object) -> "object":
    """Lift a per-argv predicate to one over every argv in the command."""
    return lambda argvs: any(predicate(argv) for argv in argvs)  # type: ignore[operator]


# The rule table, in priority order — the FIRST matching rule wins the prompt so
# the risk message names the most specific concern. Each row is
# ``(category, predicate, risk)``. careful.md's pattern table maps 1:1 here.
_RULES: tuple[tuple[str, object, str], ...] = (
    # File system
    ("rm -rf", _any_argv(_rm_destructive),
     "recursively force-deletes files that are not recognized build artifacts"),
    ("shred/wipe", _any_argv(_shred), "securely and irreversibly destroys file data"),
    ("rm -r", _any_argv(_rm_r_destructive), "recursively deletes a directory tree"),
    ("rm glob", _any_argv(_rm_glob),
     "deletes files matched by a glob — potentially many, unreviewed"),
    # Git — hard to reverse
    ("git push --force", _any_argv(_git_push_force),
     "overwrites remote history and can clobber others' commits"),
    ("git reset --hard", _any_argv(_git_reset_hard),
     "discards all uncommitted changes and moves the branch pointer"),
    ("git clean -f", _any_argv(_git_clean_force),
     "permanently deletes untracked files (drafts, notes, artifacts)"),
    ("git branch -D", _any_argv(_git_branch_force_delete),
     "force-deletes a branch even if it holds unmerged commits"),
    ("git checkout/restore .", _any_argv(_git_discard_all),
     "discards ALL working-tree changes"),
    ("git rebase", _any_argv(_git_rebase),
     "rewrites commit history — dangerous on a shared branch"),
    # Database
    ("DROP/TRUNCATE", _drop_truncate_exec,
     "drops or truncates a table or database — irreversible data loss"),
    ("DELETE without WHERE", _delete_no_where, "deletes every row in the table"),
    ("manage.py flush", _any_argv(_manage_flush), "deletes all data from the database"),
    # Container / infrastructure
    ("docker system prune -a", _any_argv(_docker_prune_all),
     "removes all unused images, not just dangling ones"),
    ("docker volume rm", _any_argv(_docker_volume_rm),
     "destroys a data volume — persisted data is lost"),
    ("kubectl delete", _any_argv(_kubectl_delete), "tears down a live cluster resource"),
    # Package management
    ("npm install -g", _any_argv(_npm_install_global),
     "installs a project tool globally, polluting the system environment"),
    ("pip install outside a venv", _any_argv(_pip_outside_venv),
     "installs into the system/base Python instead of a virtual environment"),
)


def _match(command: str) -> tuple[str, str] | None:
    """Return (category, risk) for the first destructive pattern matched."""
    argvs = _all_argvs(command)
    for category, predicate, risk in _RULES:
        if predicate(argvs):  # type: ignore[operator]
            return (category, risk)
    return None


# ---------------------------------------------------------------------------
# Class 1 — git-hook-evasion / secret-staging detectors (hard ``deny``).
#
# Estate invariant I-3: a dispatch agent NEVER bypasses git hooks and NEVER
# blind-stages the working tree. Every shape below is unambiguously an evasion
# — there is no legitimate agent use — so it is hard-denied rather than gated
# with an ``ask``. These are checked BEFORE the class-2 destructive rules so a
# destructive-pattern match can never downgrade the decision to ``ask``.
# ---------------------------------------------------------------------------

# The git config key whose neutering disables every repository hook, and the
# values that neuter it. Read only inside a ``git`` invocation: a mention in
# some other command's argument is text, and only git applies the setting.
_HOOKSPATH_KEY = "core.hookspath"
_NEUTERED_VALUES = frozenset({"", "/dev/null"})

# Secret files that must never be staged. A placeholder dotenv (``.env.example``
# and friends) carries no real values and is legitimately committed — carved
# out below so only real secret files trip the guard.
_SECRET_PLACEHOLDER_SUFFIXES = (".example", ".sample", ".template", ".dist")
# A single ``git add`` argument that names a secret file. ``.env`` and any
# ``.env.<x>`` variant, plus ``*.pem`` / ``*.key`` / ``credentials*``.
_SECRET_ARG = re.compile(
    r"(?:^|/)(?:\.env(?:\.[\w.-]+)?|[\w.-]*\.pem|[\w.-]*\.key|credentials[\w.-]*)$"
)


def _is_git(argv: list[str]) -> bool:
    """True if ``argv`` runs git."""
    return _command_name(argv) == _GIT


def _git_flag(argv: list[str], flag: str) -> bool:
    """True if ``argv`` is a git command carrying ``flag`` as a real argument.

    The flag has to be a token of its own. A flag *named* inside a commit
    message or a PR body is one word of that argument, never an argument.
    """
    return _is_git(argv) and flag in argv[1:]


def _git_no_verify(argv: list[str]) -> bool:
    return _git_flag(argv, "--no-verify")


def _git_no_gpg_sign(argv: list[str]) -> bool:
    return _git_flag(argv, "--no-gpg-sign")


def _admin_bypass(argv: list[str]) -> bool:
    """``--admin`` on gh or git — a branch-protection / required-check bypass."""
    return _command_name(argv) in {"gh", _GIT} and "--admin" in argv[1:]


def _hookspath_neutered(argv: list[str]) -> bool:
    """A git command that points ``core.hooksPath`` at nothing."""
    if not _is_git(argv):
        return False
    for index, token in enumerate(argv[1:], start=1):
        key, separator, value = token.partition("=")
        if key.lower() != _HOOKSPATH_KEY:
            continue
        if separator:
            return value in _NEUTERED_VALUES
        following = argv[index + 1 : index + 2]
        return not following or following[0] in _NEUTERED_VALUES
    return False


def _git_add_all(argv: list[str]) -> bool:
    """``git add -A`` / ``--all`` / ``.`` — blind whole-tree staging."""
    if not _is_verb(argv, _GIT, "add"):
        return False
    return any(token in {"-A", "--all", "."} for token in argv[2:])


def _is_placeholder_dotenv(arg: str) -> bool:
    """True for ``.env.example`` / ``.sample`` / ``.template`` / ``.dist``."""
    base = _basename(arg)
    return any(base.endswith(sfx) for sfx in _SECRET_PLACEHOLDER_SUFFIXES)


def _stages_secret(argv: list[str]) -> bool:
    """True if this ``git add`` names a real secret file (placeholders exempt)."""
    if not _is_verb(argv, _GIT, "add"):
        return False
    return any(
        _SECRET_ARG.search(arg) and not _is_placeholder_dotenv(arg)
        for arg in _operands(argv)[1:]
    )


def _stages_secret_file(command: str) -> bool:
    """True if any ``git add`` in ``command`` names a real secret file."""
    return any(_stages_secret(argv) for argv in _all_argvs(command))


# Evasion rule table, in priority order. Each row is ``(category, predicate,
# reason)`` where ``reason`` completes "This ..." in the deny message.
_EVASION_RULES: tuple[tuple[str, object, str], ...] = (
    ("git --no-verify", _any_argv(_git_no_verify),
     "bypasses the pre-commit / commit-msg hooks that guard every commit"),
    ("git --no-gpg-sign", _any_argv(_git_no_gpg_sign),
     "skips commit signing, defeating provenance verification"),
    ("--admin bypass", _any_argv(_admin_bypass),
     "bypasses branch-protection and required-check gates"),
    ("core.hooksPath disabled", _any_argv(_hookspath_neutered),
     "redirects git's hooks path to nothing, disabling all repository hooks"),
    ("git add -A / .", _any_argv(_git_add_all),
     "blind-stages the entire working tree instead of explicit paths"),
    ("git add of a secret file", _any_argv(_stages_secret),
     "stages a secret file (.env / *.pem / *.key / credentials*) into a commit"),
)


def _match_hook_evasion(command: str) -> tuple[str, str] | None:
    """Return (category, reason) for the first hook-evasion pattern matched."""
    argvs = _all_argvs(command)
    for category, predicate, reason in _EVASION_RULES:
        if predicate(argvs):  # type: ignore[operator]
            return (category, reason)
    return None


def _deny_message(category: str, reason: str, command: str) -> str:
    """Human-readable hard-block explanation surfaced with the deny decision."""
    return (
        "HOOK-EVASION / SECRET-STAGING — hard blocked (estate invariant I-3)\n\n"
        f"Command: {command.strip()}\n"
        f"Pattern: {category}\n"
        f"Reason: This {reason}.\n\n"
        "I-3: a dispatch agent never bypasses git hooks and never blind-stages "
        "the tree. This is not an ask you can approve — remove the bypass flag "
        "and stage explicit, non-secret paths instead."
    )


def _emit_deny(reason: str) -> None:
    """Emit a ``deny`` PreToolUse permission decision on stdout and exit 0."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(output))
    sys.exit(0)


def _ask_message(category: str, risk: str, command: str) -> str:
    """Human-readable risk explanation surfaced with the ask prompt."""
    return (
        "DESTRUCTIVE COMMAND — confirmation required\n\n"
        f"Command: {command.strip()}\n"
        f"Pattern: {category}\n"
        f"Risk: This {risk}.\n\n"
        "careful.md is a confirm gate: review the command and approve only if "
        "the destruction is intended. Safe alternatives or a narrower scope are "
        "often available. Full rule: shared/skills/careful.md"
    )


def _emit_ask(reason: str) -> None:
    """Emit an ``ask`` PreToolUse permission decision on stdout and exit 0."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }
    sys.stdout.write(json.dumps(output))
    sys.exit(0)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return 0  # unparseable input → do not block
    if not isinstance(event, dict):
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = (event.get("tool_input") or {}).get("command", "") or ""
    if not command:
        return 0

    # Class 1 first — hook evasion is a hard ``deny`` and must never be
    # downgradable to a class-2 ``ask``.
    evasion = _match_hook_evasion(command)
    if evasion is not None:
        category, reason = evasion
        _emit_deny(_deny_message(category, reason, command))
        return 0  # _emit_deny exits; unreachable, kept for type clarity

    hit = _match(command)
    if hit is None:
        return 0
    category, risk = hit
    _emit_ask(_ask_message(category, risk, command))
    return 0  # _emit_ask exits; unreachable, kept for type clarity


if __name__ == "__main__":
    sys.exit(main())

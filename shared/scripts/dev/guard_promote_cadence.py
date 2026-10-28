#!/usr/bin/env python3
# ABOUTME: PreToolUse(Bash) guard — refuse a GrantSpider staging->main promote within 6 days of the last.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/.claude/hooks/.
"""Hold GrantSpider's staging→main promotes to a weekly cadence.

Every push to grantspider ``main`` runs ``neon-integration``, which averages
103 Actions minutes. October 2026 had 40 such pushes, about 4,100 minutes
(~$33), and half of those runs were red and ignored. The doctrine was already
a weekly promote ("the Tuesday promotion PR") with local gates primary and CI
as the watchdog, and sessions promoted per fix anyway. A memory note is an
inert control, so this refuses instead (OS#634).

**Trigger.** Opening a pull request on NathanKrupa/grantspider with base
``main`` and head ``staging``, in either form:

* ``gh pr create`` (or its alias ``gh pr new``). The repo is ``--repo``/``-R``,
  else ``GH_REPO`` (the command's own prefix, then the session environment),
  else the ``origin`` of the directory the command runs in, following any
  ``cd`` earlier in the same command. An omitted ``--base`` is the repo's
  default branch, which for grantspider is ``staging``, so it is not a
  promote. An omitted ``--head`` is the checked-out branch.
* ``gh api`` POST to ``repos/NathanKrupa/grantspider/pulls`` with fields
  ``base=main`` and ``head=staging``. A body sent with ``--input`` cannot be
  read here, so it is treated as a promote: inside the window it is refused
  and can be overridden, outside it passes.

**Wrappers.** ``gh`` is found behind ``env`` (its ``VAR=value`` words count
as the command's own environment, ``-C``/``--chdir`` moves its directory),
``command``, ``exec``, ``nohup``, ``time`` and ``timeout``, and inside the
script of ``bash``/``sh``/``zsh``/``dash`` ``-c``, which inherits the
directory and environment prefix around it. Those are the only wrappers seen:
any other prefix hides ``gh`` — for example ``nice``, ``stdbuf``, ``setsid``,
``xargs``, ``sudo``, ``env -S``, aliases, shell functions, ``eval`` and
scripts on disk.

A head or repo this guard could not read is treated as a promote rather than
waved through — an unexpanded ``cd "$GS"``, a directory with no readable
``origin``, an unresolvable ``{owner}/{repo}``. That costs one lookup and
refuses only inside the window. Everything it *could* read and found to be
some other repo, base or head passes untouched, and never reaches GitHub.

**Rule.** Ask GitHub for the most recent merged PR into ``main`` from
``staging``. Under :data:`CADENCE` ago, refuse, naming its date and the next
allowed moment. If GitHub cannot be asked, refuse with a different message:
"could not look" never reads as "too soon", and never as an allow.

**Override.** A hotfix that cannot wait prefixes the promote itself with a
reason, recorded on the hook's stderr:

    GS_PROMOTE_HOTFIX='<why this cannot wait>' gh pr create ...

An empty or blank reason does not count. Only the promote's own environment
counts — its prefix, an ``env`` word before it, or the prefix of the
``bash -c`` running it. The variable in the session environment, or on
another command, does not.

**Unlexable text** (an unbalanced quote) is allowed: no shell would run it
either, and it never reaches ``gh``.

This is defence in depth, not the control. Hooks see only Claude Code's Bash
tool — a terminal, the GitHub web UI or a script all bypass it.

GitHub, git and the clock are parameters of :func:`evaluate`, so the decision
is unit-tested without network or repositories.
"""

import json
import os
import re
import shlex
import subprocess  # list-form argv, no shell
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

GS_REPO = "nathankrupa/grantspider"
TRUNK = "main"
SOURCE = "staging"
CADENCE = timedelta(days=6)
OVERRIDE_VAR = "GS_PROMOTE_HOTFIX"
GH_REPO_VAR = "GH_REPO"

# Its merge updated the newest merged staging→main PR, so only closed
# staging→main PRs touched since then can rank above it. Unverified assumption:
# fewer than 100 of those exist; were there more, an older merge would be read.
_LOOKUP_ENDPOINT = (
    "repos/NathanKrupa/grantspider/pulls?state=closed&base=main"
    "&head=NathanKrupa:staging&sort=updated&direction=desc&per_page=100"
)

# ---------------------------------------------------------------------------
# Shell lexing — a gh invocation counts only where the shell would run it.
#
# DUPLICATE — ``check_destructive_command.py``, ``guard_main_worktree.py``,
# ``guard_shared_venv.py`` and ``guard_trunk_pull.py`` carry byte-identical
# copies of this lexer (``_SEPARATORS``, ``_BACKTICK``, ``_ASSIGNMENT`` and the
# four functions below). It is NOT shared: each hook is a standalone byte-copy
# deployed into other repos' ``.claude/hooks/``, where a sibling import would
# not resolve. ``tests/dev/test_hook_lexer_drift.py`` notices when one drifts.
# ---------------------------------------------------------------------------

# Tokens that end one simple command and start the next, so the token after
# them sits in command position. Grouping and substitution parens count.
_SEPARATORS = frozenset({";", ";;", "&", "&&", "|", "||", "|&", "(", ")", "{", "}"})

# A backtick opens or closes a command substitution, so it ends one simple
# command and starts another exactly as ``;`` does. It never arrives as a token
# of its own, so the split has to be made on the token's own text.
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
    instead. None means no lexing succeeded at all.
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

    Backticks separate too, and environment assignments already collected in
    the enclosing command carry into the substitution.
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

    None means the text could not be lexed.
    """
    runs = _token_runs(command)
    if runs is None:
        return None
    return [
        _split_assignments(argv) for tokens in runs for argv in _simple_commands(tokens)
    ]


# ---------------------------------------------------------------------------
# The seams: git, GitHub, and what each answers.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Checkout:
    """What a directory's git says: its ``origin`` URL and checked-out branch."""

    origin: str | None
    branch: str | None


@dataclass(frozen=True)
class LastPromote:
    """The most recent merged staging→main pull request."""

    number: int
    merged_at: datetime


class LookupFailed(Exception):
    """GitHub could not be asked, or its answer could not be read."""


ReadCheckout = Callable[[str], Checkout]
ReadLastPromote = Callable[[], "LastPromote | None"]


def _git(path: str, *args: str) -> str | None:
    try:
        result = subprocess.run(  # list-form argv, no shell
            ["git", "-C", path, *args], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (result.stdout.strip() or None) if result.returncode == 0 else None


def read_git_checkout(path: str) -> Checkout:
    """The real :data:`ReadCheckout`: ``git`` run against ``path``."""
    return Checkout(
        origin=_git(path, "remote", "get-url", "origin"),
        branch=_git(path, "rev-parse", "--abbrev-ref", "HEAD"),
    )


def latest_merge(payload: str) -> LastPromote | None:
    """The newest merged staging→main PR in a ``gh api`` pulls listing, or None.

    The base and head are checked here as well as in the query, so a filter
    GitHub ignored can never count an unrelated merge as a promote.
    """
    try:
        pulls = json.loads(payload)
        if not isinstance(pulls, list):
            raise TypeError(f"expected a list of pull requests, got {type(pulls).__name__}")
        merges = [
            LastPromote(int(pull["number"]), datetime.fromisoformat(pull["merged_at"]))
            for pull in pulls
            if pull["merged_at"]
            and pull["base"]["ref"] == TRUNK
            and pull["head"]["ref"] == SOURCE
        ]
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise LookupFailed(f"unreadable gh api answer: {exc!r}") from exc
    return max(merges, key=lambda merge: merge.merged_at, default=None)


def read_github_last_promote() -> LastPromote | None:
    """The real :data:`ReadLastPromote`: ``gh api`` against grantspider's pulls."""
    try:
        result = subprocess.run(  # list-form argv, no shell
            ["gh", "api", _LOOKUP_ENDPOINT],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LookupFailed(f"gh api did not run: {exc!r}") from exc
    if result.returncode != 0:
        detail = (result.stderr.strip().splitlines() or ["no output"])[-1]
        raise LookupFailed(f"gh api exited {result.returncode}: {detail}")
    return latest_merge(result.stdout)


# ---------------------------------------------------------------------------
# Reading a gh command line.
# ---------------------------------------------------------------------------

# Flags that take a value, so the word after them is that value, never a flag
# or a positional. Taken from ``gh pr create --help`` and ``gh api --help``.
_PR_CREATE_VALUE_FLAGS = frozenset(
    {
        "-a", "--assignee", "-B", "--base", "-b", "--body", "-F", "--body-file",
        "-H", "--head", "-l", "--label", "-m", "--milestone", "-p", "--project",
        "-r", "--reviewer", "-T", "--template", "-t", "--title", "-R", "--repo",
        "--recover",
    }
)
_API_VALUE_FLAGS = frozenset(
    {
        "-X", "--method", "-f", "--raw-field", "-F", "--field", "-H", "--header",
        "--input", "-q", "--jq", "-t", "--template", "--hostname", "--cache",
        "-p", "--preview",
    }
)
_API_FIELD_FLAGS = frozenset({"-f", "--raw-field", "-F", "--field"})
_PULLS_ENDPOINT = re.compile(r"^/?repos/([^/]+)/([^/]+)/pulls/?$")


def _options(args: list[str], value_flags: frozenset[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """``args`` as ((flag, value) pairs in order, positionals). Boolean flags drop out."""
    pairs: list[tuple[str, str]] = []
    positionals: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            positionals.extend(args[index + 1 :])
            break
        if arg.startswith("--") and "=" in arg:
            name, _, value = arg.partition("=")
            pairs.append((name, value))
        elif arg in value_flags:
            if index + 1 < len(args):
                pairs.append((arg, args[index + 1]))
            index += 1
        elif not arg.startswith("--") and arg[:2] in value_flags and len(arg) > 2:
            pairs.append((arg[:2], arg[2:].removeprefix("=")))
        elif not arg.startswith("-"):
            positionals.append(arg)
        index += 1
    return pairs, positionals


def _last(pairs: list[tuple[str, str]], *names: str) -> str | None:
    """The value of the last of ``names`` given — the one gh would use."""
    values = [value for name, value in pairs if name in names]
    return values[-1] if values else None


def _assigned(assignments: list[str], name: str) -> str | None:
    """The value a ``NAME=value`` prefix gives ``name``, or None when absent."""
    values = [a.partition("=")[2] for a in assignments if a.partition("=")[0] == name]
    return values[-1] if values else None


def _slug(text: str | None) -> str | None:
    """``owner/repo``, lower-cased, from a repo argument or a git remote URL."""
    if not text:
        return None
    parts = [p for p in re.split(r"[/:]", text.strip().rstrip("/").removesuffix(".git")) if p]
    return "/".join(parts[-2:]).lower() if len(parts) >= 2 else None


def _branch(ref: str | None) -> str | None:
    """A branch name from ``owner:branch`` or ``refs/heads/branch``."""
    if ref is None:
        return None
    return ref.rsplit(":", 1)[-1].removeprefix("refs/heads/")


def _next_cwd(argv: list[str], cwd: str) -> str:
    """The directory later commands run in, after ``argv`` (a ``cd`` moves it)."""
    if argv[0] not in ("cd", "pushd"):
        return cwd
    target = next((arg for arg in argv[1:] if not arg.startswith("-")), "~")
    return os.path.normpath(os.path.join(cwd, os.path.expanduser(target)))


# Commands that run their arguments as another command, with the flags of
# theirs that take a value. ``timeout`` also takes its duration first.
_WRAPPER_VALUE_FLAGS = {
    "command": frozenset(),
    "exec": frozenset({"-a"}),
    "nohup": frozenset(),
    "time": frozenset({"-f", "--format", "-o", "--output"}),
    "timeout": frozenset({"-s", "--signal", "-k", "--kill-after"}),
}
_ENV_VALUE_FLAGS = frozenset({"-u", "--unset", "-C", "--chdir"})
_SHELLS = frozenset({"bash", "sh", "zsh", "dash"})
_SHELL_VALUE_FLAGS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})


def _skip_flags(args: list[str], value_flags: frozenset[str]) -> list[str]:
    """``args`` after a wrapper's own leading flags (and their values)."""
    while args and args[0].startswith("-") and args[0] != "-":
        if args[0] == "--":
            return args[1:]
        args = args[2:] if args[0] in value_flags else args[1:]
    return args


def _after_env(args: list[str], assignments: list[str], cwd: str) -> tuple[list[str], list[str], str]:
    """(argv, assignments, cwd) of the command ``env args`` runs."""
    assignments = list(assignments)
    while args:
        word = args[0]
        name, _, value = word.partition("=")
        if word in ("-C", "--chdir") and len(args) > 1:
            cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(args[1])))
        elif name == "--chdir":
            cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(value)))
        elif _ASSIGNMENT.match(word):
            assignments.append(word)
        elif not word.startswith("-"):
            break
        args = args[2:] if word in _ENV_VALUE_FLAGS else args[1:]
    return args, assignments, cwd


def _unwrap(argv: list[str], assignments: list[str], cwd: str) -> tuple[list[str], list[str], str]:
    """(argv, assignments, cwd) of the command ``argv`` finally runs, wrappers removed."""
    while argv:
        name = os.path.basename(argv[0])
        if name == "env":
            argv, assignments, cwd = _after_env(argv[1:], assignments, cwd)
        elif name in _WRAPPER_VALUE_FLAGS:
            argv = _skip_flags(argv[1:], _WRAPPER_VALUE_FLAGS[name])
            if name == "timeout":
                argv = argv[1:]
        else:
            break
    return argv, assignments, cwd


def _shell_script(argv: list[str]) -> str | None:
    """The script a ``bash -c '<script>'`` (or ``-lc``, ``sh``, …) runs, or None.

    As in bash, ``-c`` makes the first non-option argument the script, so
    options (and a ``--``) may sit between ``-c`` and the script.
    """
    if os.path.basename(argv[0]) not in _SHELLS:
        return None
    args, reads_script = argv[1:], False
    while args and args[0].startswith(("-", "+")) and args[0] not in ("-", "+"):
        flag, args = args[0], args[1:]
        if flag.startswith("-") and not flag.startswith("--") and "c" in flag[1:]:
            reads_script = True
        if flag in _SHELL_VALUE_FLAGS:
            args = args[1:]
    return args[0] if reads_script and args else None


def _is_promote(base: str | None, head: str | None) -> bool:
    """True for base main and head staging. None — could not read — counts as either."""
    return _branch(base) in (TRUNK, None) and _branch(head) in (SOURCE, None)


@dataclass
class _Context:
    """One invocation's surroundings: its env prefix, directory and the seams."""

    assignments: list[str]
    cwd: str
    environ: Mapping[str, str]
    read_checkout: ReadCheckout

    def gh_repo(self) -> str | None:
        return _assigned(self.assignments, GH_REPO_VAR) or self.environ.get(GH_REPO_VAR)

    def checkout(self) -> Checkout:
        return self.read_checkout(self.cwd)


def _pr_create_is_promote(args: list[str], ctx: _Context) -> bool:
    pairs, _ = _options(args, _PR_CREATE_VALUE_FLAGS)
    base = _last(pairs, "-B", "--base")
    if _branch(base) != TRUNK:
        return False  # omitted: gh uses the default branch, staging for grantspider
    repo = _last(pairs, "-R", "--repo") or ctx.gh_repo()
    checkout = None
    if repo is None:
        checkout = ctx.checkout()
        repo = checkout.origin
    if _slug(repo) not in (GS_REPO, None):
        return False  # None — could not read the repo — fails closed
    head = _last(pairs, "-H", "--head")
    if head is None:
        head = (checkout or ctx.checkout()).branch
    return _is_promote(base, head)


def _api_repo(owner: str, name: str, ctx: _Context) -> str | None:
    """``owner/repo`` of a REST path, resolving gh's ``{owner}/{repo}`` placeholders."""
    if "{" not in owner + name:
        return _slug(f"{owner}/{name}")
    return _slug(ctx.gh_repo() or ctx.checkout().origin)


def _api_is_promote(args: list[str], ctx: _Context) -> bool:
    pairs, positionals = _options(args, _API_VALUE_FLAGS)
    match = _PULLS_ENDPOINT.match(positionals[0].split("?")[0]) if positionals else None
    if match is None or _api_repo(*match.groups(), ctx) not in (GS_REPO, None):
        return False  # None — could not resolve {owner}/{repo} — fails closed
    fields = dict(value.partition("=")[::2] for name, value in pairs if name in _API_FIELD_FLAGS)
    has_body = bool(fields) or _last(pairs, "--input") is not None
    method = _last(pairs, "-X", "--method") or ("POST" if has_body else "GET")
    if method.upper() != "POST":
        return False
    if _last(pairs, "--input") is not None:
        return True  # the body is in a file this guard does not read
    return _is_promote(fields.get("base"), fields.get("head"))


def _gh_promote(argv: list[str], ctx: _Context) -> bool:
    """True when ``argv`` opens a staging→main pull request on grantspider."""
    if os.path.basename(argv[0]) != "gh":
        return False
    if argv[1:3] in (["pr", "create"], ["pr", "new"]):
        return _pr_create_is_promote(argv[3:], ctx)
    if argv[1:2] == ["api"]:
        return _api_is_promote(argv[2:], ctx)
    return False


@dataclass(frozen=True)
class Promote:
    """A promote found in a command, with its own ``GS_PROMOTE_HOTFIX`` (None if absent)."""

    override: str | None


def _promote_in(argv: list[str], ctx: _Context) -> Promote | None:
    """The promote one unwrapped invocation runs, looking inside ``sh -c`` scripts."""
    script = _shell_script(argv)
    if script is not None:
        return find_promote(
            script,
            ctx.cwd,
            environ=ctx.environ,
            read_checkout=ctx.read_checkout,
            inherited=ctx.assignments,
        )
    if _gh_promote(argv, ctx):
        return Promote(override=_assigned(ctx.assignments, OVERRIDE_VAR))
    return None


def find_promote(
    command: str,
    cwd: str,
    *,
    environ: Mapping[str, str],
    read_checkout: ReadCheckout,
    inherited: list[str] | None = None,
) -> Promote | None:
    """The first grantspider staging→main promote ``command`` would run, or None.

    ``inherited`` is the environment prefix of the shell running ``command``,
    which every command inside it receives.
    """
    for assignments, argv in _invocations(command) or []:
        argv, run_assignments, run_cwd = _unwrap(argv, [*(inherited or []), *assignments], cwd)
        if not argv:
            continue
        found = _promote_in(argv, _Context(run_assignments, run_cwd, environ, read_checkout))
        if found is not None:
            return found
        cwd = _next_cwd(argv, cwd)
    return None


# ---------------------------------------------------------------------------
# The decision.
# ---------------------------------------------------------------------------

_HOW_TO_OVERRIDE = (
    "If this is a hotfix that cannot wait, re-run the promote with a reason:\n"
    "    GS_PROMOTE_HOTFIX='<why this cannot wait>' gh pr create ...\n"
)

_TOO_SOON = (
    "BLOCKED — GrantSpider was promoted to main {last}, {age} ago.\n\n"
    "GrantSpider promotes weekly. Every push to grantspider `main` runs\n"
    "neon-integration (~103 Actions minutes); promoting per fix cost ~$33 of\n"
    "Actions minutes in October 2026 (OS#634). Let this ride staging: the\n"
    "next promote is allowed from {next}.\n\n" + _HOW_TO_OVERRIDE
)

_COULD_NOT_LOOK = (
    "BLOCKED — could not check when GrantSpider was last promoted, so this\n"
    "staging→main promote is refused rather than allowed blind. This is not a\n"
    "too-soon verdict: the cadence was never measured.\n\n"
    "The lookup failed: {reason}\n\n"
    "Retry once `gh api` works. " + _HOW_TO_OVERRIDE
)

_EMPTY_OVERRIDE = (
    "\nNote: an empty GS_PROMOTE_HOTFIX does not count — it must carry the reason.\n"
)

_OVERRIDDEN = (
    "guard_promote_cadence: staging→main promote allowed by GS_PROMOTE_HOTFIX — reason: {reason}\n"
)


def _when(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _age(elapsed: timedelta) -> str:
    return f"{elapsed.days}d {elapsed.seconds // 3600}h"


def evaluate(
    command: str,
    cwd: str,
    *,
    environ: Mapping[str, str],
    read_checkout: ReadCheckout,
    last_promote: ReadLastPromote,
    now: datetime,
) -> tuple[int, str]:
    """(exit code, stderr text) for ``command`` run from ``cwd``. 2 refuses, 0 allows."""
    promote = find_promote(command, cwd, environ=environ, read_checkout=read_checkout)
    if promote is None:
        return 0, ""
    reason = (promote.override or "").strip()
    if reason:
        return 0, _OVERRIDDEN.format(reason=reason)
    note = _EMPTY_OVERRIDE if promote.override is not None else ""
    try:
        last = last_promote()
    except LookupFailed as exc:
        return 2, _COULD_NOT_LOOK.format(reason=exc) + note
    if last is None:
        return 0, ""
    elapsed = now - last.merged_at
    if elapsed >= CADENCE:
        return 0, ""
    last_text = f"{_when(last.merged_at)} (PR #{last.number})"
    message = _TOO_SOON.format(
        last=last_text, age=_age(elapsed), next=_when(last.merged_at + CADENCE)
    )
    return 2, message + note


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:  # unparseable input → don't block
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = (event.get("tool_input") or {}).get("command", "") or ""
    code, message = evaluate(
        command,
        event.get("cwd") or os.getcwd(),
        environ=os.environ,
        read_checkout=read_git_checkout,
        last_promote=read_github_last_promote,
        now=datetime.now(UTC),
    )
    sys.stderr.write(message)
    return code


if __name__ == "__main__":
    sys.exit(main())

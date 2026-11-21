#!/usr/bin/env python3
# ABOUTME: PreToolUse(Bash) guard — refuse a GrantSpider or AI Grant Helper staging->main promote while ci-red is open.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/.claude/hooks/.
"""Red code never reaches production.

When the watchdog ``ci`` job goes red on a pull request into ``staging``,
``scripts/ci/ci_red_alert.py`` opens an issue labelled ``ci-red`` on that
repo. While any such issue is open, staging carries code CI called red, and
promoting it to ``main`` ships that code to production. This refuses the
promote instead (OS#657, OS#660).

**Trigger.** The same promote :mod:`guard_promote_cadence` reads — ``gh pr
create``/``gh pr new`` or a ``gh api`` POST to ``repos/<owner>/<repo>/pulls``
opening a pull request with base ``main`` and a head carrying staging:
``staging`` itself or a promote branch such as ``chore/promote-staging-<date>``,
the shape both repos' ``STAGING_WORKFLOW.md`` prescribe — on any repo in
:data:`PROMOTE_REPOS`, with the same wrappers, the same ``cd`` and
``GH_REPO`` resolution, and the same fail-closed reading: a repo, base or head
this guard could not read counts as a promote. The parser is a byte-identical
copy of the cadence guard's; ``tests/dev/test_hook_lexer_drift.py`` pins it.

An omitted ``--base`` is the repo's default branch. For aigranthelper that is
``main``, so ``gh pr create --head staging`` there is a promote; for
grantspider it is ``staging``, so it is not.

**Rule.** Ask GitHub for the promote's repo's open issues labelled ``ci-red``
(both repos when the repo could not be read). Any open one refuses, naming
each. If GitHub cannot be asked, refuse with a different message: "could not
look" never reads as "red", and never as an allow.

**Override.** A promote that must go anyway carries a reason in its own
environment prefix:

    PROMOTE_OVER_CI_RED='<why production needs this now>' gh pr create ...

The guard then comments ``PROMOTE OVERRIDE: staging→main — <reason>`` on every
open ci-red issue, and allows the promote only if every comment landed. The
override is recorded where the red is tracked, not only on the hook's stderr;
an override that could not be recorded is refused. An empty or blank reason
does not count, and neither does the variable in the session environment or on
another command. With no open ci-red issue the override records nothing and
the promote is simply allowed.

**Not covered.** Merging is not checked, only opening: ``gh pr merge`` on a
promote opened while nothing was red passes, though a ci-red issue may have
opened since. And aigranthelper has no ``ci_red_alert.py`` and no ``ci-red``
label until OS#657 PR E lands, so until then its lookup is always empty and
every AG promote is allowed: "nothing is red" there means "nothing can be".

**Text the lexer rejects** (a quote it cannot close, a trailing backslash)
is read with the lexer's own rules before deciding: everything up to where
the lexer lost the thread, and each line it held to begin inside a quote,
read again from that line's start. No quote character is removed to find a
call or to read its own flags. For a call found that way, anything written
anywhere in the text that would make it a promote does — a base naming
``main``, a head carrying staging, a watched repo, an API base field naming
``main``, an API input flag or POST method, a pulls endpoint; otherwise the
rules above apply to what was read on the call's own command. Text in which no call is found is not a promote.
A pull request whose text spells out a promote, in prose or a comment, can
be refused.

This is defence in depth, not the control. Hooks see only Claude Code's Bash
tool — a terminal, the GitHub web UI or a script all bypass it.

GitHub and git are parameters of :func:`evaluate`, so the decision is
unit-tested without network or repositories.
"""

import json
import os
import re
import shlex
import subprocess  # list-form argv, no shell
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass

# The repos this guard watches, each with its default branch — the base an
# omitted ``--base`` resolves to. Lower-case, as ``_slug`` returns them.
PROMOTE_REPOS = {
    "nathankrupa/aigranthelper": "main",
    "nathankrupa/grantspider": "staging",
}
TRUNK = "main"
SOURCE = "staging"
OVERRIDE_VAR = "PROMOTE_OVER_CI_RED"
GH_REPO_VAR = "GH_REPO"
# Mirrors ``oversteward.intake.labels.CI_RED``; this hook is stdlib-only and
# deploys into repos where that package does not exist.
CI_RED = "ci-red"
OVERRIDE_COMMENT = "PROMOTE OVERRIDE: staging→main — {reason}"
# The override comments on every issue listed, so a listing cut short would
# leave issues unrecorded: a listing that fills the limit is a failed lookup.
ISSUE_LIMIT = 100

# ---------------------------------------------------------------------------
# Shell lexing — a gh invocation counts only where the shell would run it.
#
# DUPLICATE — every guard in ``tests/dev/test_hook_lexer_drift.py``'s
# ``_HOOKS``, this one among them, carries a byte-identical copy of this lexer
# (``_SEPARATORS``, ``_BACKTICK``, ``_ASSIGNMENT``, ``_ShellLexer`` and every
# member below, through ``_invocations``); ``guard_gate_pipe.py`` and ``guard_endless_substitution.py``
# carry ``_ShellLexer`` too. It is NOT shared: each hook is a standalone
# byte-copy deployed into other repos' ``.claude/hooks/``, where a sibling
# import would not resolve. A change here must be made in every copy —
# ``tests/dev/test_hook_lexer_drift.py`` notices when one drifts.
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


# The shell's comment rule. A hash starts a comment only where a word could
# start: between tokens, outside quotes. Inside a word (``a#b``, ``$#``, a URL
# fragment) it is part of that word, and the shell runs the rest of the line.
# ``shlex`` consults ``commenters`` both between tokens and inside a word, never
# inside quotes, so the hash is offered only in its between-tokens state.
# ``shlex.__init__`` assigns ``commenters``; the setter discards that value.
# Identical in every Bash guard that lexes with ``shlex``:
# ``tests/dev/test_hook_lexer_drift.py`` compares the copies.
class _ShellLexer(shlex.shlex):
    @property
    def commenters(self) -> str:
        return "#" if self.state == " " else ""

    @commenters.setter
    def commenters(self, value: str) -> None:
        pass


def _lex(text: str) -> list[str] | None:
    """``text`` as shell tokens, or None if a quote is left open."""
    lexer = _ShellLexer(text, posix=True, punctuation_chars=True)
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


# The line-true reading. Once a line leaves a quote open, ``_token_runs`` lexes
# the whole text as one unit, in which a newline outside quotes is whitespace.
# This reading lexes the whole text once through a stream that decides each
# newline from the lexer's own state. A guard that decides under both readings
# decides under each on its own and holds if either holds. Two marker
# characters stand in for newlines, taken from candidates the text does not
# hold; with fewer than two free, lines are joined until they lex.
_LINE_MARKER_CANDIDATES = "\x1c\x1d\x1e\x1f"
_DEFAULT_PUNCTUATION = shlex.shlex("", punctuation_chars=True).punctuation_chars


class _LineStream:
    """Each newline as the lexer's state reads it: escaped, the continuation
    marker; quoted, a newline; else the line-end marker. ``readline`` (shlex's
    comment skip) leaves the newline unread, so a comment ends at its line."""

    def __init__(self, text: str, line_end: str, continuation: str) -> None:
        self._text, self._position = text, 0
        self._line_end, self._continuation = line_end, continuation
        self.lexer: shlex.shlex | None = None

    def read(self, size: int = 1) -> str:
        char = self._text[self._position : self._position + 1]
        self._position += len(char)
        if char != "\n" or self.lexer is None:
            return char
        if self.lexer.state in self.lexer.escape:
            return self._continuation
        return char if self.lexer.state in self.lexer.quotes else self._line_end

    def readline(self, size: int = -1) -> str:
        end = self._text.find("\n", self._position)
        end = len(self._text) if end < 0 else end
        rest, self._position = self._text[self._position : end], end
        return rest


def _joined_line_runs(command: str) -> list[list[str]] | None:
    """Runs for text holding the marker characters: lines joined until they lex."""
    runs: list[list[str]] = []
    pending: list[str] = []
    for line in command.split("\n"):
        pending.append(line)
        tokens = _lex("\n".join(pending))
        if tokens is not None:
            runs.append(tokens)
            pending = []
    return None if pending else [run for run in runs if run]


def _line_runs(command: str) -> list[list[str]] | None:
    """Tokens of ``command``, one run per line end the shell acts on.

    Quoted text spanning lines stays one token, as in :func:`_token_runs`. None
    when the whole text does not lex. Empty runs are dropped.
    """
    markers = [char for char in _LINE_MARKER_CANDIDATES if char not in command]
    if len(markers) < 2:
        return _joined_line_runs(command)
    line_end, continuation = markers[:2]
    stream = _LineStream(command, line_end, continuation)
    lexer = _ShellLexer(stream, posix=True, punctuation_chars=_DEFAULT_PUNCTUATION + line_end)
    lexer.whitespace_split = True
    stream.lexer = lexer
    try:
        raw = list(lexer)
    except ValueError:
        return None
    runs: list[list[str]] = [[]]
    for token in raw:
        if continuation in token:
            token = token.replace(continuation, "")
            if not token:
                continue
        if line_end not in token:
            runs[-1].append(token)
            continue
        # A line end fused onto punctuation (``;``, ``&&``, ``|``) is split off it.
        for part in re.split(f"({re.escape(line_end)})", token):
            if part == line_end:
                runs.append([])
            elif part:
                runs[-1].append(part)
    return [run for run in runs if run]


def _readings(command: str) -> tuple[bool, ...]:
    """The readings a guard decides under: today's, then the line-true one if lines exist."""
    return (False, True) if "\n" in command else (False,)


def _invocations(
    command: str, line_true: bool = False
) -> list[tuple[list[str], list[str]]] | None:
    """Every simple command in ``command`` as (env assignments, argv).

    ``line_true`` selects the line-true reading, :func:`_line_runs`;
    today's reading, :func:`_token_runs`, is the default.

    None means the text could not be lexed.
    """
    runs = _line_runs(command) if line_true else _token_runs(command)
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
class RedIssue:
    """One open ``ci-red`` issue on a repo."""

    repo: str
    number: int
    title: str


class LookupFailed(Exception):
    """GitHub could not be asked, or its answer could not be read."""


class CommentFailed(Exception):
    """An override comment did not land on its issue."""


ReadCheckout = Callable[[str], Checkout]
ListRedIssues = Callable[[str], "list[RedIssue]"]
PostComment = Callable[[RedIssue, str], None]


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


def _gh(*args: str) -> subprocess.CompletedProcess[str]:
    """``gh args``, or raise OSError/SubprocessError when it did not run."""
    return subprocess.run(  # list-form argv, no shell
        ["gh", *args], capture_output=True, text=True, timeout=30, check=False
    )


def _last_line(stderr: str) -> str:
    return (stderr.strip().splitlines() or ["no output"])[-1]


def red_issues_endpoint(repo: str) -> str:
    """The REST listing of ``repo``'s open ci-red issues.

    REST rather than ``gh issue list --label``, which goes through GitHub's
    search API and its separate rate limit. Neither is read-your-writes: on
    2026-11-05 both listings trailed an issue opened, reopened or closed by
    roughly 2 to 8 seconds, so an issue opened that close to a promote is not
    seen. That window is unguarded.
    """
    return f"repos/{repo}/issues?labels={CI_RED}&state=open&per_page={ISSUE_LIMIT}"


def parse_red_issues(repo: str, payload: str) -> list[RedIssue]:
    """The issues in a REST issues listing; pull requests in it are skipped.

    A listing that fills :data:`ISSUE_LIMIT` may have been cut short, and the
    override must comment on every open issue, so it is a failed lookup.
    """
    try:
        entries = json.loads(payload)
        if not isinstance(entries, list):
            raise TypeError(f"expected a list of issues, got {type(entries).__name__}")
        found = [
            RedIssue(repo, int(entry["number"]), str(entry["title"]))
            for entry in entries
            if "pull_request" not in entry
        ]
    except (ValueError, TypeError, KeyError) as exc:
        raise LookupFailed(f"unreadable gh api answer for {repo}: {exc!r}") from exc
    if len(entries) >= ISSUE_LIMIT:
        raise LookupFailed(f"{repo} listed {len(entries)} ci-red entries, the limit; more may exist")
    return found


def list_github_red_issues(repo: str) -> list[RedIssue]:
    """The real :data:`ListRedIssues`: ``gh api`` for ``repo``'s open ci-red issues."""
    try:
        result = _gh("api", red_issues_endpoint(repo))
    except (OSError, subprocess.SubprocessError) as exc:
        raise LookupFailed(f"gh api did not run: {exc!r}") from exc
    if result.returncode != 0:
        raise LookupFailed(f"gh api exited {result.returncode}: {_last_line(result.stderr)}")
    return parse_red_issues(repo, result.stdout)


def post_github_comment(issue: RedIssue, body: str) -> None:
    """The real :data:`PostComment`: ``gh issue comment`` on ``issue``."""
    try:
        result = _gh("issue", "comment", str(issue.number), "--repo", issue.repo, "--body", body)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CommentFailed(f"gh issue comment did not run: {exc!r}") from exc
    if result.returncode != 0:
        raise CommentFailed(f"gh issue comment exited {result.returncode}: {_last_line(result.stderr)}")


# ---------------------------------------------------------------------------
# Reading a gh command line.
#
# DUPLICATE — ``guard_promote_cadence.py`` and ``guard_promote_ci_red.py``
# carry byte-identical copies of this parser, from ``_PR_CREATE_VALUE_FLAGS``
# to ``find_promote``. What differs lies outside it: each guard's own
# ``PROMOTE_REPOS`` (repo slug -> its default branch) and ``OVERRIDE_VAR``.
# Not shared, for the lexer's reason; ``tests/dev/test_hook_lexer_drift.py``
# notices when one copy drifts.
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


# A branch cut from staging to carry a promote, as both repos' STAGING_WORKFLOW.md
# prescribe: ``chore/promote-staging-<date>``. Its head is not ``staging``, but
# what it carries into main is.
_PROMOTE_BRANCH = re.compile(r"(?:^|/)promote-staging(?:[-/]|$)")


def _carries_staging(head: str | None) -> bool:
    """True for head ``staging`` or a promote branch. None — could not read — counts."""
    branch = _branch(head)
    return branch is None or branch == SOURCE or _PROMOTE_BRANCH.search(branch) is not None


def _is_promote(base: str | None, head: str | None) -> bool:
    """True for base main and a head carrying staging. None — could not read — counts as either."""
    return _branch(base) in (TRUNK, None) and _carries_staging(head)


def _defaults_to_trunk(slug: str | None) -> bool:
    """True when an omitted ``--base`` means main, the repo's default branch.

    An unread repo (None) could be any repo in ``PROMOTE_REPOS``, so it counts
    as defaulting to main when any of them does.
    """
    defaults = [PROMOTE_REPOS[slug]] if slug is not None else list(PROMOTE_REPOS.values())
    return TRUNK in defaults


@dataclass(frozen=True)
class Promote:
    """A promote found in a command: its repo (None if unread) and its own override."""

    repo: str | None
    override: str | None


@dataclass(frozen=True)
class _Wide:
    """What the wide reading found written anywhere in text the lexer rejects.

    Each field can only make a found call a promote, never clear one; the empty
    record, which text that parses gets, changes nothing.
    """

    base_main: bool = False
    head_staging: bool = False
    repos: frozenset[str] = frozenset()
    api_base_main: bool = False
    api_head_staging: bool = False
    api_input: bool = False
    api_post: bool = False
    api_endpoints: frozenset[tuple[str, str]] = frozenset()

    def __or__(self, other: "_Wide") -> "_Wide":
        return _Wide(*(a | b for a, b in zip(vars(self).values(), vars(other).values())))


_NOTHING_WIDE = _Wide()


@dataclass
class _Context:
    """One invocation's surroundings: its env prefix, directory and the seams."""

    assignments: list[str]
    cwd: str
    environ: Mapping[str, str]
    read_checkout: ReadCheckout
    line_true: bool = False
    wide: _Wide = _NOTHING_WIDE

    def gh_repo(self) -> str | None:
        return _assigned(self.assignments, GH_REPO_VAR) or self.environ.get(GH_REPO_VAR)

    def checkout(self) -> Checkout:
        return self.read_checkout(self.cwd)

    def promote(self, repo: str | None) -> Promote:
        """A promote on ``repo``, carrying this invocation's own ``OVERRIDE_VAR``."""
        return Promote(repo=repo, override=_assigned(self.assignments, OVERRIDE_VAR))


def _pr_create_promote(args: list[str], ctx: _Context) -> Promote | None:
    pairs, _ = _options(args, _PR_CREATE_VALUE_FLAGS)
    wide = ctx.wide
    base = TRUNK if wide.base_main else _last(pairs, "-B", "--base")
    if base is not None and _branch(base) != TRUNK:
        return None
    repo = _last(pairs, "-R", "--repo") or ctx.gh_repo()
    checkout = None
    if repo is None:
        checkout = ctx.checkout()
        repo = checkout.origin
    slug = _slug(repo)
    if wide.repos and wide.repos != {slug}:
        slug = None  # a repo written elsewhere may be the one gh uses: it could be any
    if slug is not None and slug not in PROMOTE_REPOS:
        return None  # None — could not read the repo — fails closed
    if base is None and not _defaults_to_trunk(slug):
        return None  # omitted: gh uses the repo's default branch, which is not main
    head = SOURCE if wide.head_staging else _last(pairs, "-H", "--head")
    if head is None:
        head = (checkout or ctx.checkout()).branch
    if not _carries_staging(head):
        return None
    return ctx.promote(slug)


def _api_repo(owner: str, name: str, ctx: _Context) -> str | None:
    """``owner/repo`` of a REST path, resolving gh's ``{owner}/{repo}`` placeholders."""
    if "{" not in owner + name:
        return _slug(f"{owner}/{name}")
    return _slug(ctx.gh_repo() or ctx.checkout().origin)


def _api_promote(args: list[str], ctx: _Context) -> Promote | None:
    pairs, positionals = _options(args, _API_VALUE_FLAGS)
    wide = ctx.wide
    match = _PULLS_ENDPOINT.match(positionals[0].split("?")[0]) if positionals else None
    # Any pulls endpoint W found written may be the one gh uses.
    endpoints = sorted({*([match.groups()] if match else []), *wide.api_endpoints})
    if not endpoints:
        return None
    slugs = {_api_repo(owner, name, ctx) for owner, name in endpoints}
    slug = slugs.pop() if len(slugs) == 1 else None
    if slug is not None and slug not in PROMOTE_REPOS:
        return None  # None — could not resolve {owner}/{repo} — fails closed
    fields = dict(value.partition("=")[::2] for name, value in pairs if name in _API_FIELD_FLAGS)
    has_input = _last(pairs, "--input") is not None or wide.api_input
    has_body = bool(fields) or has_input or wide.api_base_main or wide.api_head_staging
    method = _last(pairs, "-X", "--method") or ("POST" if has_body else "GET")
    if method.upper() != "POST" and not wide.api_post:
        return None
    if has_input:
        return ctx.promote(slug)  # the body is in a file this guard does not read
    base = TRUNK if wide.api_base_main else fields.get("base")
    head = SOURCE if wide.api_head_staging else fields.get("head")
    return ctx.promote(slug) if _is_promote(base, head) else None


def _gh_promote(argv: list[str], ctx: _Context) -> Promote | None:
    """The staging→main pull request ``argv`` opens on a ``PROMOTE_REPOS`` repo, or None."""
    if os.path.basename(argv[0]) != "gh":
        return None
    if argv[1:3] in (["pr", "create"], ["pr", "new"]):
        return _pr_create_promote(argv[3:], ctx)
    if argv[1:2] == ["api"]:
        return _api_promote(argv[2:], ctx)
    return None


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
            line_true=ctx.line_true,
            wide=ctx.wide,
        )
    return _gh_promote(argv, ctx)


def _search(
    invocations: list[tuple[list[str], list[str]]], cwd: str, template: _Context, visited: list[str]
) -> Promote | None:
    """The first promote among ``invocations``, run in order from ``cwd``.

    ``template`` carries the seams, the reading and W; its ``assignments`` are
    the inherited prefix. Each directory a ``cd`` reaches joins ``visited``.
    """
    for assignments, argv in invocations:
        argv, run_assignments, run_cwd = _unwrap(argv, [*template.assignments, *assignments], cwd)
        if not argv:
            continue
        seams = (template.environ, template.read_checkout, template.line_true, template.wide)
        found = _promote_in(argv, _Context(run_assignments, run_cwd, *seams))
        if found is not None:
            return found
        cwd = _next_cwd(argv, cwd)
        if cwd not in visited:
            visited.append(cwd)
    return None


# Text the lexer rejects is read by the lexer's own rules, through a stream that
# takes each line end from the lexer's state, keeping every token produced
# before the error. F1 reads the whole text; F2 reads again each line the lexer
# began inside a quote; W, the wide reading, only collects values.
class _RecordingLineStream(_LineStream):
    """The lexer block's :class:`_LineStream`, also recording each line begun inside quotes.

    The block's stream keeps no record, since text that parses needs none; F2
    reads each recorded line again. An offset is that line's first character.
    """

    def __init__(self, text: str, line_end: str, continuation: str) -> None:
        super().__init__(text, line_end, continuation)
        self.quoted_line_starts: list[int] = []
        self._state_before = " "

    def read(self, size: int = 1) -> str:
        assert self.lexer is not None
        before, self._state_before = self._state_before, self.lexer.state
        char = super().read(size)
        # A quoted newline arrives as itself; an escaped one whose backslash was
        # read inside quotes arrives as the continuation marker.
        if char == "\n" or (char == self._continuation and before in self.lexer.quotes):
            self.quoted_line_starts.append(self._position)
        return char


class _UncommentedLexer(_ShellLexer):
    """``_ShellLexer`` with no comment rule, for W: nothing written is skipped."""

    @property
    def commenters(self) -> str:
        return ""

    @commenters.setter
    def commenters(self, value: str) -> None:
        pass


def _lexer_over(source, lexer_class: type[shlex.shlex], punctuation: str | bool) -> shlex.shlex:
    lexer = lexer_class(source, posix=True, punctuation_chars=punctuation)
    lexer.whitespace_split = True
    if isinstance(source, _RecordingLineStream):
        source.lexer = lexer
    return lexer


def _tokens_until_error(lexer: shlex.shlex):
    """Every token the lexer completed before its error, where it lost the thread."""
    try:
        yield from lexer
    except ValueError:
        return


def _read_rejected(text: str, lexer_class: type[shlex.shlex]) -> tuple[list[str], list[list[str]]]:
    """(F1's tokens, F2's token runs) for ``text``, each line end a ``;``.

    F1 is the whole text as far as the lexer got. F2 is each line the lexer
    began inside a quote, read afresh from its start to the line end that fresh
    reading finds. With fewer than two marker characters free, F1 reads each
    physical line alone and F2 is empty.
    """
    markers = [char for char in _LINE_MARKER_CANDIDATES if char not in text]
    if len(markers) < 2:
        lexers = [_lexer_over(line, lexer_class, True) for line in text.split("\n")]
        return [t for lexer in lexers for t in [*_tokens_until_error(lexer), ";"]], []
    line_end, continuation = markers[:2]

    def read(start: int) -> tuple[list[str], list[int]]:
        """Tokens from ``start``: to the end of the text, or for a line start to its line end."""
        stream = _RecordingLineStream(text[start:], line_end, continuation)
        lexer = _lexer_over(stream, lexer_class, _DEFAULT_PUNCTUATION + line_end)
        found: list[str] = []
        for token in _tokens_until_error(lexer):
            if continuation in token:
                token = token.replace(continuation, "")
                if not token:
                    continue
            split = [part for part in re.split(f"({re.escape(line_end)})", token) if part]
            for part in split if line_end in token else [token]:
                if part == line_end and start:
                    return found, []
                found.append(";" if part == line_end else part)
        return found, stream.quoted_line_starts

    first, starts = read(0)
    return first, [read(start)[0] for start in starts]


def _flag_values(tokens: list[str], *names: str) -> list[str]:
    """Every value written after one of ``names``, separate or attached, wherever it stands."""
    values: list[str] = []
    for index, token in enumerate(tokens):
        for name in names:
            if token == name:
                values.extend(tokens[index + 1 : index + 2])
            elif name.startswith("--") and token.startswith(name + "="):
                values.append(token[len(name) + 1 :])
            elif not name.startswith("--") and token.startswith(name) and len(token) > 2:
                values.append(token[2:].removeprefix("="))
    return values


def _wide_reading(command: str) -> _Wide:
    """W: ``command`` with every quote character deleted, read with no comment rule.

    With no quotes and no comments it skips nothing written, but for a word cut
    by a backslash ending the text (or, with too few marker characters free, a
    line). It has no command boundaries, so it only ever adds: base, head and
    repo values written as flags, API base and head fields, whether an API
    input flag or a POST method occurs, and every pulls endpoint written.
    """
    tokens, _ = _read_rejected(command.replace("'", "").replace('"', ""), _UncommentedLexer)
    fields = [
        value.partition("=")[::2]
        for value in _flag_values(tokens, "-f", "--raw-field", "-F", "--field")
    ]
    return _Wide(
        base_main=any(_branch(value) == TRUNK for value in _flag_values(tokens, "-B", "--base")),
        head_staging=any(_carries_staging(value) for value in _flag_values(tokens, "-H", "--head")),
        repos=frozenset(
            slug
            for slug in map(_slug, _flag_values(tokens, "-R", "--repo"))
            if slug in PROMOTE_REPOS
        ),
        api_base_main=any(key == "base" and _branch(value) == TRUNK for key, value in fields),
        api_head_staging=any(key == "head" and _carries_staging(value) for key, value in fields),
        api_input=any(token == "--input" or token.startswith("--input=") for token in tokens),
        api_post=any(value.upper() == "POST" for value in _flag_values(tokens, "-X", "--method")),
        api_endpoints=frozenset(
            match.groups()
            for match in (_PULLS_ENDPOINT.match(token.split("?")[0]) for token in tokens)
            if match
        ),
    )


def _rejected_promote(command: str, template: _Context) -> Promote | None:
    """The first promote in ``command``, text the lexer rejects, read by the lexer's rules.

    Calls are found only by F1 and F2, and no quote character is removed to
    find one or to read its own flags. For a call found, whatever W holds that
    would make it a promote does; otherwise today's rule applies to what F1 or
    F2 read on the call's own command. So ruling ``main`` out rests on W, not on
    a reading that may have lost text. Each run, F1 and every F2 line, is read
    from every directory any run reached, until no new one appears; a script
    inside is read under the line-true reading.
    """
    wide = template.wide | _wide_reading(command)
    template = _Context(
        template.assignments, template.cwd, template.environ, template.read_checkout, True, wide
    )
    first, fresh = _read_rejected(command, _ShellLexer)
    runs = [[_split_assignments(argv) for argv in _simple_commands(t)] for t in [first, *fresh]]
    visited, searched = [template.cwd], set()
    while len(searched) < len(runs) * len(visited):
        for index, invocations in enumerate(runs):
            for start in [cwd for cwd in visited if (index, cwd) not in searched]:
                searched.add((index, start))
                found = _search(invocations, start, template, visited)
                if found is not None:
                    return found
    return None


def find_promote(
    command: str,
    cwd: str,
    *,
    environ: Mapping[str, str],
    read_checkout: ReadCheckout,
    inherited: list[str] | None = None,
    line_true: bool = False,
    wide: _Wide = _NOTHING_WIDE,
) -> Promote | None:
    """The first staging→main promote on a ``PROMOTE_REPOS`` repo ``command`` would run.

    None when it runs none. ``inherited`` is the environment prefix of the
    shell running ``command``, which every command inside it receives.
    ``line_true`` selects the reading, and a nested script is read under it.
    Text the lexer rejects is read by :func:`_rejected_promote`; ``wide`` is
    what W found in a rejected text enclosing this one.
    """
    template = _Context(list(inherited or []), cwd, environ, read_checkout, line_true, wide)
    invocations = _invocations(command, line_true)
    if invocations is None:
        return _rejected_promote(command, template)
    return _search(invocations, cwd, template, [cwd])


def find_promotes(
    command: str, cwd: str, *, environ: Mapping[str, str], read_checkout: ReadCheckout
) -> list[Promote]:
    """The first promote under each reading, today's first, each from ``cwd``; distinct.

    Both readings reject exactly the text ``_lex`` rejects (reasoned from the
    stream's states, measured on recorded commands, pinned by a test), so
    :func:`_rejected_promote` reads such text once, in today's reading's turn.
    """
    found: list[Promote] = []
    for line_true in _readings(command) if _lex(command) is not None else (False,):
        promote = find_promote(
            command, cwd, environ=environ, read_checkout=read_checkout, line_true=line_true
        )
        if promote is not None and promote not in found:
            found.append(promote)
    return found


# ---------------------------------------------------------------------------
# The decision.
# ---------------------------------------------------------------------------

_HOW_TO_OVERRIDE = (
    "If production needs this promote anyway, re-run it with a reason. The\n"
    "reason is commented on every open ci-red issue, and the promote is\n"
    "allowed only once every comment has landed:\n"
    "    PROMOTE_OVER_CI_RED='<why production needs this now>' gh pr create ...\n"
)

_RED = (
    "BLOCKED — staging is red: {count} open ci-red issue(s) on {repos}.\n\n"
    "{issues}\n\n"
    "Red code never reaches production (OS#657). Fix the red on staging and\n"
    "close each issue, then promote.\n\n" + _HOW_TO_OVERRIDE
)

_COULD_NOT_LOOK = (
    "BLOCKED — could not check {repos} for open ci-red issues, so this\n"
    "staging→main promote is refused rather than allowed blind. This is not a\n"
    "red verdict: the ci-red issues were never read.\n\n"
    "The lookup failed: {reason}\n\n"
    "Retry once `gh api` works.\n"
)

_UNRECORDED = (
    "BLOCKED — the PROMOTE_OVER_CI_RED override could not be recorded, so the\n"
    "promote is refused: an override nobody can find on the ci-red issue is not\n"
    "an override.\n\n"
    "Comment failed on {failed}: {reason}\n"
    "Already recorded on: {landed}\n\n"
    "Retry once `gh issue comment` works.\n"
)

_EMPTY_OVERRIDE = (
    "\nNote: an empty PROMOTE_OVER_CI_RED does not count — it must carry the reason.\n"
)

_OVERRIDDEN = (
    "guard_promote_ci_red: staging→main promote allowed over {count} open ci-red issue(s) "
    "by PROMOTE_OVER_CI_RED — recorded on {issues} — reason: {reason}\n"
)


def _ref(issue: RedIssue) -> str:
    return f"{issue.repo}#{issue.number}"


def _listing(issues: list[RedIssue]) -> str:
    return "\n".join(f"  {_ref(issue)}  {issue.title}" for issue in issues)


def _record_override(
    issues: list[RedIssue], reason: str, post_comment: PostComment
) -> tuple[int, str]:
    """Comment the override on each issue; (0, note) if all landed, else (2, refusal)."""
    body = OVERRIDE_COMMENT.format(reason=reason)
    landed: list[str] = []
    for issue in issues:
        try:
            post_comment(issue, body)
        except CommentFailed as exc:
            return 2, _UNRECORDED.format(
                failed=_ref(issue), reason=exc, landed=", ".join(landed) or "none"
            )
        landed.append(_ref(issue))
    return 0, _OVERRIDDEN.format(count=len(issues), issues=", ".join(landed), reason=reason)


def evaluate(
    command: str,
    cwd: str,
    *,
    environ: Mapping[str, str],
    read_checkout: ReadCheckout,
    list_red_issues: ListRedIssues,
    post_comment: PostComment,
) -> tuple[int, str]:
    """(exit code, stderr text) for ``command`` run from ``cwd``. 2 refuses, 0 allows.

    Each reading's first promote is decided on its own, those without a reason
    first: a refusal of any stands, and the first with a reason decides the rest,
    so an override is recorded at most once.
    """
    promotes = find_promotes(command, cwd, environ=environ, read_checkout=read_checkout)
    for promote in sorted(promotes, key=_has_reason):
        code, message = _verdict(
            promote, list_red_issues=list_red_issues, post_comment=post_comment
        )
        if code or _has_reason(promote):
            return code, message
    return 0, ""


def _has_reason(promote: Promote) -> bool:
    return bool((promote.override or "").strip())


def _verdict(
    promote: Promote, *, list_red_issues: ListRedIssues, post_comment: PostComment
) -> tuple[int, str]:
    """(exit code, stderr text) for one promote."""
    repos =[promote.repo] if promote.repo is not None else sorted(PROMOTE_REPOS)
    reason = (promote.override or "").strip()
    note = _EMPTY_OVERRIDE if promote.override is not None and not reason else ""
    try:
        issues = [issue for repo in repos for issue in list_red_issues(repo)]
    except LookupFailed as exc:
        return 2, _COULD_NOT_LOOK.format(repos=" and ".join(repos), reason=exc) + note
    if not issues:
        return 0, ""
    if reason:
        return _record_override(issues, reason, post_comment)
    message = _RED.format(count=len(issues), repos=" and ".join(repos), issues=_listing(issues))
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
        list_red_issues=list_github_red_issues,
        post_comment=post_github_comment,
    )
    sys.stderr.write(message)
    return code


if __name__ == "__main__":
    sys.exit(main())

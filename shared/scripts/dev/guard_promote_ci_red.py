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

**Merging is checked too** (OS#661), because a ci-red issue can open between a
promote's opening and its merge: ``gh pr merge`` (by number, URL, branch, or
the checkout's branch when none is named) and a non-GET ``gh api`` call to
``repos/<owner>/<repo>/pulls/<n>/merge``, on a repo in :data:`PROMOTE_REPOS`.
The command does not say what the pull request merges, so :data:`ReadPull`
asks GitHub for its base and head; a merge whose base is ``main`` and whose
head carries staging is a promote and meets the rule below, and any other
merge — a hotfix into main, a feature into staging — is allowed. A merge whose
repo or pull request cannot be read from the command, or whose pull request
GitHub cannot be asked about, is refused with its own "could not read the
pull request" text. ``gh pr merge --disable-auto`` merges nothing and is
allowed. This parsing sits outside the duplicated parser block below: the
cadence guard reads only openings.

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

**Not covered.** A merge is checked when the command is run, not when it
completes: ``gh pr merge --auto`` checks once, and the merge GitHub performs
later, when the checks pass, is unguarded. A merge through GraphQL
(``gh api graphql`` with ``mergePullRequest``) or the web UI is not seen.

**Unlexable text** (an unbalanced quote) is allowed: no shell would run it
either, and it never reaches ``gh``.

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
# ``_HOOKS``, ``guard_promote_cadence.py`` among them, carries a byte-identical
# copy of this lexer (``_SEPARATORS``, ``_BACKTICK``, ``_ASSIGNMENT`` and the
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
class RedIssue:
    """One open ``ci-red`` issue on a repo."""

    repo: str
    number: int
    title: str


@dataclass(frozen=True)
class Pull:
    """What GitHub says a pull request merges: its base and head branches."""

    base: str
    head: str


class LookupFailed(Exception):
    """GitHub could not be asked, or its answer could not be read."""


class CommentFailed(Exception):
    """An override comment did not land on its issue."""


ReadCheckout = Callable[[str], Checkout]
ListRedIssues = Callable[[str], "list[RedIssue]"]
PostComment = Callable[[RedIssue, str], None]
# (repo, selector) -> the pull request's base and head; raises LookupFailed.
# The selector is what ``gh pr view`` accepts: a number or a branch name.
ReadPull = Callable[[str, str], Pull]


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


def parse_pull(payload: str) -> Pull:
    """The base and head in ``gh pr view --json baseRefName,headRefName`` output."""
    try:
        data = json.loads(payload)
        base, head = data["baseRefName"], data["headRefName"]
    except (ValueError, TypeError, KeyError) as exc:
        raise LookupFailed(f"unreadable gh pr view answer: {exc!r}") from exc
    if not (isinstance(base, str) and base and isinstance(head, str) and head):
        raise LookupFailed(f"gh pr view gave no base or head: {payload.strip()[:200]}")
    return Pull(base=base, head=head)


def read_github_pull(repo: str, selector: str) -> Pull:
    """The real :data:`ReadPull`: ``gh pr view`` for the base and head of ``selector``.

    The selector follows ``--``, so a selector that looks like a flag is read
    as a pull request, never as one of ``gh pr view``'s own options.
    """
    try:
        result = _gh("pr", "view", "--repo", repo, "--json", "baseRefName,headRefName", "--", selector)
    except (OSError, subprocess.SubprocessError) as exc:
        raise LookupFailed(f"gh pr view did not run: {exc!r}") from exc
    if result.returncode != 0:
        raise LookupFailed(f"gh pr view exited {result.returncode}: {_last_line(result.stderr)}")
    return parse_pull(result.stdout)


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

    def promote(self, repo: str | None) -> Promote:
        """A promote on ``repo``, carrying this invocation's own ``OVERRIDE_VAR``."""
        return Promote(repo=repo, override=_assigned(self.assignments, OVERRIDE_VAR))


def _pr_create_promote(args: list[str], ctx: _Context) -> Promote | None:
    pairs, _ = _options(args, _PR_CREATE_VALUE_FLAGS)
    base = _last(pairs, "-B", "--base")
    if base is not None and _branch(base) != TRUNK:
        return None
    repo = _last(pairs, "-R", "--repo") or ctx.gh_repo()
    checkout = None
    if repo is None:
        checkout = ctx.checkout()
        repo = checkout.origin
    slug = _slug(repo)
    if slug is not None and slug not in PROMOTE_REPOS:
        return None  # None — could not read the repo — fails closed
    if base is None and not _defaults_to_trunk(slug):
        return None  # omitted: gh uses the repo's default branch, which is not main
    head = _last(pairs, "-H", "--head")
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
    match = _PULLS_ENDPOINT.match(positionals[0].split("?")[0]) if positionals else None
    if match is None:
        return None
    slug = _api_repo(*match.groups(), ctx)
    if slug is not None and slug not in PROMOTE_REPOS:
        return None  # None — could not resolve {owner}/{repo} — fails closed
    fields = dict(value.partition("=")[::2] for name, value in pairs if name in _API_FIELD_FLAGS)
    has_body = bool(fields) or _last(pairs, "--input") is not None
    method = _last(pairs, "-X", "--method") or ("POST" if has_body else "GET")
    if method.upper() != "POST":
        return None
    if _last(pairs, "--input") is not None:
        return ctx.promote(slug)  # the body is in a file this guard does not read
    return ctx.promote(slug) if _is_promote(fields.get("base"), fields.get("head")) else None


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
        )
    return _gh_promote(argv, ctx)


def find_promote(
    command: str,
    cwd: str,
    *,
    environ: Mapping[str, str],
    read_checkout: ReadCheckout,
    inherited: list[str] | None = None,
) -> Promote | None:
    """The first staging→main promote on a ``PROMOTE_REPOS`` repo ``command`` would run.

    None when it runs none. ``inherited`` is the environment prefix of the
    shell running ``command``, which every command inside it receives.
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
# Reading a merge. This guard's own: the cadence guard reads only openings, so
# none of this sits in the duplicated parser block above, which it reuses.
# ---------------------------------------------------------------------------

# Flags of ``gh pr merge`` that take a value, from ``gh pr merge --help``.
_PR_MERGE_VALUE_FLAGS = frozenset(
    {
        "-A", "--author-email", "-b", "--body", "-F", "--body-file",
        "--match-head-commit", "-R", "--repo", "-t", "--subject",
    }
)
_MERGE_ENDPOINT = re.compile(r"^/?repos/([^/]+)/([^/]+)/pulls/([^/]+)/merge/?$")
_PULL_URL = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)(?:[/?#].*)?$")
# Text the shell would still expand: what reaches gh is not what the guard sees.
_UNEXPANDED = re.compile(r"[$`]")


@dataclass(frozen=True)
class Merge:
    """A merge found in a command, on a watched repo or one that could not be read.

    ``repo`` is None when the command does not say which repo, and
    ``selector`` (a number or branch, as ``gh pr view`` takes it) is None when
    it does not say which pull request: either refuses as "could not read".
    """

    repo: str | None
    selector: str | None
    override: str | None


def _merge_on(slug: str | None, selector: str | None, ctx: _Context) -> Merge | None:
    """The merge of ``selector`` on ``slug``, or None when ``slug`` is not watched."""
    if slug is not None and slug not in PROMOTE_REPOS:
        return None
    if selector is not None and _UNEXPANDED.search(selector):
        selector = None
    return Merge(slug, selector, ctx.promote(slug).override)


def _pr_merge(args: list[str], ctx: _Context) -> Merge | None:
    if "--disable-auto" in args:
        return None  # turns auto-merge off; merges nothing
    pairs, positionals = _options(args, _PR_MERGE_VALUE_FLAGS)
    selector = positionals[0] if positionals else None
    url = _PULL_URL.match(selector) if selector is not None else None
    if url is not None:
        return _merge_on(_slug(f"{url[1]}/{url[2]}"), url[3], ctx)
    repo = _last(pairs, "-R", "--repo") or ctx.gh_repo()
    checkout = None
    if repo is None:
        checkout = ctx.checkout()
        repo = checkout.origin
    slug = _slug(repo)
    if slug is not None and slug not in PROMOTE_REPOS:
        return None
    if selector is None:
        selector = (checkout or ctx.checkout()).branch  # gh merges the branch's own PR
    return _merge_on(slug, selector, ctx)


def _api_merge(args: list[str], ctx: _Context) -> Merge | None:
    pairs, positionals = _options(args, _API_VALUE_FLAGS)
    match = _MERGE_ENDPOINT.match(positionals[0].split("?")[0]) if positionals else None
    if match is None:
        return None
    has_body = any(name in _API_FIELD_FLAGS for name, _ in pairs) or _last(pairs, "--input") is not None
    method = _last(pairs, "-X", "--method") or ("POST" if has_body else "GET")
    if method.upper() == "GET":
        return None  # asks whether the pull request is merged; merges nothing
    number = match[3] if match[3].isdigit() else None
    return _merge_on(_api_repo(match[1], match[2], ctx), number, ctx)


def _merges_in(argv: list[str], ctx: _Context) -> list[Merge]:
    """The merges one unwrapped invocation runs, looking inside ``sh -c`` scripts."""
    script = _shell_script(argv)
    if script is not None:
        return find_merges(
            script,
            ctx.cwd,
            environ=ctx.environ,
            read_checkout=ctx.read_checkout,
            inherited=ctx.assignments,
        )
    if os.path.basename(argv[0]) != "gh":
        return []
    found = None
    if argv[1:3] == ["pr", "merge"]:
        found = _pr_merge(argv[3:], ctx)
    elif argv[1:2] == ["api"]:
        found = _api_merge(argv[2:], ctx)
    return [found] if found is not None else []


def find_merges(
    command: str,
    cwd: str,
    *,
    environ: Mapping[str, str],
    read_checkout: ReadCheckout,
    inherited: list[str] | None = None,
) -> list[Merge]:
    """Every pull-request merge on a ``PROMOTE_REPOS`` repo ``command`` would run.

    Whether each is a promote is GitHub's to say; see :func:`_merge_promote`.
    """
    merges: list[Merge] = []
    for assignments, argv in _invocations(command) or []:
        argv, run_assignments, run_cwd = _unwrap(argv, [*(inherited or []), *assignments], cwd)
        if not argv:
            continue
        merges.extend(_merges_in(argv, _Context(run_assignments, run_cwd, environ, read_checkout)))
        cwd = _next_cwd(argv, cwd)
    return merges


# ---------------------------------------------------------------------------
# The decision.
# ---------------------------------------------------------------------------

_HOW_TO_OVERRIDE = (
    "If production needs this promote anyway, re-run it with a reason. The\n"
    "reason is commented on every open ci-red issue, and the promote is\n"
    "allowed only once every comment has landed:\n"
    "    PROMOTE_OVER_CI_RED='<why production needs this now>' gh pr create ...\n"
    "(or gh pr merge ..., for a promote already open).\n"
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

_PULL_UNREAD = (
    "BLOCKED — could not read pull request {ref}, so this merge is refused\n"
    "rather than allowed blind: without its base and head this guard cannot\n"
    "tell a staging→main promote from any other merge. This is not a red\n"
    "verdict: no ci-red issue was read.\n\n"
    "{reason}\n\n"
    "Name the pull request by number with --repo, and retry once `gh pr view` works.\n"
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


def _merge_promote(merge: Merge, read_pull: ReadPull) -> tuple[Promote | None, str]:
    """(the promote ``merge`` is, or None when it is not one; a refusal, or "").

    A merge is a promote when GitHub says its base is main and its head carries
    staging. A merge it cannot ask about is refused, never allowed.
    """
    ref = f"{merge.repo or '<unread repo>'}#{merge.selector or '<unread pull request>'}"
    if merge.repo is None:
        reason = "The command names no repo this guard could read (--repo, GH_REPO or origin)."
        return None, _PULL_UNREAD.format(ref=ref, reason=reason)
    if merge.selector is None:
        reason = "The command names no pull request this guard could read."
        return None, _PULL_UNREAD.format(ref=ref, reason=reason)
    try:
        pull = read_pull(merge.repo, merge.selector)
    except LookupFailed as exc:
        return None, _PULL_UNREAD.format(ref=ref, reason=f"The lookup failed: {exc}")
    if not _is_promote(pull.base, pull.head):
        return None, ""
    return Promote(repo=merge.repo, override=merge.override), ""


def _check(
    promote: Promote, list_red_issues: ListRedIssues, post_comment: PostComment
) -> tuple[int, str]:
    """(exit code, stderr text) for one promote: refused while its repo is red."""
    repos = [promote.repo] if promote.repo is not None else sorted(PROMOTE_REPOS)
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


def evaluate(
    command: str,
    cwd: str,
    *,
    environ: Mapping[str, str],
    read_checkout: ReadCheckout,
    list_red_issues: ListRedIssues,
    post_comment: PostComment,
    read_pull: ReadPull,
) -> tuple[int, str]:
    """(exit code, stderr text) for ``command`` run from ``cwd``. 2 refuses, 0 allows.

    Every promote the command opens or merges is checked; the first refusal wins.
    """
    opened = find_promote(command, cwd, environ=environ, read_checkout=read_checkout)
    promotes = [opened] if opened is not None else []
    for merge in find_merges(command, cwd, environ=environ, read_checkout=read_checkout):
        promote, refusal = _merge_promote(merge, read_pull)
        if refusal:
            return 2, refusal
        if promote is not None and promote not in promotes:
            promotes.append(promote)
    notes = []
    for promote in promotes:
        code, message = _check(promote, list_red_issues, post_comment)
        if code != 0:
            return code, message
        notes.append(message)
    return 0, "".join(notes)


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
        read_pull=read_github_pull,
    )
    sys.stderr.write(message)
    return code


if __name__ == "__main__":
    sys.exit(main())

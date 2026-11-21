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
# command and starts another exactly as ``;`` does. Unlike the separators
# above it never arrives as a token of its own: it is not shell punctuation to
# the lexer, so ``git pull`` in backticks lexes as ["`git", "pull`"] and the
# split has to be made on the token's own text.
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


# The nest-true text. Inside a double-quoted string the shell opens a fresh
# quoting context in ``$( )``, backticks and ``${ }``, but ``_ShellLexer``
# toggles on every double quote and so closes the outer string at the first
# inner one. ``_nest_true`` gives the text back with each double quote inside
# such a nested region preceded by an odd run of backslashes: the unchanged
# lexer reads that as a literal quote and stays in its double-quote state to
# the real closing quote. It vouches only for text it walked to the end with
# the constructs it models, every context closed, and returns None for the
# rest. Text with no nested quote comes back unchanged. Identical in every
# Bash guard that lexes with ``shlex``: ``tests/dev/test_hook_lexer_drift.py``
# compares the copies.
_NEST_WORD_BREAKS = " \t\n;&|()<>"
_NEST_DELIMITER = re.compile(r"[\w.-]+")
_NEST_MAX_DEPTH = 64


class _Unmodelled(Exception):
    """A construct the nest-true scanner does not model, or a context left open."""


class _NestScanner:
    """One walk over ``text``, building its nest-true form in ``out``.

    ``nested`` is True inside a substitution or expansion that sits in a
    double-quoted string, where every double quote read is escaped. A heredoc
    waits in ``heredocs`` for the line end of the code frame that named it.
    """

    def __init__(self, text: str) -> None:
        self.text, self.i, self.out = text, 0, []
        self.depth = self.frames = self.heredoc_frame = 0
        self.heredocs: list[tuple[str, bool]] = []

    def peek(self, offset: int = 0) -> str:
        return self.text[self.i + offset : self.i + offset + 1]

    def take(self, count: int = 1) -> None:
        self.out.append(self.text[self.i : self.i + count])
        self.i += count

    def data(self, nested: bool) -> None:
        """One character, a double quote escaped when ``nested`` and not already."""
        if nested and self.peek() == '"':
            run = 0
            while self.text[self.i - run - 1 : self.i - run] == "\\":
                run += 1
            if run % 2 == 0:
                self.out.append("\\")
        self.take()

    def quoted(self, nested: bool) -> None:
        """One character inside quotes or an expansion, which must not end there."""
        if not self.peek():
            raise _Unmodelled("unclosed")
        if self.peek() == "\n" and self.heredocs:
            raise _Unmodelled("heredoc-placement")
        self.data(nested)

    def enter(self) -> int:
        self.depth += 1
        self.frames += 1
        if self.depth > _NEST_MAX_DEPTH:
            raise _Unmodelled("depth")
        return self.frames

    def code(self, nested: bool, closing: bool) -> None:
        """Shell code, to the ``)`` closing its ``$(`` or, without ``closing``, to the end."""
        frame = self.enter()
        parens, word_start = 0, True
        while self.peek() and not (closing and self.peek() == ")" and not parens):
            char, start, word_start = self.peek(), word_start, False
            if char == "\\":
                word_start = start if self.peek(1) == "\n" else False
                self.take(2)
            elif char == "'":
                self.single(nested)
            elif char == '"':
                self.double(nested)
            elif char == "`":
                self.backtick(nested)
            elif char == "$":
                self.dollar(nested, False)
            elif self.text.startswith("<<", self.i):
                self.heredoc(nested, frame)
            elif char in "<>" and self.peek(1) == "(":
                raise _Unmodelled("process-substitution")
            elif start and char == "#":
                while self.peek() not in ("", "\n"):
                    self.data(nested)
            elif closing and start and self.text.startswith("case", self.i) and (
                self.peek(4) in _NEST_WORD_BREAKS
            ):
                raise _Unmodelled("case")
            elif char == "\n" and self.heredocs:
                if self.heredoc_frame != frame:
                    raise _Unmodelled("heredoc-placement")
                self.take()
                self.bodies(nested)
                word_start = True
            else:
                if closing and char in "()":
                    parens += 1 if char == "(" else -1
                self.take()
                word_start = char in _NEST_WORD_BREAKS
        if closing:
            if not self.peek():
                raise _Unmodelled("unclosed")
            self.take()
        elif self.heredocs:
            raise _Unmodelled("heredoc-placement")
        self.depth -= 1

    def single(self, nested: bool) -> None:
        self.take()
        while self.peek() != "'":
            self.quoted(nested)
        self.take()

    def double(self, nested: bool) -> None:
        """A double-quoted string; what it holds is nested, its own quotes only if it is."""
        self.enter()
        self.data(nested)
        while self.peek() != '"':
            char = self.peek()
            if char == "\\":
                self.take(2)
            elif char == "`":
                self.backtick(True)
            elif char == "$":
                self.dollar(True, True)
            else:
                self.quoted(nested)
        self.data(nested)
        self.depth -= 1

    def dollar(self, nested: bool, in_double: bool) -> None:
        after = self.peek(1)
        if after == "(" and self.peek(2) != "(":
            self.take(2)
            self.code(nested, True)
        elif after == "{":
            self.take(2)
            self.parameter(nested)
        elif after in ("(", "[") or (not in_double and after in ("'", '"')):
            raise _Unmodelled("arithmetic" if after in ("(", "[") else "ansi-c-or-locale")
        else:
            self.take()

    def parameter(self, nested: bool) -> None:
        self.enter()
        while self.peek() != "}":
            char = self.peek()
            if char in ("'", "{"):
                raise _Unmodelled("parameter")
            if char == "\\":
                self.take(2)
            elif char == '"':
                self.double(nested)
            elif char == "`":
                self.backtick(nested)
            elif char == "$":
                self.dollar(nested, False)
            else:
                self.quoted(nested)
        self.take()
        self.depth -= 1

    def backtick(self, nested: bool) -> None:
        """A backtick substitution holding no substitution, heredoc or open quote."""
        self.enter()
        self.take()
        quote = ""
        while self.peek() != "`" or quote:
            char = self.peek()
            if (
                char == "`"
                or (char == "\\" and nested and self.peek(1) == '"')
                or (char == "$" and self.peek(1) in ("(", "{", "[", "'", '"'))
                or self.text.startswith("<<", self.i)
            ):
                raise _Unmodelled("backtick")
            if char == "\\":
                self.take(2)
                continue
            if char == quote:
                quote = ""
            elif not quote and char in ("'", '"'):
                quote = char
            self.quoted(nested)
        self.take()
        self.depth -= 1

    def heredoc(self, nested: bool, frame: int) -> None:
        """A ``<<`` redirect: only a quoted delimiter, whose body is never expanded."""
        if self.text.startswith("<<<", self.i):
            self.take(3)
            return
        if self.heredocs and self.heredoc_frame != frame:
            raise _Unmodelled("heredoc-placement")
        self.take(2)
        strip = self.peek() == "-"
        if strip:
            self.take()
        while self.peek() in (" ", "\t"):
            self.take()
        word, quote, quoted = [], "", False
        while self.peek() and (quote or self.peek() not in _NEST_WORD_BREAKS):
            char = self.peek()
            if (quote and char == "\\") or char == "\n":
                raise _Unmodelled("heredoc")
            if char == "\\":
                quoted = True
                self.take()
                word.append(self.peek())
            elif char == quote:
                quote = ""
            elif not quote and char in ("'", '"'):
                quote, quoted = char, True
            else:
                word.append(char)
            self.data(nested)
        delimiter = "".join(word)
        if quote or not quoted or not _NEST_DELIMITER.fullmatch(delimiter):
            raise _Unmodelled("heredoc")
        self.heredocs.append((delimiter, strip))
        self.heredoc_frame = frame

    def bodies(self, nested: bool) -> None:
        """Each waiting heredoc's body, through its delimiter line."""
        for delimiter, strip in self.heredocs:
            line = None
            while line != delimiter:
                if not self.peek():
                    raise _Unmodelled("heredoc")
                end = self.text.find("\n", self.i)
                end = len(self.text) if end < 0 else end
                line = self.text[self.i : end]
                if not nested and ("'" in line or '"' in line):
                    raise _Unmodelled("heredoc-quote")
                while self.i < end:
                    self.data(nested)
                if self.peek():
                    self.take()
                line = line.lstrip("\t") if strip else line
        self.heredocs = []


def _nest_true(text: str) -> str | None:
    """``text`` with each double quote nested in a double-quoted string escaped, or None."""
    scanner = _NestScanner(text)
    try:
        scanner.code(False, False)
    except _Unmodelled:
        return None
    return "".join(scanner.out)


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


def _reading_pairs(command: str) -> tuple[tuple[bool, bool], ...]:
    """Every reading a guard decides under, as (line_true, nest_true), today's first.

    Each of :func:`_readings` on today's text, then each again on the
    nest-true text where :func:`_nest_true` vouches for it. A guard decides
    each on its own and holds if any holds.

    A double quote is escaped only inside a ``$( )``, ``${ }`` or backtick
    region, so a text holding no double quote, or neither a dollar sign nor a
    backtick, comes back from :func:`_nest_true` unchanged. So does every
    script it hands a shell, since the lexer builds each token from the text's
    own characters. Its nest-true readings would repeat today's, and are not
    made.
    """
    nested = '"' in command and ("$" in command or "`" in command)
    nests = (False, True) if nested and _nest_true(command) is not None else (False,)
    return tuple((line, nest) for nest in nests for line in _readings(command))


def _invocations(
    command: str, line_true: bool = False, nest_true: bool = False
) -> list[tuple[list[str], list[str]]] | None:
    """Every simple command in ``command`` as (env assignments, argv).

    ``line_true`` selects the line-true reading, :func:`_line_runs`;
    today's reading, :func:`_token_runs`, is the default. ``nest_true``
    reads :func:`_nest_true`'s text in place of ``command`` where it vouches
    for it, and ``command`` itself where it does not.

    None means the text could not be lexed, which callers treat as
    un-analysable rather than as safe.
    """
    vouched = _nest_true(command) if nest_true else None
    text = command if vouched is None else vouched
    runs = _line_runs(text) if line_true else _token_runs(text)
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
# DUPLICATE — ``guard_main_worktree.py`` carries a byte-identical copy of these
# three lines, for the same reason as the lexer above. A change here must be
# made in both. ``check_destructive_command.py`` no longer carries them: its
# fallback drops the quote characters and lexes again, which needs no
# command-position regex.
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


def pull_target(command: str, line_true: bool = False, nest_true: bool = False) -> str | None:
    """The refspec a ``git pull`` names, or ``None``.

    ``None`` covers every safe shape: not a pull at all, a bare ``git pull``
    (which follows the branch's own configured upstream and so can never target
    a foreign ref), a remote with no refspec, and a pull named only inside
    quoted text.
    """
    invocations = _invocations(command, line_true, nest_true)
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


def has_override(command: str, line_true: bool = False, nest_true: bool = False) -> bool:
    """True if an override var is set in the environment or as a genuine
    leading assignment on the guarded ``git pull``.

    A quoted mention (``echo "CLAUDE_ALLOW_MAIN_GIT=1"``) or a prefix on some
    *other* command does not count — the assignment must be the pull's own.
    """
    if any(os.environ.get(var) == "1" for var in _OVERRIDE_VARS):
        return True
    invocations = _invocations(command, line_true, nest_true)
    if invocations is None:
        return bool(_OVERRIDE_PREFIX.search(command))
    return any(
        _is_pull(argv) and _inline_override(assignments)
        for assignments, argv in invocations
    )


def should_block(command: str, *, current_branch: str) -> bool:
    """True when this pull would rewrite a protected branch with a foreign ref."""
    return blocking_target(command, current_branch=current_branch) is not None


def blocking_target(command: str, *, current_branch: str) -> str | None:
    """The foreign ref some reading pulls onto a protected branch without its override.

    Each reading is decided on its own: an overridden pull one reading makes
    visible must not clear a pull another reading holds without one.
    """
    if not is_protected(current_branch):
        return None
    for line_true, nest_true in _reading_pairs(command):
        if has_override(command, line_true, nest_true):
            continue
        target = pull_target(command, line_true, nest_true)
        if target is not None and target != current_branch:
            return target
    return None


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
    if all(pull_target(command, *reading) is None for reading in _reading_pairs(command)):
        return 0  # cheap reject before shelling out to git
    cwd = event.get("cwd") or os.getcwd()
    branch = _current_branch(cwd)
    target = blocking_target(command, current_branch=branch)
    if target is None:
        return 0
    sys.stderr.write(_MESSAGE.format(branch=branch, target=target))
    return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# ABOUTME: PreToolUse(Bash) guard for the architect card — refuse every write-shaped command.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/.claude/hooks/.
"""The ``architect`` card's read-only contract, enforced.

The card (``shared/agents/architect.md``) is a Fable planning agent whose one
hard rule is *you read, you never write*. It holds ``Bash``, and ``Bash`` is
wide enough to write through: a planner one misread brief away from
``git commit``, ``gh pr create`` or ``sed -i`` is a dispatch agent with no
reviewer and no PR, on the model the card exists to keep off implementation.
Until this hook the card said so itself — "instruction, not enforcement" — which
is the inert-controls rule in ``pr-workflow.md`` written as a confession. This
is the enforcement. The card names it in its ``hooks:`` frontmatter, so it
runs only while ``architect`` runs and never touches the session's own Bash.

**Every simple command in the text is classified, and one write refuses the
whole command.** A write after a read (``cat x; git commit``), inside a
substitution (``echo $(git commit)``), inside a nested shell (``bash -c``),
behind ``eval`` / ``xargs`` / ``find -exec`` or a leading wrapper (``env``,
``timeout``) is found where the shell would run it.

What is a write:

* **``git``** — anything but a read verb. The vocabulary is closed and its
  write surface is wide, so this is an allow-list: an unknown subcommand is
  refused, not waved through. ``branch`` / ``tag`` / ``stash`` / ``worktree``
  / ``remote`` / ``config`` / ``reflog`` / ``notes`` / ``submodule`` pass only
  in their listing forms, and ``--output`` is a write on any verb.
* **``gh``** — anything but ``view`` / ``list`` / ``diff`` / ``status`` /
  ``checks``, ``search``, ``help``, ``version``, and a ``gh api`` whose method
  is ``GET`` or ``HEAD`` with no ``-f`` / ``-F`` / ``--field`` /
  ``--raw-field`` / ``--input`` (each of which makes ``gh`` POST). Same
  reasoning as ``git``: allow-listed, fails closed.
* **File tools** — ``rm``, ``mv``, ``cp``, ``mkdir``, ``touch``, ``ln``,
  ``chmod``, ``chown``, ``patch``, ``tee``, ``dd``, ``install``, ``rsync``,
  ``truncate``, ``shred``, ``unlink``, ``sed -i`` and a sed script that
  writes (``w file``) or executes (``e``), an awk program that redirects or
  pipes a ``print`` or calls ``system()``, ``sort -o``, ``find -delete`` /
  ``-fprint``.
* **Interpreters, installers and runners** — ``python`` / ``perl`` / ``ruby``
  / ``node`` (each writes anything), ``uv`` and ``pip`` outside their
  ``list`` / ``show`` / ``freeze`` forms, ``make``, ``pytest``, ``alembic``,
  ``tox``, ``nox``, ``poetry``, ``npm``, ``npx``, a shell handed a *file*
  (``bash script.sh``, ``source``), and ``sleep`` — the card forbids waiting.
* **A redirection** (``>``, ``>>``, ``>|``, ``&>``, ``<>``, ``n>file``) whose
  target is neither a ``/dev/`` sink nor inside the session scratchpad.
  Nothing else is exempt: not ``/tmp``, not the repo, not ``$HOME``.
* **Anything else not in the read vocabulary below.** ``cat``, ``head``,
  ``sed -n``, ``grep``, ``rg``, ``find``, ``ls``, ``wc``, ``jq``, ``sort``,
  ``diff`` and their kin pass; a command this file does not know is refused
  by name so the card's ``Unknowns`` section can record it.

**The scratchpad exemption.** The card is told to ``wc -l`` its own plan
before returning it, which needs somewhere to put it. No harness variable
names the session scratchpad, so the root is taken from ``CLAUDE_SCRATCHPAD``
when set (the name the issue used; tests set it), else ``CLAUDE_CODE_TMPDIR``
(which the harness does export, and under which every session's scratchpad
lives), else ``~/.claude/tmp``. A target is exempt only when its *resolved*
path is inside a resolved root — ``..`` and symlinks are followed, an unset
variable is not expanded into anything, and a relative target is resolved
against the event's ``cwd``.

**There is no override variable**, unlike the sibling guards. A read-only card
with an escape hatch is a dispatch agent with extra steps; a plan that needs a
write returns ``ended_by: refused`` naming it, which is the card's own rule.

Not a member of the ``guard_main_worktree`` / ``guard_trunk_pull`` lexer
family, deliberately: that block lexes with ``shlex``, which drops quoting, so
``grep '>' file`` and ``grep > file`` are the same tokens afterwards and this
guard must tell them apart. It scans the text itself, tracking quotes, so a
quoted ``>`` is a pattern and a bare one is a write. Text with an unbalanced
quote is evaluated rather than waved through — the quote characters are
dropped and the text scanned again — because the safe direction for a guard
is to look harder.

Decision logic is split into pure functions so it is unit-tested without a
shell. This is an estate-canonical byte-copy (ratchet treaty): improve here
and redeploy; never edit the ``.claude/hooks/`` copy in isolation.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Scanning — every simple command, with its unquoted redirections.
# ---------------------------------------------------------------------------


@dataclass
class Simple:
    """One simple command: its words (quotes stripped) and its redirections."""

    words: list[str] = field(default_factory=list)
    redirects: list[tuple[str, str]] = field(default_factory=list)


class Unbalanced(ValueError):
    """A quote, substitution or heredoc was left open."""


_WHITESPACE = " \t"
_REDIRECT_OPS = ("<<<", "<<", "<&", "<>", "<", ">>", ">|", ">&", ">")
_DOUBLE_QUOTE_ESCAPES = '"\\$`\n'


class _Scanner:
    """A small quote-aware shell reader.

    It does not evaluate anything: it finds where the shell would start a new
    simple command, which characters belong to which word, and which ``>``
    is an operator rather than text.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.i = 0
        self.commands: list[Simple] = []
        self.current = Simple()
        self.word: list[str] = []
        self.in_word = False
        self.pending_redirect: str | None = None
        self.pending_heredoc = False
        self.heredocs: list[str] = []

    # -- words and commands --------------------------------------------------

    def _end_word(self) -> None:
        if not self.in_word:
            return
        word = "".join(self.word)
        self.word, self.in_word = [], False
        if self.pending_heredoc:
            self.heredocs.append(word.lstrip("-"))
            self.pending_heredoc = False
        elif self.pending_redirect is not None:
            self.current.redirects.append((self.pending_redirect, word))
            self.pending_redirect = None
        elif word in ("{", "}"):
            self._end_command()
        else:
            self.current.words.append(word)

    def _end_command(self) -> None:
        self._end_word()
        if self.current.words or self.current.redirects:
            self.commands.append(self.current)
        self.current = Simple()

    def _add(self, fragment: str) -> None:
        self.word.append(fragment)
        self.in_word = True

    # -- substitutions -------------------------------------------------------

    def _matching_paren(self, start: int) -> int:
        """Index of the ``)`` closing the ``(`` at ``start``, quote-aware."""
        depth, i, text = 0, start, self.text
        while i < len(text):
            char = text[i]
            if char == "\\":
                i += 2
                continue
            if char in "'\"":
                i = self._closing_quote(i)
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        raise Unbalanced("unclosed substitution")

    def _closing_quote(self, start: int) -> int:
        quote, i, text = self.text[start], start + 1, self.text
        while i < len(text):
            if quote == '"' and text[i] == "\\":
                i += 2
                continue
            if text[i] == quote:
                return i
            i += 1
        raise Unbalanced("unclosed quote")

    def _substitution(self, inner: str, rendered: str) -> None:
        """A ``$(...)`` or backtick body: its commands count, and it is a word."""
        self.commands.extend(scan(inner))
        self._add(rendered)

    def _dollar(self) -> None:
        text, i = self.text, self.i
        if text.startswith("$((", i):
            end = text.find("))", i + 3)
            if end < 0:
                raise Unbalanced("unclosed arithmetic")
            self._add(text[i : end + 2])
            self.i = end + 2
        elif text.startswith("$(", i):
            end = self._matching_paren(i + 1)
            self._substitution(text[i + 2 : end], text[i : end + 1])
            self.i = end + 1
        else:
            self._add("$")
            self.i += 1

    def _backtick(self) -> None:
        end = self.text.find("`", self.i + 1)
        if end < 0:
            raise Unbalanced("unclosed backtick")
        self._substitution(self.text[self.i + 1 : end], self.text[self.i : end + 1])
        self.i = end + 1

    # -- quotes --------------------------------------------------------------

    def _single_quoted(self) -> None:
        end = self._closing_quote(self.i)
        self._add(self.text[self.i + 1 : end])
        self.i = end + 1

    def _double_quoted(self) -> None:
        text = self.text
        self.i += 1
        self.in_word = True
        while True:
            if self.i >= len(text):
                raise Unbalanced("unclosed quote")
            char = text[self.i]
            if char == '"':
                self.i += 1
                return
            if char == "\\" and self.i + 1 < len(text) and text[self.i + 1] in _DOUBLE_QUOTE_ESCAPES:
                self._add(text[self.i + 1])
                self.i += 2
            elif char == "$":
                self._dollar()
            elif char == "`":
                self._backtick()
            else:
                self._add(char)
                self.i += 1

    # -- operators -----------------------------------------------------------

    def _redirect(self) -> None:
        text, i = self.text, self.i
        if text.startswith("&>", i):
            op = "&>>" if text.startswith("&>>", i) else "&>"
        else:
            op = next(candidate for candidate in _REDIRECT_OPS if text.startswith(candidate, i))
        # ``2>file``: the digit is the descriptor, not a word.
        if self.in_word and "".join(self.word).isdigit():
            self.word, self.in_word = [], False
        self._end_word()
        self.i = i + len(op)
        if op == "<<":
            self.pending_heredoc = True
        else:
            self.pending_redirect = op

    def _skip_heredoc_bodies(self) -> None:
        text = self.text
        for delimiter in self.heredocs:
            while self.i < len(text):
                end = text.find("\n", self.i)
                end = len(text) if end < 0 else end
                line, self.i = text[self.i : end], end + 1
                if line.lstrip("\t") == delimiter:
                    break
        self.heredocs = []

    def _newline(self) -> None:
        self._end_command()
        self.i += 1
        self._skip_heredoc_bodies()

    def _separator(self, length: int) -> None:
        self._end_command()
        self.i += length

    # -- main loop -----------------------------------------------------------

    def _escape(self) -> None:
        text = self.text
        if self.i + 1 < len(text) and text[self.i + 1] != "\n":
            self._add(text[self.i + 1])
        self.i += 2

    def _comment(self) -> None:
        end = self.text.find("\n", self.i)
        self.i = len(self.text) if end < 0 else end

    def _control(self, char: str) -> bool:
        """Handle a separator or redirection at ``char``; False if it is neither."""
        text = self.text
        if char in "<>" or text.startswith("&>", self.i):
            self._redirect()
        elif char in ";&|":
            two = text[self.i : self.i + 2]
            self._separator(2 if two in (";;", "&&", "||", "|&") else 1)
        elif char in "()":
            self._separator(1)
        else:
            return False
        return True

    def _step(self) -> None:
        char = self.text[self.i]
        if char == "\\":
            self._escape()
        elif char == "'":
            self._single_quoted()
        elif char == '"':
            self._double_quoted()
        elif char == "$":
            self._dollar()
        elif char == "`":
            self._backtick()
        elif char in _WHITESPACE:
            self._end_word()
            self.i += 1
        elif char == "\n":
            self._newline()
        elif char == "#" and not self.in_word:
            self._comment()
        elif not self._control(char):
            self._add(char)
            self.i += 1

    def run(self) -> list[Simple]:
        while self.i < len(self.text):
            self._step()
        self._end_command()
        if self.pending_heredoc or self.heredocs:
            raise Unbalanced("unterminated heredoc")
        return self.commands


_QUOTE_CHARS = str.maketrans("'\"`", "   ")


def scan(text: str) -> list[Simple]:
    """Every simple command in ``text``.

    Text that cannot be scanned as written is scanned again with its quote
    characters removed — the stricter reading, in which whatever the broken
    quoting hid is read as a command.
    """
    for reading in (text, text.translate(_QUOTE_CHARS)):
        try:
            return _Scanner(reading).run()
        except Unbalanced:
            continue
    return [Simple(words=line.split()) for line in text.splitlines() if line.split()]


# ---------------------------------------------------------------------------
# Classification — what is a read, what is a write.
# ---------------------------------------------------------------------------

_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")

# Commands whose only effect is output. Anything not here, and not handled by
# a rule below, is refused by name.
_READS = frozenset(
    {
        "cat", "head", "tail", "less", "more", "nl", "tac", "rev", "fold", "expand",
        "grep", "egrep", "fgrep", "rg", "ag", "ack", "fd", "fdfind",
        "ls", "tree", "wc", "uniq", "cut", "tr", "paste", "column", "comm", "join",
        "diff", "cmp", "file", "stat", "du", "df", "pwd", "echo", "printf",
        "true", "false", ":", "test", "[", "[[", "]]", "basename", "dirname",
        "realpath", "readlink", "which", "type", "date", "jq", "yq", "seq", "expr",
        "md5sum", "sha1sum", "sha256sum", "strings", "od", "xxd", "hexdump",
        "uname", "hostname", "id", "whoami", "ps", "pgrep", "free", "uptime",
        "cd", "pushd", "popd", "dirs", "export", "set", "unset", "shopt", "local",
        "declare", "readonly", "return", "exit", "break", "continue", "read",
        "man", "help",
    }
)

# Leading words that run another command rather than being one.
_WRAPPERS = frozenset({"env", "command", "exec", "sudo", "nohup", "time", "builtin"})
_WRAPPER_VALUE_FLAGS = frozenset({"-u", "-g", "-p", "-C", "-h", "-r", "-t", "-T", "-U", "-S"})

# Keywords that sit in command position and are followed by a command.
_KEYWORD_PREFIX = frozenset({"if", "then", "elif", "else", "while", "until", "do", "!"})
# Keywords whose whole simple command is control flow, not a program.
_KEYWORD_WHOLE = frozenset({"for", "select", "case", "function", "fi", "done", "esac", "in"})

_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
_SCRIPT_FLAGS = frozenset({"-c", "-lc", "-ic", "-xc"})
_MAX_DEPTH = 3

_XARGS_VALUE_FLAGS = frozenset({"-n", "-I", "-P", "-d", "-L", "-s", "-E", "-a"})
_FIND_WRITE_FLAGS = frozenset({"-delete", "-fprint", "-fprint0", "-fprintf"})
_FIND_EXEC_FLAGS = frozenset({"-exec", "-execdir", "-ok", "-okdir"})

_GIT_READS = frozenset(
    {
        "log", "show", "diff", "grep", "ls-tree", "ls-files", "ls-remote", "rev-parse",
        "status", "blame", "cat-file", "describe", "shortlog", "rev-list", "name-rev",
        "for-each-ref", "show-ref", "merge-base", "count-objects", "check-ignore",
        "check-attr", "diff-tree", "diff-index", "diff-files", "range-diff",
        "show-branch", "whatchanged", "var", "version", "--version", "help", "--help",
        "verify-commit", "verify-tag", "fsck", "cherry",
    }
)
_GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace"})
_GIT_BRANCH_LIST_FLAGS = frozenset(
    {"-l", "--list", "-a", "--all", "-r", "--remotes", "--contains", "--no-contains",
     "--merged", "--no-merged", "--points-at", "--show-current"}
)
_GIT_BRANCH_WRITE_FLAGS = frozenset(
    {"-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy", "-u",
     "--set-upstream-to", "--unset-upstream", "-f", "--force", "--edit-description"}
)
_GIT_TAG_WRITE_FLAGS = frozenset({"-a", "-s", "-d", "--delete", "-f", "--force", "-m", "-F"})
_GIT_CONFIG_READ_FLAGS = frozenset(
    {"--get", "--get-all", "--get-regexp", "-l", "--list", "--show-origin", "--show-scope"}
)

_GH_READ_VERBS = frozenset({"view", "list", "diff", "status", "checks"})
_GH_READ_NOUNS = frozenset({"search", "help", "version", "--version", "--help", "status"})
_GH_API_METHOD_FLAGS = ("-X", "--method")
_GH_API_BODY_FLAGS = frozenset({"-f", "-F", "--field", "--raw-field", "--input"})
_GH_API_READ_METHODS = frozenset({"GET", "HEAD"})

# ``s/a/b/w file`` and a bare ``w file`` write; ``e`` executes.
_SED_ADDRESS = r"(?:[\d$,~+\s]*|/(?:[^/\\]|\\.)*/[\d,$]*)?"
_SED_WRITES = re.compile(
    r"(?:^|[;{\n])\s*" + _SED_ADDRESS + r"\s*[wWe](?:\s|$)|/[gpIiMm0-9]*[we](?:\s|$)"
)
_SED_SCRIPT_FLAGS = frozenset({"-e", "--expression"})
# awk's ``print > file`` and ``print | cmd`` write; ``system()`` runs.
_AWK_WRITES = re.compile(r"\bprintf?\b[^;{}\n]*[>|]|\bsystem\s*\(")
_AWK_VALUE_FLAGS = ("-F", "-v")

_DEV_SINKS = ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "/dev/fd/")
_SCRATCHPAD_VARS = ("CLAUDE_SCRATCHPAD", "CLAUDE_CODE_TMPDIR")


def _basename(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def _operands(words: list[str]) -> list[str]:
    return [word for word in words[1:] if word != "--" and not word.startswith("-")]


def _short_flags(words: list[str]) -> str:
    return "".join(
        word[1:] for word in words[1:] if word.startswith("-") and not word.startswith("--")
    )


def _unwrap(words: list[str]) -> list[str]:
    """``words`` with leading assignments, wrappers and keywords removed."""
    while words:
        while words and _ASSIGNMENT.match(words[0]):
            words = words[1:]
        if not words:
            break
        name = _basename(words[0])
        if name in _KEYWORD_PREFIX:
            words = words[1:]
        elif name == "timeout":
            rest = [word for word in words[1:] if not word.startswith("-")]
            words = rest[1:]
        elif name in _WRAPPERS:
            rest = words[1:]
            while rest and (_ASSIGNMENT.match(rest[0]) or rest[0].startswith("-")):
                rest = rest[2:] if rest[0] in _WRAPPER_VALUE_FLAGS and len(rest) > 1 else rest[1:]
            words = rest
        else:
            break
    return words


# -- git ---------------------------------------------------------------------


def _git_subcommand(words: list[str]) -> tuple[str, list[str]]:
    """The verb ``git`` runs and the arguments after it, global options skipped."""
    index = 1
    while index < len(words):
        word = words[index]
        if word in _GIT_VALUE_OPTIONS:
            index += 2
        elif word.startswith("-") and word not in ("--version", "--help"):
            index += 1
        else:
            break
    if index >= len(words):
        return "", []
    return words[index], words[index + 1 :]


def _git_listing_only(verb: str, args: list[str]) -> bool:
    """True when this ``branch`` / ``tag`` / ``stash`` … invocation only lists."""
    flags = {arg for arg in args if arg.startswith("-")}
    operands = [arg for arg in args if not arg.startswith("-")]
    if verb == "branch":
        if flags & _GIT_BRANCH_WRITE_FLAGS:
            return False
        return not operands or bool(flags & _GIT_BRANCH_LIST_FLAGS)
    if verb == "tag":
        if flags & _GIT_TAG_WRITE_FLAGS:
            return False
        return not operands or bool(flags & {"-l", "--list", "--contains", "--points-at"})
    if verb == "stash":
        return operands[:1] in (["list"], ["show"])
    if verb in ("notes", "reflog"):
        return not operands or operands[0] in ("list", "show")
    if verb == "worktree":
        return operands[:1] == ["list"]
    if verb == "remote":
        return not operands or operands[0] in ("show", "get-url")
    if verb == "config":
        return bool(flags & _GIT_CONFIG_READ_FLAGS)
    if verb == "submodule":
        return operands[:1] == ["status"]
    return False


def _git_refusal(words: list[str]) -> str | None:
    verb, args = _git_subcommand(words)
    if not verb:
        return None
    if any(arg == "-o" or arg.startswith("--output") for arg in args):
        return f"`git {verb} --output` writes a file"
    if verb in _GIT_READS or _git_listing_only(verb, args):
        return None
    return f"`git {verb}` is a git mutation"


# -- gh ------------------------------------------------------------------------


def _gh_api_refusal(args: list[str]) -> str | None:
    for index, arg in enumerate(args):
        flag, _, inline = arg.partition("=")
        if flag in _GH_API_METHOD_FLAGS:
            method = inline or (args[index + 1] if index + 1 < len(args) else "")
            if method.upper() not in _GH_API_READ_METHODS:
                return f"`gh api -X {method}` is a GitHub mutation"
        elif flag in _GH_API_BODY_FLAGS:
            return f"`gh api {flag}` sends a request body, which is a GitHub mutation"
    return None


def _gh_refusal(words: list[str]) -> str | None:
    positional = [word for word in words[1:] if not word.startswith("-")]
    noun = positional[0] if positional else "--help"
    if noun in _GH_READ_NOUNS or (not positional and any(w.startswith("--") for w in words[1:])):
        return None
    if noun == "api":
        return _gh_api_refusal(words[2:])
    if len(positional) < 2:
        return None  # ``gh pr`` alone prints usage
    verb = positional[1]
    if verb in _GH_READ_VERBS:
        return None
    return f"`gh {noun} {verb}` is a GitHub mutation"


# -- file tools ----------------------------------------------------------------


def _sed_refusal(words: list[str]) -> str | None:
    if "i" in _short_flags(words) or any(w.startswith("--in-place") for w in words[1:]):
        return "`sed -i` edits a file in place"
    if "-f" in words[1:] or any(w.startswith("--file") for w in words[1:]):
        return "`sed -f` runs a script file this guard cannot read"
    scripts = [
        words[index + 1]
        for index, word in enumerate(words[:-1])
        if word in _SED_SCRIPT_FLAGS
    ]
    scripts += [w.partition("=")[2] for w in words[1:] if w.startswith("--expression=")]
    if not scripts:
        operands = _operands(words)
        scripts = operands[:1]
    for script in scripts:
        if _SED_WRITES.search(script):
            return "a sed script that writes (`w`) or executes (`e`) is not a read"
    return None


def _awk_refusal(words: list[str]) -> str | None:
    args = words[1:]
    if "-f" in args:
        return "`awk -f` runs a program file this guard cannot read"
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            break
        if arg in _AWK_VALUE_FLAGS:
            index += 2
        elif arg.startswith(_AWK_VALUE_FLAGS) or arg.startswith("-"):
            index += 1
        else:
            break
    program = args[index] if index < len(args) else ""
    if _AWK_WRITES.search(program):
        return "an awk program that redirects, pipes or calls system() is not a read"
    return None


def _sort_output(words: list[str]) -> str | None:
    """The file ``sort -o`` / ``--output`` names, or None."""
    for index, word in enumerate(words[1:], start=1):
        if word in ("-o", "--output"):
            return words[index + 1] if index + 1 < len(words) else ""
        if word.startswith("--output="):
            return word.partition("=")[2]
        if word.startswith("-o") and not word.startswith("--"):
            return word[2:]
    return None


def _sort_refusal(words: list[str], *, cwd: str, environ: Mapping[str, str]) -> str | None:
    target = _sort_output(words)
    if target is None or is_sink(target, cwd=cwd, environ=environ):
        return None
    return f"`sort -o {target}` writes outside the session scratchpad"


def _xargs_argv(words: list[str]) -> list[str]:
    rest = words[1:]
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in _XARGS_VALUE_FLAGS and len(rest) > 1 else rest[1:]
    return rest


def _find_exec_argv(words: list[str]) -> list[str]:
    for index, word in enumerate(words):
        if word in _FIND_EXEC_FLAGS:
            argv = []
            for following in words[index + 1 :]:
                if following in (";", "+"):
                    break
                argv.append(following)
            return argv
    return []


# -- redirections --------------------------------------------------------------


def scratchpad_roots(environ: Mapping[str, str]) -> list[Path]:
    """Every directory a redirection may land in, resolved."""
    roots = [Path(environ[var]) for var in _SCRATCHPAD_VARS if environ.get(var)]
    if not roots:
        roots = [Path.home() / ".claude" / "tmp"]
    return [root.resolve() for root in roots]


_VARIABLE = re.compile(r"\$(?:\{([A-Za-z_]\w*)\}|([A-Za-z_]\w*))")


def _expand(target: str, environ: Mapping[str, str]) -> str:
    """``target`` with ``$VAR`` / ``${VAR}`` / leading ``~`` from ``environ`` — unset stays literal."""

    def value(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        return environ.get(name, match.group(0))

    expanded = _VARIABLE.sub(value, target)
    home = environ.get("HOME") or str(Path.home())
    if expanded == "~" or expanded.startswith("~/"):
        expanded = home + expanded[1:]
    return expanded


def _writes_file(op: str, target: str) -> bool:
    if op.startswith("<") and op != "<>":
        return False
    if op == ">&" and (target.isdigit() or target == "-"):
        return False  # a descriptor duplication, not a file
    return not target.startswith("(")  # ``>(cmd)`` — cmd is classified on its own


def is_sink(target: str, *, cwd: str, environ: Mapping[str, str]) -> bool:
    """True when writing ``target`` persists nothing outside the session scratchpad."""
    expanded = _expand(target, environ)
    if expanded.startswith(_DEV_SINKS):
        return True
    resolved = (Path(cwd) / expanded).resolve()
    return any(resolved.is_relative_to(root) for root in scratchpad_roots(environ))


def _redirect_refusal(simple: Simple, *, cwd: str, environ: Mapping[str, str]) -> str | None:
    for op, target in simple.redirects:
        if _writes_file(op, target) and not is_sink(target, cwd=cwd, environ=environ):
            return f"`{op} {target}` writes outside the session scratchpad"
    return None


# -- the decision --------------------------------------------------------------


def _shell_refusal(words: list[str], depth: int, cwd: str, environ: Mapping[str, str]) -> str | None:
    for index, word in enumerate(words[1:], start=1):
        if word in _SCRIPT_FLAGS and index + 1 < len(words):
            if depth >= _MAX_DEPTH:
                return "a shell nested this deep is not a read"
            return _refusal(words[index + 1], depth=depth + 1, cwd=cwd, environ=environ)
    return f"`{_basename(words[0])}` handed a script file runs code this guard cannot read"


def _tee_refusal(words: list[str], *, cwd: str, environ: Mapping[str, str]) -> str | None:
    for target in _operands(words):
        if not is_sink(target, cwd=cwd, environ=environ):
            return f"`tee {target}` writes outside the session scratchpad"
    return None


def _installer_refusal(words: list[str]) -> str | None:
    """``uv`` and ``pip`` read only in their ``list`` / ``show`` / ``freeze`` forms."""
    name = _basename(words[0])
    verbs = _operands(words)[: 2 if name == "uv" else 1]
    if verbs and verbs[-1] in ("list", "show", "freeze"):
        return None
    return f"`{' '.join([name, *verbs])}` installs or runs, which is not a read"


def _find_refusal(words: list[str], depth: int, cwd: str, environ: Mapping[str, str]) -> str | None:
    if any(word in _FIND_WRITE_FLAGS for word in words):
        return "`find -delete` / `-fprint` writes"
    return _argv_refusal(_find_exec_argv(words) or ["true"], depth, cwd, environ)


# Programs with a rule of their own. Each takes the unwrapped argv; the ones
# that can run another command also take the nesting depth and the sink context.
_ARGV_RULES = {
    "git": lambda words, depth, cwd, environ: _git_refusal(words),
    "gh": lambda words, depth, cwd, environ: _gh_refusal(words),
    "sed": lambda words, depth, cwd, environ: _sed_refusal(words),
    "awk": lambda words, depth, cwd, environ: _awk_refusal(words),
    "gawk": lambda words, depth, cwd, environ: _awk_refusal(words),
    "mawk": lambda words, depth, cwd, environ: _awk_refusal(words),
    "nawk": lambda words, depth, cwd, environ: _awk_refusal(words),
    "sort": lambda words, depth, cwd, environ: _sort_refusal(words, cwd=cwd, environ=environ),
    "tee": lambda words, depth, cwd, environ: _tee_refusal(words, cwd=cwd, environ=environ),
    "uv": lambda words, depth, cwd, environ: _installer_refusal(words),
    "pip": lambda words, depth, cwd, environ: _installer_refusal(words),
    "pip3": lambda words, depth, cwd, environ: _installer_refusal(words),
    "find": _find_refusal,
    "eval": lambda words, depth, cwd, environ: _refusal(
        " ".join(words[1:]), depth=depth + 1, cwd=cwd, environ=environ
    ),
    "xargs": lambda words, depth, cwd, environ: _argv_refusal(
        _xargs_argv(words) or ["echo"], depth, cwd, environ
    ),
}


def _argv_refusal(words: list[str], depth: int, cwd: str, environ: Mapping[str, str]) -> str | None:
    words = _unwrap(words)
    if not words:
        return None
    name = _basename(words[0])
    if name in _KEYWORD_WHOLE or name in _READS:
        return None
    if name in _SHELLS:
        return _shell_refusal(words, depth, cwd, environ)
    rule = _ARGV_RULES.get(name)
    if rule is not None:
        return rule(words, depth, cwd, environ)
    return f"`{name}` is not a sanctioned read shape"


def _refusal(command: str, *, depth: int, cwd: str, environ: Mapping[str, str]) -> str | None:
    for simple in scan(command):
        reason = _redirect_refusal(simple, cwd=cwd, environ=environ) or _argv_refusal(
            simple.words, depth, cwd, environ
        )
        if reason is not None:
            return reason
    return None


def refusal(command: str, *, cwd: str, environ: Mapping[str, str]) -> str | None:
    """One-line reason ``command`` is not a read, or None when every part of it is."""
    return _refusal(command, depth=0, cwd=cwd, environ=environ)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:  # unparseable input → don't block
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = (event.get("tool_input") or {}).get("command", "") or ""
    reason = refusal(command, cwd=event.get("cwd") or os.getcwd(), environ=os.environ)
    if reason is None:
        return 0
    sys.stderr.write(
        f"BLOCKED — architect is read-only: {reason}. "
        "Plan without it, or return `ended_by: refused` naming this act.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())

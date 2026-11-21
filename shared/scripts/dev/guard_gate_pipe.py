#!/usr/bin/env python3
# ABOUTME: PreToolUse(Bash) guard — refuse a gate whose exit status a trailing filter swallows.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/.claude/hooks/.
"""Block ``<gate> | tail`` and ``<gate> | head``.

A pipeline's exit status is its **last** command's. So::

    pytest -q 2>&1 | tail -20
    rc=$?

reports *tail's* status — always 0 — and a failing suite reads as a pass. The
same shape has certified a failing ``make verify`` and a refusing
``worktree_doctor.py teardown``.

``pr-workflow.md`` has prohibited this in prose since 2026-08-21 and it recurred
twice afterwards, once in a PR whose own trajectory note cites the rule while
breaking it. OS#424 measured the general case: procedural rules recur 8+ times
as prose and 0-2 times as hooks. This is the hook.

Scope is deliberately narrow, because a guard that cries wolf gets overridden
reflexively:

* Only a **gate** command counts — a test runner, a linter, a verify target.
  ``git log | head -5`` is an ordinary, correct idiom.
* Only a filter in the pipeline's **final** position counts, because that is the
  one whose status becomes the pipeline's. ``pytest | tail -20 | grep -c FAILED``
  is not refused: it is already weird, but the last stage is not the swallower
  this rule is about.
* ``tee`` and a redirect are the sanctioned forms and are never refused.

A multi-line command is also read line by line as the shell reads it: a newline
outside quotes ends a line, a backslash-newline joins two, a comment ends at its
own line, and a line ending in a pipe continues on the next. Where the lexer
reports a quote spanning lines, the command is read again with its quote
characters blanked, and each line that began inside quotes is read from its own
start. The reading of the whole text is kept beside these, so a command it
refuses is still refused.

Not a member of the ``guard_main_worktree`` / ``guard_trunk_pull`` lexer family,
deliberately: that block splits on ``|`` as a separator and therefore destroys
the pipeline structure this guard has to see. It lexes with ``shlex`` directly
and keeps the pipe operators.

This is defence in depth. Hooks see only Claude Code's Bash tool — a terminal,
a Makefile or a CI runner all bypass it.
"""

import json
import os
import re
import shlex
import sys
from typing import NamedTuple

# Same escape-hatch shape as the sibling guards: an env var, or a genuine
# leading assignment on the offending command itself.
_OVERRIDE_VAR = "CLAUDE_ALLOW_GATE_PIPE"

# The filters whose exit status is meaninglessly 0 and which are routinely
# reached for to shorten a gate's output. `grep` is deliberately absent: a
# trailing grep exits non-zero on no-match, so it does not manufacture a green.
_SWALLOWING_FILTERS = frozenset({"tail", "head"})

# Commands whose exit status is a verdict about the tree. Matched on the
# basename, so `.venv/bin/pytest` and `/usr/bin/ruff` count.
_GATE_COMMANDS = frozenset({"pytest", "gaudi", "ruff", "mypy", "bandit"})

# `make` is a gate only for the targets that run gates; `make clean | head` is
# not this rule's business.
_MAKE = "make"
_GATE_MAKE_TARGETS = ("verify", "ci")

# Runners that delegate to a gate: the gate is a later word in the same argv.
_RUNNERS = frozenset({"uv", "python", "python3", "poetry", "hatch", "nox", "tox"})

_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")

# Tokens that end one pipeline and begin the next. `|` is NOT here: it is the
# structure this guard exists to read.
_PIPELINE_SEPARATORS = frozenset({";", "&", "&&", "||", "(", ")", "{", "}", "\n"})
_PIPE_TOKENS = frozenset({"|", "|&"})


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


def _lex(text):
    """``text`` as shell tokens with pipe operators preserved, or None."""
    lexer = _ShellLexer(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _lex_or_degrade(command):
    """Tokens for ``command``; on an unbalanced quote, retry without quote chars.

    A guard's safe direction is to look harder, not to wave the command
    through — an unlexable command is un-analysed, not proven innocent.
    """
    tokens = _lex(command)
    if tokens is not None:
        return tokens
    stripped = command.replace("'", " ").replace('"', " ")
    return _lex(stripped) or stripped.split()


def _pipelines(tokens):
    """``tokens`` split into pipelines, each a list of stage argvs."""
    pipelines = [[[]]]
    for token in tokens:
        if token in _PIPELINE_SEPARATORS:
            pipelines.append([[]])
        elif token in _PIPE_TOKENS:
            pipelines[-1].append([])
        else:
            pipelines[-1][-1].append(token)
    return [
        [stage for stage in pipeline if stage]
        for pipeline in pipelines
        if any(stage for stage in pipeline)
    ]


def _split_assignments(argv):
    """``argv`` as (leading ``VAR=value`` assignments, the command it runs)."""
    index = 0
    while index < len(argv) and _ASSIGNMENT.match(argv[index]):
        index += 1
    return argv[:index], argv[index:]


def _basename(word):
    return word.rsplit("/", 1)[-1]


def is_gate(argv):
    """True when this stage's exit status is a verdict about the tree."""
    _, words = _split_assignments(argv)
    if not words:
        return False
    names = [_basename(word) for word in words]
    if names[0] in _GATE_COMMANDS:
        return True
    if names[0] == _MAKE:
        return any(
            target.startswith(_GATE_MAKE_TARGETS)
            for target in words[1:]
            if not target.startswith("-")
        )
    if names[0] in _RUNNERS:
        # `uv run pytest`, `python -m pytest`, `tox -e lint` — the gate is a
        # later word. Only look at words, never at flag values that merely
        # contain the name.
        return any(name in _GATE_COMMANDS for name in names[1:])
    return False


def is_swallowing_filter(argv):
    """True when this stage's exit status is meaninglessly 0."""
    _, words = _split_assignments(argv)
    return bool(words) and _basename(words[0]) in _SWALLOWING_FILTERS


def _inline_override(argv):
    assignments, _ = _split_assignments(argv)
    for assignment in assignments:
        name, _, value = assignment.partition("=")
        if name == _OVERRIDE_VAR and value == "1":
            return True
    return False


# Line-aware readings of a multi-line command. Today's reading above lexes the
# whole text in one pass, and shlex reads an unquoted newline as whitespace, so
# a pipeline on its own line is glued to the line before it. The readings below
# take each line end from the lexer's own state instead: the stream hands the
# lexer a marker in place of every newline outside quotes, escaped or not.
#
# Two marker characters stand in for newlines: one ends a line, one joins a
# continued line. They are taken from these candidates, skipping any the text
# itself holds; text holding too many is read one physical line at a time.
_MARKER_CANDIDATES = "\x1c\x1d\x1e\x1f"
_DEFAULT_PUNCTUATION = shlex.shlex("", punctuation_chars=True).punctuation_chars
# What a quoted lone newline is read as: a word, never the separator it equals.
_QUOTED_NEWLINE = "''"


class _LineStream:
    """``text`` fed to a lexer one character at a time, each newline as the shell reads it.

    An escaped newline is the continuation marker, a newline inside quotes stays
    a newline, and any other is the line-end marker, which the lexer takes as
    punctuation and so ends the word before it. A comment ends at its own line:
    ``readline``, which shlex calls only to skip a comment, leaves the newline
    unread. Lines that begin inside quotes are recorded by offset.
    """

    def __init__(self, text, line_end, continuation):
        self._text = text
        self._position = 0
        self._line_end = line_end
        self._continuation = continuation
        self._state_before = " "
        self.lexer = None
        self.quoted_line_starts = []

    def read(self, size=1):
        if self._position >= len(self._text):
            return ""
        char = self._text[self._position]
        self._position += 1
        state, before = self.lexer.state, self._state_before
        self._state_before = state
        if char != "\n":
            return char
        if state in self.lexer.escape:
            # The backslash was read inside quotes: the next line is in them too.
            if before in self.lexer.quotes:
                self.quoted_line_starts.append(self._position)
            return self._continuation
        if state in self.lexer.quotes:
            self.quoted_line_starts.append(self._position)
            return char
        return self._line_end

    def readline(self, size=-1):
        end = self._text.find("\n", self._position)
        end = len(self._text) if end < 0 else end
        rest = self._text[self._position:end]
        self._position = end
        return rest


class _Reading(NamedTuple):
    tokens: list
    failed: bool
    quoted_line_starts: list


def _line_lexer(text, line_end, continuation):
    """``_ShellLexer`` over ``text`` through a :class:`_LineStream`, and that stream."""
    stream = _LineStream(text, line_end, continuation)
    lexer = _ShellLexer(stream, posix=True, punctuation_chars=_DEFAULT_PUNCTUATION + line_end)
    lexer.whitespace_split = True
    stream.lexer = lexer
    return lexer, stream


def _tokens_until_error(lexer, failures):
    """The lexer's tokens up to a lex error, which is recorded in ``failures``."""
    try:
        yield from lexer
    except ValueError:
        failures.append(True)


def _line_tokens(raw, line_end, continuation):
    """``raw`` with markers resolved: a line end is kept unless a pipe waits for a stage."""
    marker = re.compile(f"({re.escape(line_end)})")
    last = None
    for token in raw:
        for part in marker.split(token):
            part = part.replace(continuation, "")
            if not part:
                continue
            if part == "\n":
                part = _QUOTED_NEWLINE
            if part == line_end and last in _PIPE_TOKENS:
                continue
            last = part
            yield part


def _read_lines(text, line_end, continuation):
    """``text`` read with line ends from the lexer's state, as a :class:`_Reading`."""
    lexer, stream = _line_lexer(text, line_end, continuation)
    failures = []
    raw = _tokens_until_error(lexer, failures)
    tokens = [";" if t == line_end else t for t in _line_tokens(raw, line_end, continuation)]
    return _Reading(tokens, bool(failures), stream.quoted_line_starts)


def _first_line(text, line_end, continuation):
    """The tokens of ``text``'s first line, continued lines included, lexed afresh."""
    lexer, _ = _line_lexer(text, line_end, continuation)
    tokens = []
    for token in _line_tokens(_tokens_until_error(lexer, []), line_end, continuation):
        if token == line_end:
            break
        tokens.append(token)
    return tokens


def _line_offenders(command):
    """Offenders found by reading ``command``'s lines as the shell does.

    R1 reads the text with line ends from the lexer's state. Where the lexer
    reports a quote spanning lines, or cannot lex the text, it may have
    mis-tracked the quoting, so two more readings run: R2, the same reading
    with every quote character blanked, and R3, each line that began inside
    quotes lexed afresh from its own start to its own end.
    """
    if "\n" not in command:
        return []
    markers = [char for char in _MARKER_CANDIDATES if char not in command]
    if len(markers) < 2:
        return [
            offender
            for line in command.split("\n")
            for offender in _offenders(_lex_or_degrade(line))
        ]
    line_end, continuation = markers[:2]
    reading = _read_lines(command, line_end, continuation)
    found = _offenders(reading.tokens)
    if reading.failed or reading.quoted_line_starts:
        blanked = command.replace("'", " ").replace('"', " ")
        found += _offenders(_read_lines(blanked, line_end, continuation).tokens)
        for start in reading.quoted_line_starts:
            found += _offenders(_first_line(command[start:], line_end, continuation))
    return found


def offending_pipelines(command):
    """Every pipeline in ``command`` whose gate's status a trailing filter eats.

    The line-aware readings are searched first, then today's reading of the
    whole text, which is kept as it is: nothing it refuses can pass.
    """
    found = []
    for pipeline in _line_offenders(command) + _offenders(_lex_or_degrade(command)):
        if pipeline not in found:
            found.append(pipeline)
    return found


def _offenders(tokens):
    """The pipelines in ``tokens`` whose gate's status a trailing filter eats."""
    offenders = []
    for pipeline in _pipelines(tokens):
        if len(pipeline) < 2:
            continue
        if not is_swallowing_filter(pipeline[-1]):
            continue
        gates = [stage for stage in pipeline[:-1] if is_gate(stage)]
        if not gates:
            continue
        # The override must be this pipeline's own, not another command's.
        if any(_inline_override(stage) for stage in pipeline):
            continue
        offenders.append(pipeline)
    return offenders


def should_block(command):
    """True when running ``command`` would report a filter's status as a gate's."""
    if os.environ.get(_OVERRIDE_VAR) == "1":
        return False
    return bool(offending_pipelines(command))


_MESSAGE = """BLOCKED — a gate's exit status would be swallowed by `{filter_name}`.

    {rendered}

A pipeline's exit status is its LAST command's, so `$?` here is `{filter_name}`'s
— always 0. A failing gate reads as a pass. This has certified a failing
`make verify` and a refusing `worktree_doctor.py teardown`.

Use a form that keeps the gate's own status:

    <gate> > /tmp/out.txt 2>&1; rc=$?     # then read the file
    <gate> 2>&1 | tail -20; rc=${{PIPESTATUS[0]}}

Deliberate one-off: prefix the command with
    {var}=1 <your command>
"""


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:  # unparseable input → don't block
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = (event.get("tool_input") or {}).get("command", "") or ""
    if os.environ.get(_OVERRIDE_VAR) == "1":
        return 0
    offenders = offending_pipelines(command)
    if not offenders:
        return 0
    pipeline = offenders[0]
    sys.stderr.write(
        _MESSAGE.format(
            filter_name=_basename(_split_assignments(pipeline[-1])[1][0]),
            rendered=" | ".join(" ".join(stage) for stage in pipeline),
            var=_OVERRIDE_VAR,
        )
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())

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
reports a quote spanning lines, the command is read again with the quote
characters blanked from each quote that crossed a line end or never closed, and
each line that began inside quotes is read from its own start. A quote that
opens and closes on one line is read as quoted text, as in a single-line
command. The reading of the whole text is kept beside these, so a command it
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


class _QuoteSpan:
    """A quote from its opening character to its closing one (``end`` None: never closed)."""

    def __init__(self, start):
        self.start = start
        self.end = None
        self.crossed = False

    def is_suspect(self):
        """True when the lexer cannot vouch for this quote: it crossed a line end or never closed."""
        return self.crossed or self.end is None


class _LineStream:
    """``text`` fed to a lexer one character at a time, each newline as the shell reads it.

    An escaped newline is the continuation marker, a newline inside quotes stays
    a newline, and any other is the line-end marker, which the lexer takes as
    punctuation and so ends the word before it. A comment ends at its own line:
    ``readline``, which shlex calls only to skip a comment, leaves the newline
    unread. Lines that begin inside quotes are recorded by offset.

    Each quote span is recorded as the lexer's state shows it opening and
    closing: a quote character read outside quote and escape states opens one,
    and the same character read in its own quote state closes it. A span is
    marked crossed when a line begins inside it.
    """

    def __init__(self, text, line_end, continuation):
        self._text = text
        self._position = 0
        self._line_end = line_end
        self._continuation = continuation
        self._state_before = " "
        self.lexer = None
        self.quoted_line_starts = []
        self.quote_spans = []

    def read(self, size=1):
        if self._position >= len(self._text):
            return ""
        char = self._text[self._position]
        self._position += 1
        state, before = self.lexer.state, self._state_before
        self._state_before = state
        if char in self.lexer.quotes:
            self._note_quote(char, state)
        if char != "\n":
            return char
        if state in self.lexer.escape:
            # The backslash was read inside quotes: the next line is in them too.
            if before in self.lexer.quotes:
                self._note_quoted_line_start()
            return self._continuation
        if state in self.lexer.quotes:
            self._note_quoted_line_start()
            return char
        return self._line_end

    def _note_quote(self, char, state):
        index = self._position - 1
        if state in self.lexer.quotes:
            if char == state:
                self.quote_spans[-1].end = index
        elif state not in self.lexer.escape:
            self.quote_spans.append(_QuoteSpan(index))

    def _note_quoted_line_start(self):
        self.quoted_line_starts.append(self._position)
        self.quote_spans[-1].crossed = True

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
    quote_spans: list


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
    return _Reading(tokens, bool(failures), stream.quoted_line_starts, stream.quote_spans)


def _blank_suspect_quotes(text, spans):
    """``text`` with every quote character of each suspect span blanked, opening through closing.

    Both kinds are blanked inside such a span, so no quote character the lexer
    read as literal text comes alive on the re-read. A span the lexer opened
    and closed on one line is left as it is.
    """
    chars = list(text)
    for span in spans:
        if not span.is_suspect():
            continue
        end = len(chars) - 1 if span.end is None else span.end
        for index in range(span.start, end + 1):
            if chars[index] in "'\"":
                chars[index] = " "
    return "".join(chars)


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
    with the quote characters of each quote the lexer cannot vouch for blanked
    (one that crossed a line end or never closed), and R3, each line that
    began inside quotes lexed afresh from its own start to its own end.
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
        blanked = _blank_suspect_quotes(command, reading.quote_spans)
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

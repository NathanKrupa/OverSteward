#!/usr/bin/env python3
# ABOUTME: PreToolUse(Bash) guard — refuse a process substitution whose command never ends.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/.claude/hooks/.
"""Block ``read -t 5 < <(:; exec cat /dev/zero >/dev/null)`` and its relatives.

Foreground ``sleep`` is refused in Claude Code, so on 2026-11-12 a dispatch agent
built its own sleep out of a timed ``read`` on a process substitution. ``read``
gives up after five seconds and the shell closes its end of the pipe, but
``cat /dev/zero >/dev/null`` never touches that pipe, so nothing ever tells it
to stop: every call leaked one process spinning at full speed. 115 of them had
the laptop at load ~127 before another agent found them (OS#723).

The general shape is a process substitution, ``<(…)`` or ``>(…)``, whose command
reads a source that never runs dry and nothing downstream bounds it:

* an endless device — ``/dev/zero``, ``/dev/full``, ``/dev/urandom``,
  ``/dev/random`` — as an operand, a redirect or a ``dd if=``;
* ``yes``, ``sleep infinity``, and ``tail -f`` without ``--pid``.

A later ``head -c``, ``dd … count=`` or a ``timeout`` wrapper bounds the source,
and so does any ``head`` unless the source is a stream of zeros, in which a
line count never finds its newline. Never-ending readers *outside* a
substitution are not this guard's business: ``cat /dev/zero | head -c 10`` is
ordinary, and a foreground command that never ends is visible to whoever ran it.

Only a substitution the shell would actually create counts. Quoted text, a
``#`` comment and a heredoc body are prose, so a commit message, an issue
comment or a file written through a heredoc can describe the shape freely
(the OS#401 lesson). A substitution inside ``$(…)`` within double quotes is
real and is read.

Not a member of the ``guard_main_worktree`` lexer family: that block discards
the parentheses this guard has to match. It scans the command text itself and
lexes each substitution body with ``shlex``.

This is defence in depth. Hooks see only Claude Code's Bash tool — a terminal,
a Makefile or a CI runner all bypass it. A loop that never ends without a
substitution (``while :; do …; done``) is outside it too.
"""

import json
import os
import re
import shlex
import sys

_OVERRIDE_VAR = "CLAUDE_ALLOW_ENDLESS_SUBSTITUTION"

# Devices that never run dry. A stream of zeros has no newline, so a line-counting
# `head` never finishes reading it; a random stream has newlines.
_ZERO_DEVICES = frozenset({"/dev/zero", "/dev/full"})
_RANDOM_DEVICES = frozenset({"/dev/urandom", "/dev/random"})
_ZERO = "zero"
_ENDLESS = "endless"

# Leading words that run the next word as the command.
_WRAPPERS = frozenset({"exec", "command", "nohup"})

_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")

# Punctuation-only tokens that stay inside a stage, because the word after them
# is part of the same command (`cat < /dev/zero`).
_REDIRECTS = frozenset({"<", ">", ">>", "<&", ">&", "<>", ">|", "&>", "&>>", "<<<"})
_PIPES = frozenset({"|", "|&"})
_PUNCTUATION = frozenset("();<>|&")

# Characters that end an unquoted word: a `#` after one starts a comment, and a
# heredoc's delimiter word stops at one.
_WORD_BREAKS = frozenset(" \t\n;&|()<>")


class _Scanner:
    """Finds every process substitution the shell would create in a command."""

    def __init__(self, text):
        self.text = text
        self.bodies = []

    def scan(self):
        self._unquoted(0, nested=False)
        return self.bodies

    def _unquoted(self, i, nested):
        """Scan shell text from ``i``; when ``nested``, return the index of the closing ``)``."""
        text, depth, heredocs = self.text, 0, []
        while i < len(text):
            char, pair = text[i], text[i:i + 2]
            if char == "\\":
                i += 2
            elif char == "'":
                end = text.find("'", i + 1)
                i = len(text) if end < 0 else end + 1
            elif char == '"':
                i = self._double_quoted(i + 1)
            elif char == "#" and (i == 0 or text[i - 1] in _WORD_BREAKS):
                end = text.find("\n", i)
                i = len(text) if end < 0 else end
            elif char == "\n" and heredocs:
                i = self._skip_heredoc_bodies(i + 1, heredocs)
                heredocs = []
            elif text.startswith("<<<", i):
                i += 3
            elif pair == "<<":
                i = self._heredoc_delimiter(i + 2, heredocs)
            elif pair in ("<(", ">("):
                end = self._unquoted(i + 2, nested=True)
                self.bodies.append(text[i + 2:end])
                i = end + 1
            elif pair == "$(":
                i = self._unquoted(i + 2, nested=True) + 1
            elif char == "(":
                depth += 1
                i += 1
            elif char == ")":
                if nested and depth == 0:
                    return i
                depth = max(depth - 1, 0)
                i += 1
            else:
                i += 1
        # Unclosed: the body runs to the end. Looking harder is the safe direction.
        return len(text)

    def _double_quoted(self, i):
        """Skip a double-quoted string from ``i``, reading any ``$(…)`` inside it."""
        text = self.text
        while i < len(text):
            if text[i] == "\\":
                i += 2
            elif text[i] == '"':
                return i + 1
            elif text.startswith("$(", i):
                i = self._unquoted(i + 2, nested=True) + 1
            else:
                i += 1
        return len(text)

    def _heredoc_delimiter(self, i, heredocs):
        """Record the heredoc opened at ``i`` (just past ``<<``); return where its word ends."""
        text = self.text
        strip_tabs = text.startswith("-", i)
        if strip_tabs:
            i += 1
        while i < len(text) and text[i] in " \t":
            i += 1
        start = i
        quote = None
        while i < len(text):
            char = text[i]
            if quote:
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif char in _WORD_BREAKS:
                break
            i += 1
        word = re.sub(r"[\"'\\]", "", text[start:i])
        if word:
            heredocs.append((word, strip_tabs))
        return i

    def _skip_heredoc_bodies(self, i, heredocs):
        """Skip each pending heredoc body, starting at ``i``; return the index after the last."""
        text = self.text
        for word, strip_tabs in heredocs:
            while i < len(text):
                end = text.find("\n", i)
                line = text[i:] if end < 0 else text[i:end]
                i = len(text) if end < 0 else end + 1
                if (line.lstrip("\t") if strip_tabs else line) == word:
                    break
        return i


def substitution_bodies(command):
    """The text inside every ``<(…)`` and ``>(…)`` the shell would create, nested ones included."""
    return _Scanner(command).scan()


def _lex(text):
    """``text`` as shell tokens with operators kept, or None when the quoting is unbalanced."""
    lexer = shlex.shlex(text.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _pipelines(body):
    """``body`` split into pipelines, each a list of stage word lists."""
    tokens = _lex(body)
    if tokens is None:
        # A guard's safe direction is to look harder, not to wave the body through.
        tokens = _lex(body.replace("'", " ").replace('"', " ")) or body.split()
    pipelines = [[[]]]
    for token in tokens:
        operator = token and set(token) <= _PUNCTUATION
        if not operator or token in _REDIRECTS:
            pipelines[-1][-1].append(token)
        elif token in _PIPES:
            pipelines[-1].append([])
        else:
            pipelines.append([[]])
    return [[stage for stage in pipeline if stage] for pipeline in pipelines]


def _command_words(stage):
    """``stage`` with leading assignments and wrappers such as ``exec`` removed."""
    index = 0
    while index < len(stage) and (
        _ASSIGNMENT.match(stage[index]) or stage[index] in _WRAPPERS
    ):
        index += 1
    return stage[index:]


def _basename(word):
    return word.rsplit("/", 1)[-1]


def _reads_device(words, devices):
    return any(word in devices or word.endswith(tuple("=" + d for d in devices)) for word in words)


def _follows(arguments):
    """True when ``tail``'s arguments follow a file and nothing ends the following."""
    if any(argument.startswith("--pid") for argument in arguments):
        return False
    for argument in arguments:
        if argument == "--follow" or argument.startswith("--follow="):
            return True
        if argument.startswith("-") and not argument.startswith("--"):
            flags = re.match(r"-[A-Za-z]*", argument).group(0)
            if "f" in flags or "F" in flags:
                return True
    return False


def _endless_source(stage):
    """What never runs dry in this stage: ``_ZERO``, ``_ENDLESS``, or None."""
    words = _command_words(stage)
    if not words:
        return None
    if _reads_device(words, _ZERO_DEVICES):
        return _ZERO
    if _reads_device(words, _RANDOM_DEVICES):
        return _ENDLESS
    name, arguments = _basename(words[0]), words[1:]
    if name == "yes":
        return _ENDLESS
    if name == "sleep" and any(arg in ("infinity", "inf") for arg in arguments):
        return _ENDLESS
    if name == "tail" and _follows(arguments):
        return _ENDLESS
    return None


def _bounds(stage, source):
    """True when this stage stops reading ``source`` after a finite amount."""
    words = _command_words(stage)
    if not words:
        return False
    name, arguments = _basename(words[0]), words[1:]
    if name == "timeout":
        return True
    if name == "dd":
        return any(argument.startswith("count=") for argument in arguments)
    if name == "head":
        counts_bytes = any(
            argument.startswith(("-c", "--bytes")) for argument in arguments
        )
        return counts_bytes or source != _ZERO
    return False


def _is_endless(pipeline):
    pending = None
    for stage in pipeline:
        if pending is not None and _bounds(stage, pending):
            pending = None
        source = _endless_source(stage)
        if source is not None and not _bounds(stage, source):
            pending = source
    return pending is not None


def endless_substitutions(command):
    """Every process substitution body in ``command`` that would never end."""
    return [
        body
        for body in substitution_bodies(command)
        if any(_is_endless(pipeline) for pipeline in _pipelines(body))
    ]


_MESSAGE = """BLOCKED — a process substitution that never ends: <({body})

Whatever reads this substitution can stop, but the command inside it cannot, so
it outlives the call and keeps running. As a sleep substitute,
`read -t N < <(exec cat /dev/zero)` leaked one process spinning at full speed
per call: 115 of them had the laptop at load ~127 (OS#723).

Wait with a sanctioned shape instead:

    a run_in_background until-loop with sleep inside it:
        until [ -f <done-file> ]; do sleep 30; done
    the Monitor tool
    timeout N tail --pid=<pid> -f /dev/null

Deliberate one-off: set {var}=1 in the environment Claude Code runs in.
"""


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:  # unparseable input → don't block
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    if os.environ.get(_OVERRIDE_VAR) == "1":
        return 0
    command = (event.get("tool_input") or {}).get("command", "") or ""
    offenders = endless_substitutions(command)
    if not offenders:
        return 0
    body = " ".join(offenders[0].split())
    sys.stderr.write(_MESSAGE.format(body=body, var=_OVERRIDE_VAR))
    return 2


if __name__ == "__main__":
    sys.exit(main())

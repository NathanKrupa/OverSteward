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


def _lex(text):
    """``text`` as shell tokens with pipe operators preserved, or None."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
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


def offending_pipelines(command):
    """Every pipeline in ``command`` whose gate's status a trailing filter eats."""
    offenders = []
    for pipeline in _pipelines(_lex_or_degrade(command)):
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

#!/usr/bin/env python3
# ABOUTME: PreToolUse(Bash) guard — refuse CLI drains billed to the metered Anthropic API key.
# ABOUTME: Canonical in OverSteward shared/scripts/dev/; deployed to <repo>/.claude/hooks/.
"""Block ``grantspider`` subcommands that spend Anthropic API credits.

On 2026-08-20 an operator session launched ``grantspider enrich`` as a
background Bash task — a 500-foundation Sonnet drain through
``grantspider.connectors.anthropic``, billed to the metered API key of Nathan's
Individual Org. It drained the org's credits to zero, Anthropic disabled the
org's API access, and AG production Studio (customer-facing) went down with it.

The standing order already existed — *enrich-drain stays in-session (Max)* —
and was violated by misreading: "launched from a session" is not "Max-billed".
A prohibition that lives only in memory is an inert control, so this fails
closed instead.

Scope is the *bulk drain* shapes, each confirmed against grantspider's CLI to
construct an ``AnthropicClient`` (or ``build_llm_client("anthropic", ...)``)
and loop over a cohort. The near-miss neighbours are deliberately left alone,
because every one of them is the sanctioned Max-billed path or costs nothing:

* ``enrich-profile pull-batch`` / ``enrich-profile apply`` — the Max workflow
  this guard points people at.
* ``llm-extract export-queue`` / ``import-results`` — the operator-in-loop
  bridge, same shape.
* ``hygiene beautify-pull-batch`` / ``beautify-apply`` — likewise.
* ``enrich-dispositions`` — local-GPU qwen, zero metered cost. It shares a
  prefix with ``enrich`` and must never be caught by it.
* ``db scratch``, ``dq snapshot``, and every other read-only verb.

A guard that cries wolf gets overridden reflexively, which leaves the real case
unguarded — so matching is on the whole subcommand *path*, word by word, never
on a substring.

Deliberate metered runs arm with a recorded decision:

    CLAUDE_ALLOW_METERED_API=1 grantspider <subcommand>

This is defence in depth, not the control. Hooks see only Claude Code's Bash
tool — a terminal, a Makefile, direnv, Dagster or Railway all bypass it. The
CLI-side arming gate (grantspider#2322) is the control.

Known limit: a mention inside a heredoc *body* whose terminator never appears
(a truncated command) is still read as a command. Quoted mentions and complete
heredocs are stripped. The override is the escape hatch when it misfires.

Decision logic is split into pure functions so it is unit-tested without a CLI.
"""

import json
import os
import re
import sys

# Env var that waves the guard through. Named for the cost it authorises, not
# for the tool — the sibling guards' CLAUDE_ALLOW_MAIN_GIT would be a
# surprising thing to type in front of a spend.
_OVERRIDE_VAR = "CLAUDE_ALLOW_METERED_API"

# The sanctioned Max-billed replacements, named per blocked shape. A refusal
# that only says "no" gets worked around; one that names the alternative gets
# followed.
_ENRICH_DRAIN = (
    "the enrich-drain workflow — pull a batch with `enrich-profile pull-batch`,\n"
    "  do the reasoning in THIS session (Max), then `enrich-profile apply`"
)
_LLM_EXTRACT_QUEUE = (
    "the operator-in-loop bridge — `llm-extract export-queue`, extract in THIS\n"
    "  session (Max), then `llm-extract import-results`"
)
_BEAUTIFY_QUEUE = (
    "the operator-in-loop bridge — `hygiene beautify-pull-batch`, rewrite in\n"
    "  THIS session (Max), then `hygiene beautify-apply`"
)
_IN_SESSION = "in-session reasoning on Max, or the backfill pipeline running on Railway"

# Subcommand paths that spend metered credits, each with its Max-billed
# alternative. Matched as a whole-word PREFIX of the invoked subcommand path,
# so ("enrich",) catches `enrich --limit 500` but never `enrich-profile ...`
# or `enrich-dispositions`. A tuple of pairs rather than a dict: module-level
# mutable state is exactly what a byte-copied hook must not carry.
_METERED_SHAPES = (
    (("enrich",), _ENRICH_DRAIN),
    (("enrichment-worker",), _ENRICH_DRAIN),
    (("llm-extract", "run"), _LLM_EXTRACT_QUEUE),
    (("hygiene", "beautify-text"), _BEAUTIFY_QUEUE),
    (("pcs", "backfill-grants"), _IN_SESSION),
    (("pcs", "backfill-programmes"), _IN_SESSION),
    (("dq", "ntee-check"), _IN_SESSION),
    (("corporate-direct-ingest",), _IN_SESSION),
)

# ``grantspider`` only at a command position — start of line, after a shell
# separator (``; & | && ||``), or after a substitution/grouping opener — with
# an optional leading run of ``VAR=value`` assignments and an optional
# ``uv run [--flags]`` wrapper. An explicit path (``.venv/bin/grantspider``)
# counts; a bare mention inside a string does not, because quoted spans are
# blanked before this ever runs.
#
# DUPLICATE — ``guard_main_worktree.py``, ``guard_trunk_pull.py`` and
# ``check_destructive_command.py`` carry byte-identical copies of these two
# lines. They are NOT shared: each hook is a standalone byte-copy deployed into
# other repos' ``.claude/hooks/``, where a sibling import would not resolve. A
# change here must be made in all of them.
_SEP = r"(?:^|[\n;&|`(])\s*"  # start-of-line, shell separator, or substitution opener
_ASSIGN = r"(?:\w+=\S+\s+)*"  # a run of ``VAR=value`` env assignments
_AT_CMD = _SEP + _ASSIGN

_INVOCATION = re.compile(
    _AT_CMD
    + r"(?:uv\s+run\s+(?:-\S+\s+)*)?"
    + r"(?:\S*/)?grantspider\b(?P<rest>[^\n;&|]*)"
)

_FLAG = re.compile(r"^-")

# ``--help`` renders text and spends nothing, so it must never be refused —
# not even for a group that is metered end to end.
_HELP = re.compile(r"(?:^|\s)(?:--help|-h)(?:\s|$)")

# The inline escape hatch: the override set as a real leading assignment on the
# guarded command (start-of-line or after a separator, possibly among other
# assignments). Matching a command-position prefix rather than a bare substring
# is what closes the bypass where the name appears only inside a string.
_OVERRIDE_PREFIX = re.compile(
    _SEP
    + _ASSIGN
    + rf"{_OVERRIDE_VAR}=1\s+"
    + _ASSIGN
    + r"(?:uv\s+run\s+(?:-\S+\s+)*)?(?:\S*/)?grantspider\b"
)

# A heredoc opener and the line that terminates its body. PR bodies and issue
# comments are written this way constantly, and they talk about the very
# commands this guard blocks.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(?P<marker>\w+)\1")

_MESSAGE = (
    "BLOCKED — `grantspider {shape}` bills the METERED Anthropic API key.\n\n"
    "This is not covered by Nathan's Max subscription. On 2026-08-20 one such\n"
    "run drained the Individual Org's credits to zero; Anthropic disabled the\n"
    "org's API access, which took AG production Studio down with it.\n\n"
    "Use the Max-billed path instead:\n"
    "  {alternative}\n\n"
    "If this run is genuinely meant to spend metered credits, arm it — a\n"
    "recorded decision, not a reflex:\n"
    "    {override}=1 <your command>\n"
)


def strip_noncommand_text(command: str) -> str:
    """Blank out quoted spans and heredoc bodies, preserving offsets.

    A shell command that *mentions* a drain is not a drain. ``git commit -m
    "block grantspider enrich"`` and a ``gh pr create`` heredoc describing this
    very guard both sit at a command position once the quoting is ignored.
    Replacing the inner text with spaces (rather than deleting it) keeps every
    separator and line break where it was, so the command-position regexes see
    the same structure they would have seen without the prose.
    """
    return _blank_heredoc_bodies(_blank_quoted_spans(command))


def _blank_quoted_spans(command: str) -> str:
    """Replace the contents of single- and double-quoted spans with spaces."""
    out = list(command)
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote == "" and char in "'\"":
            quote = char
        elif quote and char == quote:
            quote = ""
        elif quote:
            if char != "\n":  # newlines still delimit commands
                out[index] = " "
            if quote == '"' and char == "\\":
                index += 1  # an escaped char cannot close the span
                if index < len(command) and command[index] != "\n":
                    out[index] = " "
        index += 1
    return "".join(out)


def _blank_heredoc_bodies(command: str) -> str:
    """Replace every complete heredoc body with blank lines."""
    lines = command.split("\n")
    marker = None
    for position, line in enumerate(lines):
        if marker is None:
            found = _HEREDOC.search(line)
            marker = found.group("marker") if found else None
            continue
        if line.strip() == marker:
            marker = None
        else:
            lines[position] = ""
    return "\n".join(lines)


def _invocation_args(command: str) -> str | None:
    """Everything a ``grantspider`` invocation is given, or ``None`` if it is not one."""
    match = _INVOCATION.search(strip_noncommand_text(command))
    return match.group("rest") if match else None


def subcommand_path(command: str) -> tuple[str, ...] | None:
    """The subcommand words a ``grantspider`` invocation names, or ``None``.

    ``None`` means "not a grantspider invocation at all". The path stops at the
    first option flag, because click's subcommand path is always the leading
    run of bare words — ``enrich --limit 500`` is the ``enrich`` command with
    an option, not a two-word path.
    """
    args = _invocation_args(command)
    if args is None:
        return None
    words: list[str] = []
    for word in args.split():
        if _FLAG.match(word):
            break
        words.append(word)
    return tuple(words)


def metered_alternative(path: tuple[str, ...]) -> str | None:
    """The Max-billed alternative for a metered subcommand path, else ``None``."""
    for shape, alternative in _METERED_SHAPES:
        if path[: len(shape)] == shape:
            return alternative
    return None


def has_override(command: str) -> bool:
    """True if the run is armed — in the environment, or as a leading assignment.

    A bare substring (``echo "CLAUDE_ALLOW_METERED_API=1"``) does not count:
    the assignment must sit at a command position in front of the invocation.
    """
    if os.environ.get(_OVERRIDE_VAR) == "1":
        return True
    return bool(_OVERRIDE_PREFIX.search(strip_noncommand_text(command)))


def refusal(command: str) -> str | None:
    """The refusal message for a metered command, or ``None`` to allow it."""
    if has_override(command):
        return None
    args = _invocation_args(command)
    if args is None or _HELP.search(args):
        return None
    path = subcommand_path(command)
    if not path:
        return None
    alternative = metered_alternative(path)
    if alternative is None:
        return None
    return _MESSAGE.format(
        shape=" ".join(path), alternative=alternative, override=_OVERRIDE_VAR
    )


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:  # unparseable input → don't block
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = (event.get("tool_input") or {}).get("command", "") or ""
    message = refusal(command)
    if message is None:
        return 0
    sys.stderr.write(message)
    return 2


if __name__ == "__main__":
    sys.exit(main())

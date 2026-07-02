#!/usr/bin/env python3
# ABOUTME: Sanctioned runner — load .env in-process, then exec a command with it. No secret on argv/stdout.
# ABOUTME: Canonical (OverSteward shared/scripts/dev/); deployed byte-identical to every repo's scripts/dev/.
"""Run a command with a project's ``.env`` loaded into the environment — safely.

Agents repeatedly need to run the dockerized test backend (``make verify``,
``pytest``) with secrets from ``.env`` in scope. The obvious ``source .env`` is
blocked by the credential-hygiene hook for good reason: a connection string with
an unquoted ``&`` (every Neon URL carries ``&channel_binding=require``) leaks
through bash job control onto stderr — and stderr is captured in the agent
transcript (grantspider, 2026-05-26, five strings rotated). The workaround was a
hand-rolled in-process shim, reinvented session after session.

This is that shim, sanctioned and reusable. It parses ``.env`` in-process (never
through the shell, so no job-control split), merges the values into the
environment **without ever printing a value**, and ``exec``s the target command
so it inherits them. The secret values touch only this process's memory and the
child's environment — never argv, never stdout, never stderr.

Usage::

    scripts/dev/with_test_env.py [--env-file PATH] [--] COMMAND [ARG ...]

Examples::

    scripts/dev/with_test_env.py make verify
    scripts/dev/with_test_env.py -- pytest -k integration
    scripts/dev/with_test_env.py --env-file .env.test python -m mytool

Existing process environment wins over ``.env`` (matching ``load_dotenv``'s
default), so an explicit override on the command line is still respected.

Dependency-free by design (stdlib only) so the byte-copy deploys to any repo
without requiring ``python-dotenv``.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

USAGE = "usage: with_test_env.py [--env-file PATH] [--] COMMAND [ARG ...]"

# Replaces the running process with the command. Injected in tests so the exec
# can be observed without actually handing off control.
Executor = Callable[[str, "Sequence[str]", "Mapping[str, str]"], object]

# python-dotenv value grammar, replicated in stdlib (no third-party import — this
# runner is a canonical byte-copy that must deploy to every repo dependency-free).
# A double-quoted body is a run of ``\<x>`` escape pairs or non-quote chars up to
# the matching ``"``; single-quoted is the same up to the matching ``'``. Both are
# anchored so the opening quote must start the value, and both are unicode-escape
# decoded (``\n`` → newline, ``\'`` → ``'``, etc.) exactly as python-dotenv does.
_DOUBLE_QUOTED = re.compile(r'"((?:\\"|[^"])*)"')
_SINGLE_QUOTED = re.compile(r"'((?:\\'|[^'])*)'")
_DOUBLE_QUOTE_ESCAPES = re.compile(r"\\[\\'\"abfnrtv]")
_SINGLE_QUOTE_ESCAPES = re.compile(r"\\[\\']")
# After a closing quote, only whitespace + an optional ``#`` comment may follow;
# anything else (``"abc"def"``) is malformed and drops the line, as python-dotenv.
_TRAILING_COMMENT = re.compile(r"\s*(?:#.*)?$")
# An unquoted inline comment: a ``#`` preceded by whitespace, to end of value.
# A leading ``#`` (no preceding whitespace) is kept — it is part of the value.
_INLINE_COMMENT = re.compile(r"\s+#.*")


def _decode_escapes(pattern: re.Pattern[str], body: str) -> str:
    """Decode the escape sequences python-dotenv recognises within a quoted body."""
    return pattern.sub(lambda m: m.group(0).encode().decode("unicode-escape"), body)


def _parse_quoted(
    value: str, quoted: re.Pattern[str], escapes: re.Pattern[str]
) -> str | None:
    """Return the decoded body of a matched quoted value, or ``None`` if malformed.

    A value is well-formed only when the closing quote is followed by nothing but
    optional whitespace and an optional ``#`` comment; a stray ``"abc"def"`` drops
    the line rather than silently truncating to ``abc``.
    """
    match = quoted.match(value)
    if not match or not _TRAILING_COMMENT.match(value, match.end()):
        return None
    return _decode_escapes(escapes, match.group(1))


def _parse_value(raw_value: str) -> str | None:
    """Resolve one ``.env`` value the way python-dotenv does; ``None`` = drop the line.

    ``raw_value`` is everything after the first ``=`` on the line, before any
    whitespace normalisation.

    - A value opening with ``"`` up to a matching ``"`` is a double-quoted string:
      escape sequences are decoded and anything after the closing quote (typically
      a trailing comment) is discarded. A ``#`` inside the quotes is preserved.
    - A value opening with ``'`` up to a matching ``'`` is a single-quoted string:
      ``\\'`` / ``\\\\`` are decoded, trailing content is discarded, in-quote ``#``
      is preserved.
    - An opening quote with no matching close (``"abc"def"``, ``"unterminated``)
      is malformed — python-dotenv drops the whole binding; return ``None`` so the
      value is never mangled into a wrong (possibly shorter, still-plausible) one.
    - Otherwise the value is unquoted: an inline comment is stripped only when the
      ``#`` is preceded by whitespace, then trailing whitespace is trimmed. A value
      that merely begins or ends with a quote is left verbatim.
    """
    value = raw_value.lstrip()
    first = value[:1]
    if first == '"':
        return _parse_quoted(value, _DOUBLE_QUOTED, _DOUBLE_QUOTE_ESCAPES)
    if first == "'":
        return _parse_quoted(value, _SINGLE_QUOTED, _SINGLE_QUOTE_ESCAPES)
    return _INLINE_COMMENT.sub("", value).rstrip()


def parse_env_file(text: str) -> dict[str, str]:
    """Parse ``.env`` content into a mapping. Pure string work — no shell, no echo.

    Handles ``KEY=VALUE``, an optional ``export`` prefix, blank lines, and ``#``
    comment lines. Values follow python-dotenv semantics (see ``_parse_value``):
    matched surrounding quotes are stripped and decoded, out-of-quote trailing
    comments are dropped, in-quote ``#`` and connection strings with ``=`` or
    ``&`` survive intact, and a malformed quoted value drops its line rather than
    being mangled.
    """
    env: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            continue
        parsed = _parse_value(value)
        if parsed is not None:
            env[key] = parsed
    return env


def build_environment(env_file: Path, base_env: Mapping[str, str]) -> dict[str, str]:
    """Merge ``.env`` values onto a copy of ``base_env``; existing keys are not overridden."""
    merged = dict(base_env)
    for key, value in parse_env_file(env_file.read_text(encoding="utf-8")).items():
        merged.setdefault(key, value)
    return merged


def _default_executor(file: str, args: Sequence[str], env: Mapping[str, str]) -> object:
    os.execvpe(file, list(args), dict(env))


def _parse_args(argv: Sequence[str]) -> tuple[Path, list[str]]:
    """Split argv into (env_file, command). Empty command signals a usage error."""
    args = list(argv)
    env_file = Path(".env")
    if args and args[0] == "--env-file":
        if len(args) < 2:
            return env_file, []
        env_file = Path(args[1])
        args = args[2:]
    if args and args[0] == "--":
        args = args[1:]
    return env_file, args


def run(
    argv: Sequence[str],
    *,
    base_env: Mapping[str, str] | None = None,
    executor: Executor = _default_executor,
) -> int:
    """Load ``env_file`` and exec the command. Returns a non-zero code on failure only.

    On success the process is replaced by ``executor`` and this never returns; the
    trailing ``return 0`` exists for the injected-executor test path.
    """
    base_env = os.environ if base_env is None else base_env
    env_file, command = _parse_args(argv)
    if not command:
        print(USAGE, file=sys.stderr)
        return 2
    if not env_file.is_file():
        print(f"with_test_env: env file not found: {env_file}", file=sys.stderr)
        return 1
    child_env = build_environment(env_file, base_env)
    try:
        executor(command[0], command, child_env)
    except FileNotFoundError:
        print(f"with_test_env: command not found: {command[0]}", file=sys.stderr)
        return 127
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())

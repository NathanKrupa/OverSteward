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
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

USAGE = "usage: with_test_env.py [--env-file PATH] [--] COMMAND [ARG ...]"

# Replaces the running process with the command. Injected in tests so the exec
# can be observed without actually handing off control.
Executor = Callable[[str, "Sequence[str]", "Mapping[str, str]"], object]


def _strip_quotes(value: str) -> str:
    """Drop one layer of matching surrounding quotes; leave the value otherwise verbatim."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_env_file(text: str) -> dict[str, str]:
    """Parse ``.env`` content into a mapping. Pure string work — no shell, no echo.

    Handles ``KEY=VALUE``, an optional ``export`` prefix, blank lines, and ``#``
    comment lines. Values are kept verbatim apart from one layer of surrounding
    quotes, so connection strings with ``=`` or ``&`` survive intact.
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
        env[key] = _strip_quotes(value.strip())
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

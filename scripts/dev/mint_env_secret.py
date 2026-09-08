#!/usr/bin/env python
# ABOUTME: OUTER entrypoint — mint a fresh URL-safe token straight into a .env file, replacing any existing line.
# ABOUTME: The value is never printed; the only output is which line changed and the token's length.

"""Mint (or rotate) a secret in a ``.env`` file without ever printing it.

    scripts/dev/mint_env_secret.py SMOKE_PROBE_TOKEN            # repo-root .env
    scripts/dev/mint_env_secret.py STEWARD_PROBE_TOKEN --env-file /path/.env

``secrets.token_urlsafe(32)`` produces no quote or backslash, which is what a
Cloudflare rule expression needs of a compared literal. An existing assignment
is replaced in place; a missing one is appended.

* **0** — written.
* **1** — the file could not be read or written.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1

TOKEN_BYTES = 32


_ASSIGNMENT_PREFIX = ("", "export ")


def _assigns(line: str, name: str) -> bool:
    """Whether ``line`` assigns ``name`` — with or without an ``export`` prefix."""
    stripped = line.strip()
    for prefix in _ASSIGNMENT_PREFIX:
        if (
            stripped.startswith(prefix)
            and stripped[len(prefix) :].split("=", 1)[0].strip() == name
            and "=" in stripped
        ):
            return True
    return False


def mint_into(env_file: Path, name: str, *, token: str | None = None) -> str:
    """Write ``name=<token>`` into ``env_file``; return ``replaced`` or ``appended``.

    Every existing assignment of ``name`` — plain or ``export``ed — is removed
    and one fresh line written where the first stood, so a rotation leaves no
    previous value behind. The file is written to a private temporary sibling
    and renamed into place, so an interrupted mint never truncates the
    credential file; a new file is created owner-read-write only.
    """
    value = token or secrets.token_urlsafe(TOKEN_BYTES)
    existed = env_file.exists()
    lines = env_file.read_text().splitlines() if existed else []
    assignment = f"{name}={value}"
    matches = [i for i, line in enumerate(lines) if _assigns(line, name)]
    if matches:
        lines[matches[0]] = assignment
        for index in reversed(matches[1:]):
            del lines[index]
        outcome = "replaced"
    else:
        lines.append(assignment)
        outcome = "appended"
    mode = env_file.stat().st_mode & 0o777 if existed else 0o600
    # The sibling's name ends in ``.env`` so ``.gitignore``'s ``*.env`` covers
    # it, and it is removed on any failure so an interruption leaves neither a
    # truncated credential file nor a stray one holding the fresh secret.
    temporary = env_file.with_name(f"{env_file.name}.mint-{os.getpid()}.env")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write("\n".join(lines) + "\n")
        os.chmod(temporary, mode)
        os.replace(temporary, env_file)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("name", help="the variable to mint, e.g. SMOKE_PROBE_TOKEN")
    parser.add_argument(
        "--env-file", default=".env", type=Path, help="file to write (default .env)"
    )
    args = parser.parse_args(argv)
    try:
        outcome = mint_into(args.env_file, args.name)
    except OSError as error:
        print(f"could not write {args.env_file}: {error}", file=sys.stderr)
        return EXIT_FAILED
    print(f"{args.name}: {outcome} in {args.env_file} (value never printed)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

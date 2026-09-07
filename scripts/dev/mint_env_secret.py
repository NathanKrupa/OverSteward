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
import secrets
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1

TOKEN_BYTES = 32


def mint_into(env_file: Path, name: str, *, token: str | None = None) -> str:
    """Write ``name=<token>`` into ``env_file``; return ``replaced`` or ``appended``."""
    value = token or secrets.token_urlsafe(TOKEN_BYTES)
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    assignment = f"{name}={value}"
    matches = [i for i, line in enumerate(lines) if line.split("=", 1)[0].strip() == name]
    if matches:
        lines[matches[-1]] = assignment
        outcome = "replaced"
    else:
        lines.append(assignment)
        outcome = "appended"
    env_file.write_text("\n".join(lines) + "\n")
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

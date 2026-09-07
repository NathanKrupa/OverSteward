#!/usr/bin/env python
# ABOUTME: OUTER entrypoint — copy one value from a .env file into a GitHub Actions repository secret.
# ABOUTME: The value travels on gh's stdin, never a command line, never stdout, never the whole file.

"""Push one ``.env`` value to a repository's Actions secrets.

``gh secret set`` takes its value from ``--body`` (a command line — the leak
the credential-hygiene rule forbids), from ``--env-file`` (which uploads
**every** key in the file), or from stdin. This is the stdin form, with the
value read in-process from the named file:

    scripts/dev/push_actions_secret.py SMOKE_PROBE_TOKEN --repo NathanKrupa/aigranthelper

* **0** — set (gh's own confirmation is printed).
* **1** — gh refused.
* **2** — the variable is unset or blank in the file.
"""

from __future__ import annotations

import argparse
import subprocess  # nosec B404 -- list-form argv, no shell; the value goes to stdin only
import sys
from collections.abc import Callable
from pathlib import Path

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_MISCONFIGURED = 2

Runner = Callable[[list[str], str], int]


def read_env_value(env_file: Path, name: str) -> str:
    """``name``'s value in ``env_file`` — the last assignment wins, quotes stripped, never printed."""
    value = ""
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        if key.strip() == name:
            value = rest.strip().strip("'\"")
    return value


def gh_argv(name: str, repo: str) -> list[str]:
    """The exact gh invocation — note what is absent: the value."""
    return ["gh", "secret", "set", name, "--repo", repo]


def _run(argv: list[str], stdin: str) -> int:
    return subprocess.run(argv, input=stdin, text=True, check=False).returncode  # nosec B603


def push(name: str, repo: str, env_file: Path, *, runner: Runner = _run) -> int:
    value = read_env_value(env_file, name)
    if not value:
        print(f"misconfigured: {name} is unset or blank in {env_file}", file=sys.stderr)
        return EXIT_MISCONFIGURED
    return EXIT_OK if runner(gh_argv(name, repo), value) == 0 else EXIT_REFUSED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("name", help="the variable to copy, e.g. SMOKE_PROBE_TOKEN")
    parser.add_argument("--repo", required=True, help="owner/repo whose Actions secret to set")
    parser.add_argument(
        "--env-file", default=".env", type=Path, help="file holding the value (default .env)"
    )
    args = parser.parse_args(argv)
    return push(args.name, args.repo, args.env_file)


if __name__ == "__main__":
    sys.exit(main())

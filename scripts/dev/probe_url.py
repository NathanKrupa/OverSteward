#!/usr/bin/env python
# ABOUTME: OUTER entrypoint — fetch a live estate URL as the steward and report what the edge served.
# ABOUTME: Thin: read the token, call the probe client, print status + title, map outcomes to exit codes.

"""See a live page the way a customer does — through Cloudflare, not around it.

    scripts/dev/with_test_env.py -- scripts/dev/probe_url.py <url> [--expect-title TEXT]

Exit codes carry meaning and must not be collapsed:

* **0** — the page answered 200 (and contained ``--expect-title`` if given).
* **1** — a measured failure: challenged, non-200, or the title was absent.
* **2** — could not look: ``STEWARD_PROBE_TOKEN`` unset, or the transport failed.
"""

from __future__ import annotations

import argparse
import sys

from oversteward.probe.client import fetch
from oversteward.probe.config import ProbeConfigError, probe_token_from_env

EXIT_OK = 0
EXIT_MEASURED_FAILURE = 1
EXIT_COULD_NOT_LOOK = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("url")
    parser.add_argument("--expect-title", default="", help="text the <title> must contain")
    args = parser.parse_args(argv)

    try:
        token = probe_token_from_env()
    except ProbeConfigError as error:
        print(f"could not look: {error}", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK
    try:
        result = fetch(args.url, token)
    except OSError as error:
        print(f"could not look: {error}", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK

    verdict = "CHALLENGED" if result.challenged else f"HTTP {result.status}"
    print(f"{verdict}  {result.url}\n  title: {result.title or '(none)'}")
    if result.challenged or result.status != 200:
        return EXIT_MEASURED_FAILURE
    if args.expect_title and args.expect_title not in result.title:
        print(f"  expected title to contain: {args.expect_title!r}")
        return EXIT_MEASURED_FAILURE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

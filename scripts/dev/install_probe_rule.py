#!/usr/bin/env python
# ABOUTME: OUTER entrypoint — install or refresh the Cloudflare skip rule that honours the steward probe.
# ABOUTME: Thin: read both tokens, call the WAF connector, print the outcome, map failures to exit codes.

"""Install a signed-header skip rule on a Cloudflare zone.

``--consumer steward`` (the default) installs the steward probe's rule from
``STEWARD_PROBE_TOKEN``; ``--consumer smoke`` installs aigranthelper's
post-promotion smoke rule from ``SMOKE_PROBE_TOKEN``, scoped to
``/foundations/*`` and holding its own token (AG#1968). Both need
``CLOUDFLARE_API_TOKEN`` (Zone → WAF → Edit; the consumer repo's ``.env``) and
the zone id — ``--zone-id`` or ``CLOUDFLARE_ZONE_ID`` (a zone id is public, so
it may sit on the command line). Chain the sanctioned runner so no token
touches a command line — the first env-file wins on conflict, so name the
consumer's first:

    scripts/dev/with_test_env.py --env-file ../aigranthelper/.env -- \\
        scripts/dev/with_test_env.py -- scripts/dev/install_probe_rule.py --zone-id <id> [--consumer smoke]

Idempotent: re-run after rotating the token.

* **0** — rule created, updated, or already current (the outcome is printed).
* **1** — Cloudflare refused or could not be read.
* **2** — a required variable is unset.
"""

from __future__ import annotations

import argparse
import sys

from oversteward.probe.config import (
    PROBE_TOKEN_VAR,
    SMOKE_TOKEN_VAR,
    ProbeConfigError,
    cloudflare_from_env,
    probe_token_from_env,
)
from oversteward.probe.waf import (
    SMOKE_PROBE,
    STEWARD_PROBE,
    CloudflareError,
    SkipRule,
    ensure_skip_rule,
)

#: Consumer name → (the rule to install, the env var holding its token).
CONSUMERS: dict[str, tuple[SkipRule, str]] = {
    "steward": (STEWARD_PROBE, PROBE_TOKEN_VAR),
    "smoke": (SMOKE_PROBE, SMOKE_TOKEN_VAR),
}

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--zone-id", default="", help="Cloudflare zone id (else CLOUDFLARE_ZONE_ID)"
    )
    parser.add_argument(
        "--consumer", choices=sorted(CONSUMERS), default="steward", help="which rule to install"
    )
    args = parser.parse_args(argv)
    rule, token_var = CONSUMERS[args.consumer]
    try:
        zone = cloudflare_from_env(args.zone_id)
        probe_token = probe_token_from_env(token_var)
    except ProbeConfigError as error:
        print(f"misconfigured: {error}", file=sys.stderr)
        return EXIT_MISCONFIGURED
    try:
        outcome = ensure_skip_rule(zone.zone_id, zone.api_token, probe_token, rule=rule)
    except (CloudflareError, OSError) as error:
        print(f"could not install: {error}", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK
    print(
        f"{outcome.action}: {args.consumer} rule {outcome.rule_id} in ruleset {outcome.ruleset_id}"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
# ABOUTME: OUTER entrypoint — install or refresh the Cloudflare skip rule that honours the steward probe.
# ABOUTME: Thin: read both tokens, call the WAF connector, print the outcome, map failures to exit codes.

"""Install the steward-probe skip rule on a Cloudflare zone.

Needs ``CLOUDFLARE_ZONE_ID`` + ``CLOUDFLARE_API_TOKEN`` (Zone → WAF → Edit; the
consumer repo's ``.env``) and ``STEWARD_PROBE_TOKEN`` (OverSteward's ``.env``).
Chain the sanctioned runner so neither value touches a command line — the
first env-file wins on conflict, so name the consumer's first:

    scripts/dev/with_test_env.py --env-file ../aigranthelper/.env -- \\
        scripts/dev/with_test_env.py -- scripts/dev/install_probe_rule.py

Idempotent: re-run after rotating ``STEWARD_PROBE_TOKEN``.

* **0** — rule created, updated, or already current (the outcome is printed).
* **1** — Cloudflare refused or could not be read.
* **2** — a required variable is unset.
"""

from __future__ import annotations

import sys

from oversteward.probe.config import ProbeConfigError, cloudflare_from_env, probe_token_from_env
from oversteward.probe.waf import CloudflareError, ensure_skip_rule

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2


def main() -> int:
    try:
        zone = cloudflare_from_env()
        probe_token = probe_token_from_env()
    except ProbeConfigError as error:
        print(f"misconfigured: {error}", file=sys.stderr)
        return EXIT_MISCONFIGURED
    try:
        outcome = ensure_skip_rule(zone.zone_id, zone.api_token, probe_token)
    except (CloudflareError, OSError) as error:
        print(f"could not install: {error}", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK
    print(f"{outcome.action}: rule {outcome.rule_id} in ruleset {outcome.ruleset_id}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

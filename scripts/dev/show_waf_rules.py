#!/usr/bin/env python
# ABOUTME: OUTER entrypoint — list a Cloudflare zone's custom-firewall and rate-limit rules with secrets redacted.
# ABOUTME: The only sanctioned way to read a ruleset: a raw API dump prints every skip rule's token.

"""List a zone's WAF custom rules and rate-limit rules, expressions redacted.

A skip rule keeps its credential inside its expression (``… eq "<token>"``),
so a raw ruleset read is a secret leak — one happened on 2026-09-07. This
reader replaces every quoted string literal with ``<redacted>`` before printing,
whatever operator compares it — ``eq``, ``==``, ``ne``, ``contains``, ``matches``, ``in``.

Needs ``CLOUDFLARE_API_TOKEN`` (the consumer repo's ``.env``, through the
sanctioned runner) and the zone id — ``--zone-id`` or ``CLOUDFLARE_ZONE_ID``:

    scripts/dev/with_test_env.py --env-file ../aigranthelper/.env -- \\
        scripts/dev/show_waf_rules.py --zone-id <id>

* **0** — printed.
* **1** — Cloudflare refused or could not be read.
* **2** — a required variable is unset.
"""

from __future__ import annotations

import argparse
import sys

from oversteward.probe.config import ProbeConfigError, cloudflare_from_env
from oversteward.probe.waf import CloudflareError, read_rules

EXIT_OK = 0
EXIT_COULD_NOT_LOOK = 1
EXIT_MISCONFIGURED = 2


def render(rules_by_phase: dict[str, list[dict]]) -> str:
    lines: list[str] = []
    for phase, rules in rules_by_phase.items():
        lines.append(f"{phase}: {len(rules)} rule(s)")
        for index, rule in enumerate(rules):
            state = "on" if rule["enabled"] else "OFF"
            lines.append(f"  {index}. [{rule['action']}] ({state}) {rule['description']}")
            lines.append(f"       {rule['expression']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--zone-id", default="", help="Cloudflare zone id (else CLOUDFLARE_ZONE_ID)"
    )
    args = parser.parse_args(argv)
    try:
        zone = cloudflare_from_env(args.zone_id)
    except ProbeConfigError as error:
        print(f"misconfigured: {error}", file=sys.stderr)
        return EXIT_MISCONFIGURED
    try:
        rules = read_rules(zone.zone_id, zone.api_token)
    except (CloudflareError, OSError) as error:
        print(f"could not read: {error}", file=sys.stderr)
        return EXIT_COULD_NOT_LOOK
    print(render(rules))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())

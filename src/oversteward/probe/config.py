# ABOUTME: The one place the probe reads its secrets from the environment.
# ABOUTME: Factories only — the client and connector take their tokens as parameters.

from __future__ import annotations

import os
from dataclasses import dataclass

PROBE_TOKEN_VAR = "STEWARD_PROBE_TOKEN"
CLOUDFLARE_TOKEN_VAR = "CLOUDFLARE_API_TOKEN"
CLOUDFLARE_ZONE_VAR = "CLOUDFLARE_ZONE_ID"


class ProbeConfigError(RuntimeError):
    """A required variable is unset — the "could not look" case, exit 2 at the edge."""


def probe_token_from_env() -> str:
    token = os.environ.get(PROBE_TOKEN_VAR, "").strip()
    if not token:
        raise ProbeConfigError(f"{PROBE_TOKEN_VAR} is unset — run through scripts/dev/with_test_env.py")
    return token


@dataclass(frozen=True)
class CloudflareZone:
    zone_id: str
    api_token: str


def cloudflare_from_env() -> CloudflareZone:
    zone_id = os.environ.get(CLOUDFLARE_ZONE_VAR, "").strip()
    api_token = os.environ.get(CLOUDFLARE_TOKEN_VAR, "").strip()
    missing = [n for n, v in ((CLOUDFLARE_ZONE_VAR, zone_id), (CLOUDFLARE_TOKEN_VAR, api_token)) if not v]
    if missing:
        raise ProbeConfigError(f"{', '.join(missing)} unset — the Cloudflare zone cannot be edited")
    return CloudflareZone(zone_id=zone_id, api_token=api_token)

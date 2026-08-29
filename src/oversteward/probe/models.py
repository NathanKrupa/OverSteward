# ABOUTME: Shapes shared by the probe client and the WAF connector — the header name and a fetch result.
# ABOUTME: Pure data; no I/O.

from __future__ import annotations

from dataclasses import dataclass

#: The request header that carries the probe token. The Cloudflare skip rule
#: matches this header's value, so a change here must be re-installed there.
PROBE_HEADER = "x-steward-probe"

#: Cloudflare stamps this response header when it served a challenge instead
#: of the page — the signal that the request was treated as unverified.
MITIGATED_HEADER = "cf-mitigated"

#: Cloudflare's cache verdict for the response (``HIT``, ``MISS``, ``DYNAMIC``,
#: ``EXPIRED`` …) — the difference between "the purge landed" and "the edge is
#: still serving the old page".
CACHE_STATUS_HEADER = "cf-cache-status"


@dataclass(frozen=True)
class ProbeResult:
    """What one live fetch saw at the edge.

    ``challenged`` is Cloudflare's own verdict (``cf-mitigated: challenge``),
    distinct from an ordinary 403 the origin might return. ``cache_status`` is
    empty when the response did not pass through Cloudflare's cache.
    """

    url: str
    status: int
    title: str
    challenged: bool
    cache_status: str = ""

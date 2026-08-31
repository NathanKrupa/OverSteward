# ABOUTME: INNER connector for a live estate page — one HTTPS fetch carrying the signed probe header.
# ABOUTME: Transport only; whether the result is acceptable is the caller's decision.

"""Fetch a live URL as the steward.

Cloudflare challenges every unverified client on the foundation tail, which is
right for scrapers and wrong for the estate's own eyes: a data repair is not
done until the public page renders it, and a purge is not verified until the
edge answers. The probe header is the sanctioned way through — a WAF skip
rule (``waf.py``) matches it, so the token never travels on a command line.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from html import unescape
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from oversteward.probe.models import (
    CACHE_STATUS_HEADER,
    MITIGATED_HEADER,
    PROBE_HEADER,
    ProbeResult,
)

_TIMEOUT_SECONDS = 30
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_USER_AGENT = "OverSteward-probe/1 (+https://github.com/NathanKrupa/OverSteward)"

Transport = Callable[[Request, int], object]


def _decode(body: bytes) -> str:
    """The response as text. Undecodable bytes are replaced, never raised on —
    a mis-encoded page is still a page the caller came to read."""
    return body.decode("utf-8", errors="replace")


def _title_of(text: str) -> str:
    match = _TITLE.search(text)
    return unescape(match.group(1)).strip() if match else ""


def fetch(url: str, token: str, *, transport: Transport = urlopen) -> ProbeResult:
    """Fetch ``url`` with the probe header and report what the edge returned.

    An HTTP error status is a *result*, not an exception — a 403 challenge or
    a 404 is exactly what the caller came to measure. Only transport failures
    (DNS, TLS, timeout) propagate.
    """
    request = Request(url, headers={PROBE_HEADER: token, "User-Agent": _USER_AGENT})  # noqa: S310 - https URLs from the operator
    try:
        response = transport(request, timeout=_TIMEOUT_SECONDS)
    except HTTPError as error:
        text = _decode(error.read() or b"")
        return ProbeResult(
            url=url,
            status=error.code,
            title=_title_of(text),
            challenged=(error.headers.get(MITIGATED_HEADER) or "").lower() == "challenge",
            cache_status=(error.headers.get(CACHE_STATUS_HEADER) or "").upper(),
            body=text,
        )
    text = _decode(response.read())
    return ProbeResult(
        url=url,
        status=response.status,
        title=_title_of(text),
        challenged=(response.getheader(MITIGATED_HEADER) or "").lower() == "challenge",
        cache_status=(response.getheader(CACHE_STATUS_HEADER) or "").upper(),
        body=text,
    )

# ABOUTME: INNER connector for the Cloudflare WAF — installs the skip rule that honours the probe header.
# ABOUTME: Idempotent: creates the rule first in the custom ruleset, updates it, or leaves it alone.

"""Keep the steward-probe skip rule installed on a zone.

The rule sits first in the ``http_request_firewall_custom`` ruleset and, when
the probe header equals the token, skips the remaining custom rules (the
managed challenge on ``/foundations/*``) and the rate-limiting phase. It is
found again by its description, so rotating the token is a re-run, not a
dashboard hunt.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from oversteward.probe.models import PROBE_HEADER

API_ROOT = "https://api.cloudflare.com/client/v4"
RULE_DESCRIPTION = "steward probe — skip challenge + rate limit for signed session checks"
_PHASE = "http_request_firewall_custom"
_TIMEOUT_SECONDS = 30

Transport = Callable[[str, str, str, dict | None], dict]


class CloudflareError(RuntimeError):
    """Cloudflare refused or could not be read. Carries the API's message, never a token."""


@dataclass(frozen=True)
class RuleOutcome:
    """What ``ensure_skip_rule`` did: ``created``, ``updated`` or ``unchanged``."""

    action: str
    rule_id: str
    ruleset_id: str


def skip_rule_expression(token: str) -> str:
    """The rule expression matching the probe header against ``token``.

    The token is embedded in a quoted string literal, so a quote or backslash
    would change the expression's meaning; ``secrets.token_urlsafe`` never
    produces one, and anything else is refused rather than escaped.
    """
    if any(ch in token for ch in '"\\') or not token:
        raise ValueError("probe token must be non-empty and contain no quote or backslash")
    return f'http.request.headers["{PROBE_HEADER}"][0] eq "{token}"'


def _http_transport(method: str, url: str, api_token: str, body: dict | None) -> dict:
    """One Cloudflare API call; the bearer token lives only in the header."""
    data = json.dumps(body).encode() if body is not None else None
    request = Request(  # noqa: S310 - fixed https API root
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
            return json.load(response)
    except HTTPError as error:
        try:
            return json.load(error)
        except ValueError:
            raise CloudflareError(f"Cloudflare answered HTTP {error.code}") from None


def _call(transport: Transport, method: str, url: str, api_token: str, body: dict | None) -> dict:
    payload = transport(method, url, api_token, body)
    if not payload.get("success"):
        messages = "; ".join(e.get("message", "?") for e in payload.get("errors", [])) or "unknown"
        raise CloudflareError(f"Cloudflare refused {method} {url.replace(API_ROOT, '')}: {messages}")
    return payload["result"]


def ensure_skip_rule(
    zone_id: str,
    api_token: str,
    probe_token: str,
    *,
    transport: Transport = _http_transport,
) -> RuleOutcome:
    """Create, update or confirm the probe skip rule on ``zone_id``."""
    expression = skip_rule_expression(probe_token)
    entrypoint = f"{API_ROOT}/zones/{zone_id}/rulesets/phases/{_PHASE}/entrypoint"
    ruleset = _call(transport, "GET", entrypoint, api_token, None)
    ruleset_id = ruleset["id"]
    rules = ruleset.get("rules", [])
    rules_url = f"{API_ROOT}/zones/{zone_id}/rulesets/{ruleset_id}/rules"

    desired = {
        "action": "skip",
        "action_parameters": {"ruleset": "current", "phases": ["http_ratelimit"]},
        "expression": expression,
        "description": RULE_DESCRIPTION,
        "enabled": True,
    }

    existing = next((r for r in rules if r.get("description") == RULE_DESCRIPTION), None)
    if existing is not None:
        if existing.get("expression") == expression and existing.get("enabled", False):
            return RuleOutcome("unchanged", existing["id"], ruleset_id)
        _call(transport, "PATCH", f"{rules_url}/{existing['id']}", api_token, desired)
        return RuleOutcome("updated", existing["id"], ruleset_id)

    if rules:
        desired["position"] = {"before": rules[0]["id"]}
    created = _call(transport, "POST", rules_url, api_token, desired)
    return RuleOutcome("created", created.get("id", ""), ruleset_id)

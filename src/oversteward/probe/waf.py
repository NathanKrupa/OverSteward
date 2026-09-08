# ABOUTME: INNER connector for the Cloudflare WAF — installs the skip rule that honours the probe header.
# ABOUTME: Idempotent: creates the rule first in the custom ruleset, updates it, or leaves it alone.

"""Keep a signed-header skip rule installed on a zone.

A skip rule sits first in the ``http_request_firewall_custom`` ruleset and,
when its header equals its token, skips the remaining custom rules (the
managed challenge on ``/foundations/*``) and the rate-limiting phase. It is
found again by its description, so rotating the token is a re-run, not a
dashboard hunt.

Two rules are known here, one per credential, because a skip is a bypass and
its reach should be the consumer's need and no wider:

* :data:`STEWARD_PROBE` — the steward's live-URL checks, zone-wide.
* :data:`SMOKE_PROBE` — aigranthelper's post-promotion smoke, whose headless
  browser is otherwise served the challenge; scoped to ``/foundations/*`` by a
  path conjunct in the expression, and holding its own token so CI never
  carries the steward's (AG#1968).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from oversteward.probe.models import PROBE_HEADER

API_ROOT = "https://api.cloudflare.com/client/v4"
RULE_DESCRIPTION = "steward probe — skip challenge + rate limit for signed session checks"
_PHASE = "http_request_firewall_custom"
_RATELIMIT_PHASE = "http_ratelimit"
_TIMEOUT_SECONDS = 30

#: Every double-quoted string literal in a rule expression. A skip rule keeps
#: its secret in one, and the Rules language compares literals with ``eq``,
#: ``==``, ``ne``, ``contains``, ``matches`` and ``in {…}`` alike, so the only
#: honest redaction is of the literal itself, whatever precedes it. Field names
#: and operators survive, as does a subscript key (``headers["x-smoke-probe"]``
#: names a header, not a secret); a path prefix or a host is redacted with the
#: rest, and the rule's description says what it is.
_QUOTED_LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"')
REDACTED = '"<redacted>"'


@dataclass(frozen=True)
class SkipRule:
    """One signed-header skip rule: the header it matches, the description it
    is found by, and the path prefix (if any) that bounds its reach."""

    header: str
    description: str
    path_prefix: str | None = None


STEWARD_PROBE = SkipRule(header=PROBE_HEADER, description=RULE_DESCRIPTION)
SMOKE_PROBE = SkipRule(
    header="x-smoke-probe",
    description="smoke probe — skip challenge + rate limit for the post-promotion smoke on /foundations/*",
    path_prefix="/foundations/",
)

Transport = Callable[[str, str, str, dict | None], dict]


class CloudflareError(RuntimeError):
    """Cloudflare refused or could not be read. Carries the API's message, never a token."""


@dataclass(frozen=True)
class RuleOutcome:
    """What ``ensure_skip_rule`` did: ``created``, ``updated`` or ``unchanged``."""

    action: str
    rule_id: str
    ruleset_id: str


def skip_rule_expression(token: str, *, rule: SkipRule = STEWARD_PROBE) -> str:
    """The rule expression matching ``rule``'s header against ``token``.

    The token is embedded in a quoted string literal, so a quote or backslash
    would change the expression's meaning; ``secrets.token_urlsafe`` never
    produces one, and anything else is refused rather than escaped. A rule
    with a path prefix is bounded to it by a leading conjunct, so the skip
    reaches no further than the pages its consumer needs.
    """
    if any(ch in token for ch in '"\\') or not token:
        raise ValueError("probe token must be non-empty and contain no quote or backslash")
    expression = f'http.request.headers["{rule.header}"][0] eq "{token}"'
    if rule.path_prefix is None:
        return expression
    if not rule.path_prefix.startswith("/") or any(ch in rule.path_prefix for ch in '"\\'):
        raise ValueError("a path prefix must start with / and contain no quote or backslash")
    return f'starts_with(http.request.uri.path, "{rule.path_prefix}") and {expression}'


def redact_expression(expression: str) -> str:
    """The expression with every quoted string literal replaced — safe to print.

    Literals are consumed left to right as whole strings, so a subscript key
    (``headers["x-smoke-probe"]``) is recognised by the ``[`` before it and
    kept; every other literal, whatever operator compares it, is replaced.
    """

    def _keep_or_redact(match: re.Match[str]) -> str:
        preceded_by_subscript = match.start() > 0 and expression[match.start() - 1] == "["
        return match.group(0) if preceded_by_subscript else REDACTED

    return _QUOTED_LITERAL.sub(_keep_or_redact, expression)


def _http_transport(method: str, url: str, api_token: str, body: dict | None) -> dict:
    """One Cloudflare API call; the bearer token lives only in the header."""
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
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
        raise CloudflareError(
            f"Cloudflare refused {method} {url.replace(API_ROOT, '')}: {messages}"
        )
    return payload["result"]


def read_rules(
    zone_id: str, api_token: str, *, transport: Transport = _http_transport
) -> dict[str, list[dict]]:
    """Every rule in the custom-firewall and rate-limit phases, expressions redacted.

    The only reader that should ever print a ruleset: a raw API dump carries
    each skip rule's token inside its expression.
    """
    out: dict[str, list[dict]] = {}
    for phase in (_PHASE, _RATELIMIT_PHASE):
        try:
            ruleset = _call(
                transport,
                "GET",
                f"{API_ROOT}/zones/{zone_id}/rulesets/phases/{phase}/entrypoint",
                api_token,
                None,
            )
        except CloudflareError as error:
            # Cloudflare has no entrypoint ruleset for a phase until a rule
            # exists in it, and answers with this wording (observed 2026-09-07
            # for http_request_firewall_managed; unverified for other phases).
            # A wrong guess at the wording fails closed — the error propagates.
            if "could not find entrypoint" in str(error):
                out[phase] = []
                continue
            raise
        out[phase] = [
            {
                "description": rule.get("description", ""),
                "action": rule.get("action", ""),
                "enabled": rule.get("enabled", False),
                "expression": redact_expression(rule.get("expression", "")),
            }
            for rule in ruleset.get("rules", [])
        ]
    return out


def ensure_skip_rule(
    zone_id: str,
    api_token: str,
    probe_token: str,
    *,
    rule: SkipRule = STEWARD_PROBE,
    transport: Transport = _http_transport,
) -> RuleOutcome:
    """Create, update or confirm ``rule`` on ``zone_id`` with ``probe_token``."""
    expression = skip_rule_expression(probe_token, rule=rule)
    entrypoint = f"{API_ROOT}/zones/{zone_id}/rulesets/phases/{_PHASE}/entrypoint"
    ruleset = _call(transport, "GET", entrypoint, api_token, None)
    ruleset_id = ruleset["id"]
    rules = ruleset.get("rules", [])
    rules_url = f"{API_ROOT}/zones/{zone_id}/rulesets/{ruleset_id}/rules"

    desired = {
        "action": "skip",
        "action_parameters": {"ruleset": "current", "phases": [_RATELIMIT_PHASE]},
        "expression": expression,
        "description": rule.description,
        "enabled": True,
    }

    existing = next((r for r in rules if r.get("description") == rule.description), None)
    if existing is not None:
        if existing.get("expression") == expression and existing.get("enabled", False):
            return RuleOutcome("unchanged", existing["id"], ruleset_id)
        _call(transport, "PATCH", f"{rules_url}/{existing['id']}", api_token, desired)
        return RuleOutcome("updated", existing["id"], ruleset_id)

    if rules:
        desired["position"] = {"before": rules[0]["id"]}
    # Cloudflare answers a rule create with the whole ruleset, not the rule.
    updated_ruleset = _call(transport, "POST", rules_url, api_token, desired)
    created = next(
        (r for r in updated_ruleset.get("rules", []) if r.get("description") == rule.description),
        {},
    )
    return RuleOutcome("created", created.get("id", ""), ruleset_id)

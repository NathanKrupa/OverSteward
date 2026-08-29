# ABOUTME: Tests the Cloudflare WAF connector that installs the steward-probe skip rule.
# ABOUTME: Fake transport records every API call; asserts create-when-absent, update-when-present, no-op.

from __future__ import annotations

import json

import pytest

from oversteward.probe.models import PROBE_HEADER
from oversteward.probe.waf import (
    RULE_DESCRIPTION,
    CloudflareError,
    ensure_skip_rule,
    skip_rule_expression,
)

_ZONE = "zone123"
_API = "cf-api-token"
_TOKEN = "probe-token"
_RULESET = "ruleset-abc"


def _entrypoint(rules: list[dict]) -> dict:
    return {"success": True, "errors": [], "result": {"id": _RULESET, "rules": rules}}


def _fake_transport(responses: list[dict]):
    """Return (transport, calls); each call pops the next canned response."""
    calls: list[tuple[str, str, dict | None]] = []

    def transport(method: str, url: str, api_token: str, body: dict | None) -> dict:
        assert api_token == _API
        calls.append((method, url, body))
        return responses.pop(0)

    return transport, calls


class TestExpression:
    def test_matches_the_probe_header_against_the_token(self):
        assert skip_rule_expression(_TOKEN) == f'http.request.headers["{PROBE_HEADER}"][0] eq "{_TOKEN}"'

    def test_a_token_with_a_quote_is_refused(self):
        with pytest.raises(ValueError):
            skip_rule_expression('a"b')


class TestEnsure:
    def test_creates_the_rule_first_when_absent(self):
        existing = [{"id": "r1", "action": "block", "description": "other"}]
        # Cloudflare answers a rule create with the whole ruleset, not the rule.
        after = _entrypoint([{"id": "new", "description": RULE_DESCRIPTION}, *existing])
        transport, calls = _fake_transport([_entrypoint(existing), after])
        outcome = ensure_skip_rule(_ZONE, _API, _TOKEN, transport=transport)

        assert outcome.action == "created"
        assert outcome.rule_id == "new"
        assert outcome.ruleset_id == _RULESET
        method, url, body = calls[1]
        assert method == "POST"
        assert url.endswith(f"/zones/{_ZONE}/rulesets/{_RULESET}/rules")
        assert body["action"] == "skip"
        assert body["action_parameters"] == {"ruleset": "current", "phases": ["http_ratelimit"]}
        assert body["expression"] == skip_rule_expression(_TOKEN)
        assert body["description"] == RULE_DESCRIPTION
        assert body["enabled"] is True
        assert body["position"] == {"before": "r1"}

    def test_creates_without_position_when_the_ruleset_is_empty(self):
        transport, calls = _fake_transport(
            [_entrypoint([]), {"success": True, "errors": [], "result": {"id": "new"}}]
        )
        ensure_skip_rule(_ZONE, _API, _TOKEN, transport=transport)
        assert "position" not in calls[1][2]

    def test_updates_the_expression_when_the_rule_exists_with_another_token(self):
        existing = [
            {"id": "probe", "action": "skip", "description": RULE_DESCRIPTION, "expression": "old"},
            {"id": "r1", "action": "block", "description": "other"},
        ]
        transport, calls = _fake_transport(
            [_entrypoint(existing), {"success": True, "errors": [], "result": {"id": "probe"}}]
        )
        outcome = ensure_skip_rule(_ZONE, _API, _TOKEN, transport=transport)

        assert outcome.action == "updated"
        method, url, body = calls[1]
        assert method == "PATCH"
        assert url.endswith(f"/rulesets/{_RULESET}/rules/probe")
        assert body["expression"] == skip_rule_expression(_TOKEN)

    def test_is_a_no_op_when_the_rule_already_matches(self):
        existing = [
            {
                "id": "probe",
                "action": "skip",
                "description": RULE_DESCRIPTION,
                "expression": skip_rule_expression(_TOKEN),
                "enabled": True,
            }
        ]
        transport, calls = _fake_transport([_entrypoint(existing)])
        outcome = ensure_skip_rule(_ZONE, _API, _TOKEN, transport=transport)
        assert outcome.action == "unchanged"
        assert len(calls) == 1

    def test_an_api_refusal_is_raised_with_its_message_and_never_the_token(self):
        transport, _ = _fake_transport(
            [{"success": False, "errors": [{"message": "Authentication error"}], "result": None}]
        )
        with pytest.raises(CloudflareError) as excinfo:
            ensure_skip_rule(_ZONE, _API, _TOKEN, transport=transport)
        assert "Authentication error" in str(excinfo.value)
        assert _TOKEN not in str(excinfo.value)
        assert _API not in str(excinfo.value)

    def test_the_body_is_json_serialisable(self):
        transport, calls = _fake_transport(
            [_entrypoint([]), {"success": True, "errors": [], "result": {"id": "new"}}]
        )
        ensure_skip_rule(_ZONE, _API, _TOKEN, transport=transport)
        json.dumps(calls[1][2])

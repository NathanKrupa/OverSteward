# ABOUTME: Tests the Cloudflare WAF connector that installs the steward-probe skip rule.
# ABOUTME: Fake transport records every API call; asserts create-when-absent, update-when-present, no-op.

from __future__ import annotations

import json

import pytest

from oversteward.probe.models import PROBE_HEADER
from oversteward.probe.waf import (
    REDACTED,
    RULE_DESCRIPTION,
    SMOKE_PROBE,
    STEWARD_PROBE,
    CloudflareError,
    SkipRule,
    ensure_skip_rule,
    read_rules,
    redact_expression,
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
        assert (
            skip_rule_expression(_TOKEN)
            == f'http.request.headers["{PROBE_HEADER}"][0] eq "{_TOKEN}"'
        )

    def test_a_token_with_a_quote_is_refused(self):
        with pytest.raises(ValueError):
            skip_rule_expression('a"b')

    def test_the_steward_rule_is_the_default_and_has_no_path_bound(self):
        assert skip_rule_expression(_TOKEN, rule=STEWARD_PROBE) == skip_rule_expression(_TOKEN)
        assert "starts_with" not in skip_rule_expression(_TOKEN)

    def test_the_smoke_rule_is_bounded_to_foundations_and_carries_its_own_header(self):
        """The smoke's bypass reaches the pages the smoke opens and no further,
        and never the steward's header — a token in CI is a token in CI."""
        expression = skip_rule_expression(_TOKEN, rule=SMOKE_PROBE)
        assert expression == (
            'starts_with(http.request.uri.path, "/foundations/") and '
            f'(http.request.headers["x-smoke-probe"][0] eq "{_TOKEN}" or http.cookie contains "smoke_probe={_TOKEN}")'
        )
        assert SMOKE_PROBE.header != STEWARD_PROBE.header
        assert SMOKE_PROBE.description != STEWARD_PROBE.description

    def test_the_smoke_rule_accepts_the_same_token_as_a_cookie(self):
        """A browser sends a cookie only to the host that set it, on every hop
        and on API requests — the reach a per-request header cannot have."""
        expression = skip_rule_expression(_TOKEN, rule=SMOKE_PROBE)
        assert f'or http.cookie contains "smoke_probe={_TOKEN}")' in expression
        assert expression.startswith('starts_with(http.request.uri.path, "/foundations/") and (')
        assert 'http.request.headers["x-smoke-probe"][0] eq' in expression

    def test_the_steward_rule_has_no_cookie_clause(self):
        assert "cookie" not in skip_rule_expression(_TOKEN, rule=STEWARD_PROBE)
        assert STEWARD_PROBE.cookie is None

    @pytest.mark.parametrize(
        "name", ['a"b', "a b", "a=b", "a;b", "смоке", "١٢", "smoke²", "ǅabc", ""]
    )
    def test_a_cookie_name_a_browser_cannot_send_is_refused(self, name):
        """Unicode letters and digits are alphanumeric to Python and unsendable
        to a browser; a rule with such a name can never match — fail-closed, but
        a rule installed to never match is a rule nobody meant."""
        with pytest.raises(ValueError, match="cookie name"):
            skip_rule_expression(
                _TOKEN, rule=SkipRule(header="x", description="d", path_prefix="/p/", cookie=name)
            )

    def test_a_hyphenated_cookie_name_is_accepted(self):
        rule = SkipRule(header="x", description="d", path_prefix="/p/", cookie="smoke-probe")
        assert f'http.cookie contains "smoke-probe={_TOKEN}"' in skip_rule_expression(
            _TOKEN, rule=rule
        )

    def test_a_cookie_without_a_path_bound_is_refused(self):
        """A zone-wide cookie bypass is a shape nothing here should install."""
        with pytest.raises(ValueError, match="path prefix"):
            skip_rule_expression(
                _TOKEN, rule=SkipRule(header="x", description="d", cookie="smoke_probe")
            )

    def test_a_path_prefix_that_is_not_a_path_is_refused(self):
        for prefix in ("foundations/", '/a"b', "/a\\b"):
            with pytest.raises(ValueError):
                skip_rule_expression(
                    _TOKEN, rule=SkipRule(header="x", description="d", path_prefix=prefix)
                )


class TestRedaction:
    def test_every_compared_literal_is_replaced(self):
        expression = (
            skip_rule_expression(_TOKEN, rule=SMOKE_PROBE) + ' or http.host eq "ab.example"'
        )
        redacted = redact_expression(expression)
        assert _TOKEN not in redacted
        assert (
            redacted.count(REDACTED) == 5
        )  # the path prefix, the header key, the token, the cookie, the host
        assert "starts_with" in redacted and "http.request.headers[" in redacted

    @pytest.mark.parametrize(
        "expression",
        [
            f'http.request.headers["x"][0] == "{_TOKEN}"',
            f'http.request.headers["x"][0] ne "{_TOKEN}"',
            f'http.request.headers["x"][0] contains "{_TOKEN}"',
            f'http.request.headers["x"][0] matches "^{_TOKEN}$"',
            f'http.request.headers["x"][0] in {{"{_TOKEN}" "other"}}',
            f'(http.host eq "h") and (http.request.uri.query contains "t={_TOKEN}")',
            f'http.cookie contains "a\\"b{_TOKEN}"',
        ],
        ids=["==", "ne", "contains", "matches", "in", "nested", "escaped-quote"],
    )
    def test_a_literal_is_redacted_whatever_operator_compares_it(self, expression):
        """The Rules language has more than ``eq``, and the zone holds rules this
        installer did not write; the redaction is of the literal, not the operator."""
        redacted = redact_expression(expression)
        assert _TOKEN not in redacted, redacted
        assert REDACTED in redacted

    def test_a_refusal_that_echoes_the_expression_is_raised_redacted(self):
        """A rule create can be refused with the submitted expression quoted back;
        the installer prints the message to stderr, which is the transcript."""
        expression = skip_rule_expression(_TOKEN, rule=SMOKE_PROBE)
        transport, _ = _fake_transport(
            [
                _entrypoint([]),
                {
                    "success": False,
                    "errors": [{"message": f"expression is not valid: {expression}"}],
                    "result": None,
                },
            ]
        )
        with pytest.raises(CloudflareError) as raised:
            ensure_skip_rule(_ZONE, _API, _TOKEN, rule=SMOKE_PROBE, transport=transport)
        assert _TOKEN not in str(raised.value)
        assert "expression is not valid" in str(raised.value) and REDACTED in str(raised.value)

    def test_read_rules_never_returns_a_token(self):
        transport, calls = _fake_transport(
            [
                _entrypoint(
                    [
                        {
                            "id": "r1",
                            "description": "d",
                            "action": "skip",
                            "enabled": True,
                            "expression": skip_rule_expression(_TOKEN),
                        }
                    ]
                ),
                {
                    "success": True,
                    "errors": [],
                    "result": {
                        "id": "rl",
                        "rules": [
                            {
                                "id": "r2",
                                "description": "rate",
                                "action": "block",
                                "enabled": True,
                                "expression": '(http.request.uri.path contains "/foundations/")',
                            }
                        ],
                    },
                },
            ]
        )
        rules = read_rules(_ZONE, _API, transport=transport)
        assert _TOKEN not in json.dumps(rules)
        assert rules["http_request_firewall_custom"][0]["expression"].endswith(REDACTED)
        assert rules["http_ratelimit"][0]["action"] == "block"
        assert [method for method, _, _ in calls] == ["GET", "GET"]

    def test_read_rules_treats_a_missing_ratelimit_entrypoint_as_empty(self):
        transport, _ = _fake_transport(
            [
                _entrypoint([]),
                {
                    "success": False,
                    "errors": [
                        {"message": "could not find entrypoint ruleset in the http_ratelimit phase"}
                    ],
                    "result": None,
                },
            ]
        )
        assert read_rules(_ZONE, _API, transport=transport)["http_ratelimit"] == []


class TestEnsure:
    def test_the_smoke_rule_is_created_by_its_own_description_beside_the_stewards(self):
        steward = {
            "id": "r-steward",
            "description": RULE_DESCRIPTION,
            "expression": skip_rule_expression("other"),
            "enabled": True,
        }
        transport, calls = _fake_transport(
            [
                _entrypoint([steward]),
                _entrypoint([{"id": "r-smoke", "description": SMOKE_PROBE.description}, steward]),
            ]
        )
        outcome = ensure_skip_rule(_ZONE, _API, _TOKEN, rule=SMOKE_PROBE, transport=transport)
        assert outcome.action == "created" and outcome.rule_id == "r-smoke"
        method, _, body = calls[1]
        assert method == "POST"
        assert body["description"] == SMOKE_PROBE.description
        assert body["expression"].startswith('starts_with(http.request.uri.path, "/foundations/")')
        assert body["position"] == {"before": "r-steward"}

    def test_the_smoke_rule_never_touches_the_stewards(self):
        """Same token, same zone: the steward's rule is neither updated nor
        matched, because the rules are found by description."""
        steward = {
            "id": "r-steward",
            "description": RULE_DESCRIPTION,
            "expression": skip_rule_expression(_TOKEN),
            "enabled": True,
        }
        smoke = {
            "id": "r-smoke",
            "description": SMOKE_PROBE.description,
            "expression": "stale",
            "enabled": True,
        }
        transport, calls = _fake_transport(
            [_entrypoint([smoke, steward]), {"success": True, "errors": [], "result": {}}]
        )
        outcome = ensure_skip_rule(_ZONE, _API, _TOKEN, rule=SMOKE_PROBE, transport=transport)
        assert outcome.action == "updated" and outcome.rule_id == "r-smoke"
        assert calls[1][1].endswith("/rules/r-smoke")

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

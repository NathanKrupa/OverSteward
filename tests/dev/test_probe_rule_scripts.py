# ABOUTME: Tests for the three probe-credential scripts — the redacting ruleset reader, the stdin-fed
# ABOUTME: Actions-secret pusher, and the in-place .env minter — each asserted never to print a value.

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

_DEV = Path(__file__).resolve().parents[2] / "scripts" / "dev"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _DEV / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


show = _load("show_waf_rules")
push = _load("push_actions_secret")
mint = _load("mint_env_secret")
install = _load("install_probe_rule")


class TestShowWafRules:
    def test_render_lists_every_phase_and_rule_and_carries_no_literal(self):
        text = show.render(
            {
                "http_request_firewall_custom": [
                    {
                        "description": "smoke probe",
                        "action": "skip",
                        "enabled": True,
                        "expression": 'x eq "<redacted>"',
                    },
                    {
                        "description": "challenge",
                        "action": "managed_challenge",
                        "enabled": False,
                        "expression": 'starts_with(p, "/f/")',
                    },
                ],
                "http_ratelimit": [],
            }
        )
        assert (
            "http_request_firewall_custom: 2 rule(s)" in text
            and "http_ratelimit: 0 rule(s)" in text
        )
        assert "[skip] (on) smoke probe" in text and "[managed_challenge] (OFF) challenge" in text
        assert "<redacted>" in text

    def test_misconfigured_exits_2(self, monkeypatch):
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        monkeypatch.delenv("CLOUDFLARE_ZONE_ID", raising=False)
        assert show.main([]) == 2


class TestPushActionsSecret:
    def test_the_value_travels_on_stdin_and_never_in_argv(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("OTHER=1\nSMOKE_PROBE_TOKEN='tok-123'\n")
        seen: dict[str, object] = {}

        def runner(argv, stdin):
            seen["argv"], seen["stdin"] = argv, stdin
            return 0

        assert push.push("SMOKE_PROBE_TOKEN", "o/r", env, runner=runner) == 0
        assert seen["argv"] == ["gh", "secret", "set", "SMOKE_PROBE_TOKEN", "--repo", "o/r"]
        assert seen["stdin"] == "tok-123"
        assert "tok-123" not in " ".join(seen["argv"])

    def test_only_the_named_key_is_read(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("A=1\nSMOKE_PROBE_TOKEN=first\nSMOKE_PROBE_TOKEN=last\n")
        assert push.read_env_value(env, "SMOKE_PROBE_TOKEN") == "last"
        assert push.read_env_value(env, "MISSING") == ""

    def test_a_blank_value_exits_2_and_never_calls_gh(self, tmp_path, capsys):
        env = tmp_path / ".env"
        env.write_text("SMOKE_PROBE_TOKEN=\n")
        called = []
        assert (
            push.push("SMOKE_PROBE_TOKEN", "o/r", env, runner=lambda a, s: called.append(1) or 0)
            == 2
        )
        assert called == []
        assert "unset or blank" in capsys.readouterr().err

    def test_a_gh_refusal_exits_1(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("SMOKE_PROBE_TOKEN=tok\n")
        assert push.push("SMOKE_PROBE_TOKEN", "o/r", env, runner=lambda a, s: 1) == 1


class TestMintEnvSecret:
    def test_replaces_an_existing_line_in_place(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("A=1\nSMOKE_PROBE_TOKEN=old\nB=2\n")
        assert mint.mint_into(env, "SMOKE_PROBE_TOKEN", token="new") == "replaced"
        assert env.read_text() == "A=1\nSMOKE_PROBE_TOKEN=new\nB=2\n"

    def test_appends_when_absent(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("A=1\n")
        assert mint.mint_into(env, "SMOKE_PROBE_TOKEN", token="new") == "appended"
        assert env.read_text().endswith("SMOKE_PROBE_TOKEN=new\n")

    def test_a_minted_token_is_url_safe_and_never_printed(self, tmp_path, capsys):
        env = tmp_path / ".env"
        assert mint.main(["SMOKE_PROBE_TOKEN", "--env-file", str(env)]) == 0
        value = push.read_env_value(env, "SMOKE_PROBE_TOKEN")
        assert len(value) >= 40 and not any(ch in value for ch in '"\\')
        out = capsys.readouterr().out
        assert value not in out and "value never printed" in out


class TestInstallerConsumers:
    def test_each_consumer_names_its_own_rule_and_token(self):
        steward_rule, steward_var = install.CONSUMERS["steward"]
        smoke_rule, smoke_var = install.CONSUMERS["smoke"]
        assert steward_var == "STEWARD_PROBE_TOKEN" and smoke_var == "SMOKE_PROBE_TOKEN"
        assert steward_rule.header == "x-steward-probe" and smoke_rule.header == "x-smoke-probe"
        assert smoke_rule.path_prefix == "/foundations/" and steward_rule.path_prefix is None

    def test_an_unknown_consumer_is_refused_by_argparse(self):
        with pytest.raises(SystemExit):
            install.main(["--consumer", "other"])

    def test_missing_smoke_token_exits_2(self, monkeypatch):
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
        monkeypatch.setenv("CLOUDFLARE_ZONE_ID", "z")
        monkeypatch.delenv("SMOKE_PROBE_TOKEN", raising=False)
        monkeypatch.setattr(sys, "stderr", io.StringIO())
        assert install.main(["--consumer", "smoke"]) == 2

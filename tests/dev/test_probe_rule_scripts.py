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
    def test_reads_the_value_exactly_as_the_sanctioned_runner_does(self, tmp_path):
        """One parser for both holders: an inline comment, an export prefix and
        quotes are handled as with_test_env.py handles them, so the WAF and CI
        receive the same bytes."""
        env = tmp_path / ".env"
        env.write_text('export SMOKE_PROBE_TOKEN="abc 123"   # rotated 2026-09-07\n')
        assert push.read_env_value(env, "SMOKE_PROBE_TOKEN") == "abc 123"
        env.write_text("SMOKE_PROBE_TOKEN=abc123   # rotated 2026-09-07\n")
        assert push.read_env_value(env, "SMOKE_PROBE_TOKEN") == "abc123"

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
    def test_every_previous_assignment_goes_including_exported_ones(self, tmp_path):
        """A rotation that leaves the old token in the file has not rotated."""
        env = tmp_path / ".env"
        env.write_text("export SMOKE_PROBE_TOKEN=old1\nA=1\nSMOKE_PROBE_TOKEN=old2\n")
        assert mint.mint_into(env, "SMOKE_PROBE_TOKEN", token="new") == "replaced"
        text = env.read_text()
        assert text == "SMOKE_PROBE_TOKEN=new\nA=1\n"
        assert "old" not in text

    def test_a_new_file_is_private_and_an_existing_mode_is_kept(self, tmp_path):
        env = tmp_path / ".env"
        mint.mint_into(env, "SMOKE_PROBE_TOKEN", token="new")
        assert env.stat().st_mode & 0o777 == 0o600
        env.chmod(0o640)
        mint.mint_into(env, "SMOKE_PROBE_TOKEN", token="newer")
        assert env.stat().st_mode & 0o777 == 0o640

    def test_an_interrupted_mint_leaves_the_original_whole_and_no_stray_secret(
        self, tmp_path, monkeypatch
    ):
        env = tmp_path / ".env"
        env.write_text("KEEP=1\n")

        def boom(src, dst):
            raise OSError("disk full at the worst moment")

        monkeypatch.setattr(mint.os, "replace", boom)
        with pytest.raises(OSError):
            mint.mint_into(env, "SMOKE_PROBE_TOKEN", token="fresh-secret")
        assert env.read_text() == "KEEP=1\n"
        assert [p.name for p in tmp_path.iterdir()] == [".env"], (
            "a temporary holding the fresh secret was left behind"
        )

    def test_the_temporary_name_is_covered_by_the_env_ignore_pattern(self, tmp_path, monkeypatch):
        """``*.env`` in .gitignore must cover the sibling, so an interruption can
        never stage the fresh secret."""
        env = tmp_path / ".env"
        seen = {}
        real_replace = mint.os.replace

        def spy(src, dst):
            seen["src"] = Path(src)
            real_replace(src, dst)

        monkeypatch.setattr(mint.os, "replace", spy)
        mint.mint_into(env, "SMOKE_PROBE_TOKEN", token="new")
        assert seen["src"].name.endswith(".env") and seen["src"].name != ".env"

    def test_the_write_is_atomic_and_leaves_no_temporary(self, tmp_path, monkeypatch):
        """The credential file is replaced by rename, never truncated in place:
        an interrupted mint leaves the old file whole."""
        env = tmp_path / ".env"
        env.write_text("KEEP=1\n")
        real_replace = mint.os.replace
        seen = {}

        def spy(src, dst):
            seen["src"], seen["dst"] = Path(src), Path(dst)
            assert env.read_text() == "KEEP=1\n", "the original was touched before the rename"
            real_replace(src, dst)

        monkeypatch.setattr(mint.os, "replace", spy)
        mint.mint_into(env, "SMOKE_PROBE_TOKEN", token="new")
        assert seen["dst"] == env and seen["src"].parent == tmp_path and seen["src"] != env
        assert not seen["src"].exists()
        assert [p.name for p in tmp_path.iterdir()] == [".env"]

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

    def test_missing_smoke_token_exits_2_even_when_the_stewards_is_set(self, monkeypatch):
        """No fallback: the smoke's rule must never be installed with the steward's token."""
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "t")
        monkeypatch.setenv("CLOUDFLARE_ZONE_ID", "z")
        monkeypatch.setenv("STEWARD_PROBE_TOKEN", "steward-secret")
        monkeypatch.delenv("SMOKE_PROBE_TOKEN", raising=False)
        monkeypatch.setattr(sys, "stderr", io.StringIO())
        called = []
        monkeypatch.setattr(install, "ensure_skip_rule", lambda *a, **k: called.append((a, k)))
        assert install.main(["--consumer", "smoke"]) == 2
        assert called == []

    @pytest.mark.parametrize("consumer", ["steward", "smoke"])
    def test_each_consumer_installs_its_own_rule_with_its_own_token(self, monkeypatch, consumer):
        """The success path, end to end: this rule, this token, this zone."""
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-token")
        monkeypatch.setenv("CLOUDFLARE_ZONE_ID", "zone-1")
        monkeypatch.setenv("STEWARD_PROBE_TOKEN", "steward-secret")
        monkeypatch.setenv("SMOKE_PROBE_TOKEN", "smoke-secret")
        seen = {}

        def fake_ensure(zone_id, api_token, probe_token, *, rule):
            seen.update(zone=zone_id, api=api_token, token=probe_token, rule=rule)
            return _Outcome()

        monkeypatch.setattr(install, "ensure_skip_rule", fake_ensure)
        assert install.main(["--consumer", consumer]) == 0
        rule, _var = install.CONSUMERS[consumer]
        assert seen["rule"] is rule and seen["zone"] == "zone-1" and seen["api"] == "cf-token"
        assert seen["token"] == {"steward": "steward-secret", "smoke": "smoke-secret"}[consumer]


class _Outcome:
    action, rule_id, ruleset_id = "created", "r1", "rs1"

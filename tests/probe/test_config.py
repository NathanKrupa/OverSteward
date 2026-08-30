# ABOUTME: Tests the probe's env factories — the only place its secrets are read.
# ABOUTME: A missing variable is a ProbeConfigError naming the variable, never a silent default.

from __future__ import annotations

import pytest

from oversteward.probe.config import (
    CLOUDFLARE_TOKEN_VAR,
    CLOUDFLARE_ZONE_VAR,
    PROBE_TOKEN_VAR,
    ProbeConfigError,
    cloudflare_from_env,
    probe_token_from_env,
)


class TestProbeToken:
    def test_reads_the_variable(self, monkeypatch):
        monkeypatch.setenv(PROBE_TOKEN_VAR, " tok ")
        assert probe_token_from_env() == "tok"

    def test_unset_is_a_config_error_naming_the_variable(self, monkeypatch):
        monkeypatch.delenv(PROBE_TOKEN_VAR, raising=False)
        with pytest.raises(ProbeConfigError, match=PROBE_TOKEN_VAR):
            probe_token_from_env()


class TestCloudflare:
    def test_zone_argument_wins_over_the_environment(self, monkeypatch):
        monkeypatch.setenv(CLOUDFLARE_ZONE_VAR, "env-zone")
        monkeypatch.setenv(CLOUDFLARE_TOKEN_VAR, "api")
        assert cloudflare_from_env("arg-zone").zone_id == "arg-zone"

    def test_zone_falls_back_to_the_environment(self, monkeypatch):
        monkeypatch.setenv(CLOUDFLARE_ZONE_VAR, "env-zone")
        monkeypatch.setenv(CLOUDFLARE_TOKEN_VAR, "api")
        assert cloudflare_from_env().zone_id == "env-zone"

    def test_missing_pieces_are_named(self, monkeypatch):
        monkeypatch.delenv(CLOUDFLARE_ZONE_VAR, raising=False)
        monkeypatch.delenv(CLOUDFLARE_TOKEN_VAR, raising=False)
        with pytest.raises(ProbeConfigError) as excinfo:
            cloudflare_from_env()
        assert CLOUDFLARE_ZONE_VAR in str(excinfo.value)
        assert CLOUDFLARE_TOKEN_VAR in str(excinfo.value)

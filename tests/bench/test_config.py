# ABOUTME: Tests for the bench's credential factory — the one place that reads the environment.
# ABOUTME: Missing token or account id is the "not configured to look" case; the token never reprs.

from __future__ import annotations

import pytest

from oversteward.bench.config import (
    ACCOUNT_VAR,
    DEFAULT_PROJECT,
    PROJECT_VAR,
    TOKEN_VAR,
    BenchConfigError,
    credentials_from_env,
)

FULL = {TOKEN_VAR: "tok-secret", ACCOUNT_VAR: "acct-1"}


class TestCredentialsFromEnv:
    def test_reads_token_account_and_the_default_project(self, tmp_path):
        creds = credentials_from_env(FULL, dotenv_path=tmp_path / "absent")
        assert (creds.token, creds.account_id, creds.project) == ("tok-secret", "acct-1", DEFAULT_PROJECT)

    def test_the_project_can_be_overridden(self, tmp_path):
        creds = credentials_from_env({**FULL, PROJECT_VAR: "other"}, dotenv_path=tmp_path / "absent")
        assert creds.project == "other"

    @pytest.mark.parametrize("missing", [TOKEN_VAR, ACCOUNT_VAR])
    def test_a_missing_variable_is_a_config_error_naming_it(self, missing, tmp_path):
        env = {key: value for key, value in FULL.items() if key != missing}
        with pytest.raises(BenchConfigError, match=missing):
            credentials_from_env(env, dotenv_path=tmp_path / "absent")

    def test_an_empty_variable_counts_as_missing(self, tmp_path):
        with pytest.raises(BenchConfigError, match=TOKEN_VAR):
            credentials_from_env({**FULL, TOKEN_VAR: ""}, dotenv_path=tmp_path / "absent")

    def test_the_repo_root_dotenv_is_the_fallback_and_the_environment_wins(self, tmp_path):
        dotenv = tmp_path / ".env"
        dotenv.write_text(f"{TOKEN_VAR}=from-file\n{ACCOUNT_VAR}=acct-file\n", encoding="utf-8")
        assert credentials_from_env({}, dotenv_path=dotenv).token == "from-file"
        assert credentials_from_env({TOKEN_VAR: "exported"}, dotenv_path=dotenv).token == "exported"

    def test_the_token_never_appears_in_the_repr(self, tmp_path):
        creds = credentials_from_env(FULL, dotenv_path=tmp_path / "absent")
        assert "tok-secret" not in repr(creds)
        assert "tok-secret" not in str(creds)

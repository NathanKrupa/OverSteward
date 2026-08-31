# ABOUTME: Tests the one place the judge reads the environment (ARCH-020).
# ABOUTME: Exported wins over .env; an absent key is "not configured", never a default.

from __future__ import annotations

import pytest

from oversteward.judge.config import (
    FALLBACK_KEY_VAR,
    GEMINI_KEY_VAR,
    JudgeConfigError,
    judge_from_env,
    resolve_api_key,
)


class TestResolveApiKey:
    def test_the_exported_key_is_used(self, tmp_path):
        assert resolve_api_key({GEMINI_KEY_VAR: "exported"}, tmp_path / "absent.env") == "exported"

    def test_google_api_key_is_the_documented_fallback(self, tmp_path):
        assert resolve_api_key({FALLBACK_KEY_VAR: "google"}, tmp_path / "absent.env") == "google"

    def test_exported_wins_over_dotenv(self, tmp_path):
        dotenv = tmp_path / ".env"
        dotenv.write_text(f"{GEMINI_KEY_VAR}=from-file\n", encoding="utf-8")
        assert resolve_api_key({GEMINI_KEY_VAR: "exported"}, dotenv) == "exported"

    def test_dotenv_is_the_fallback_when_nothing_is_exported(self, tmp_path):
        dotenv = tmp_path / ".env"
        dotenv.write_text(f"{GEMINI_KEY_VAR}=from-file\n", encoding="utf-8")
        assert resolve_api_key({}, dotenv) == "from-file"

    def test_a_missing_key_names_the_variable_it_wanted(self, tmp_path):
        with pytest.raises(JudgeConfigError, match=GEMINI_KEY_VAR):
            resolve_api_key({}, tmp_path / "absent.env")


class TestFactory:
    def test_the_factory_refuses_without_a_key(self, tmp_path):
        with pytest.raises(JudgeConfigError):
            judge_from_env({}, tmp_path / "absent.env")

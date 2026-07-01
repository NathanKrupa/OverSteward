# ABOUTME: Tests for the reader's env factory — the only piece testable without a DB driver.
# ABOUTME: The live read_corpus_funnel path is exercised by the operator, not in CI (no DB).

from __future__ import annotations

import pytest

from oversteward.vintner.reader import (
    RESEARCH_DSN_ENV,
    VintnerConfigError,
    research_dsn,
)


def test_research_dsn_reads_injected_env():
    dsn = research_dsn({RESEARCH_DSN_ENV: "postgresql://x"})
    assert dsn == "postgresql://x"


def test_research_dsn_raises_when_unset():
    with pytest.raises(VintnerConfigError):
        research_dsn({})


def test_research_dsn_raises_when_empty():
    with pytest.raises(VintnerConfigError):
        research_dsn({RESEARCH_DSN_ENV: ""})


def _write_dotenv(tmp_path, value):
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{RESEARCH_DSN_ENV}={value}\n")
    return dotenv


def test_research_dsn_falls_back_to_dotenv_when_unexported(tmp_path):
    dotenv = _write_dotenv(tmp_path, "postgresql://from-dotenv")
    dsn = research_dsn({}, dotenv_path=dotenv)
    assert dsn == "postgresql://from-dotenv"


def test_research_dsn_exported_wins_over_dotenv(tmp_path):
    dotenv = _write_dotenv(tmp_path, "postgresql://from-dotenv")
    dsn = research_dsn({RESEARCH_DSN_ENV: "postgresql://exported"}, dotenv_path=dotenv)
    assert dsn == "postgresql://exported"


def test_research_dsn_raises_when_absent_from_env_and_dotenv(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("SOMETHING_ELSE=x\n")
    with pytest.raises(VintnerConfigError):
        research_dsn({}, dotenv_path=dotenv)

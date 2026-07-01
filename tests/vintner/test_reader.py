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

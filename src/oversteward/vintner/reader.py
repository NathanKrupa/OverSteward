# ABOUTME: Read-only adapter for vintner.corpus_funnel_v via the vintner_reader role (view-only, no base tables).
# ABOUTME: INNER layer — one external system (GS neondb). Connection URL injected; only the factory reads env.

from __future__ import annotations

import os

from .models import StageRow

FUNNEL_QUERY = (
    "SELECT stage_order, stage, count, newest_at "
    "FROM vintner.corpus_funnel_v "
    "ORDER BY stage_order"
)

RESEARCH_DSN_ENV = "VINTNER_RESEARCH_DATABASE_URL"


class VintnerConfigError(RuntimeError):
    """Raised when the vintner_reader connection string is not configured."""


def read_corpus_funnel(dsn: str) -> list[StageRow]:
    """Read the corpus-funnel view. Connection string is injected, never read here.

    Imports psycopg lazily so the pure-logic spine and its tests never require
    a DB driver; the driver is only needed on the live read path.
    """
    import psycopg  # noqa: PLC0415 — lazy so pure-logic path needs no driver

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(FUNNEL_QUERY)
        rows = cur.fetchall()

    return [
        StageRow(
            stage_order=int(r[0]),
            stage=str(r[1]),
            count=int(r[2] or 0),
            newest_at=r[3],
        )
        for r in rows
    ]


def research_dsn(env: dict[str, str] | None = None) -> str:
    """Factory: read the vintner_reader research DSN from the environment.

    This is the only place that touches os.environ (ARCH-020). Raises a clear
    error when unset so the operator gets a useful message, not a stack trace.
    """
    source = env if env is not None else os.environ
    dsn = source.get(RESEARCH_DSN_ENV)
    if not dsn:
        raise VintnerConfigError(
            f"{RESEARCH_DSN_ENV} is not set — the /pipeline-status read needs the "
            "vintner_reader connection string (view-only, GS neondb)."
        )
    return dsn

# ABOUTME: Data shapes for the Vintner corpus-funnel report — raw view rows and computed per-stage results.
# ABOUTME: Plain frozen dataclasses; no DB, no LLM. Shared by the pure-logic funnel service and the reader adapter.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class StageState(str, Enum):
    """Running-vs-stopped verdict derived from a stage's freshness stamp."""

    RUNNING = "running"
    STALE = "stale"
    STOPPED = "stopped"
    EMPTY = "empty"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StageRow:
    """One raw row of ``vintner.corpus_funnel_v`` as read from the view."""

    stage_order: int
    stage: str
    count: int
    newest_at: datetime | None


@dataclass(frozen=True)
class StageReport:
    """A funnel stage after coverage / velocity / freshness interpretation."""

    stage_order: int
    stage: str
    count: int
    newest_at: datetime | None
    parent: str | None
    coverage_pct: float | None
    delta: int | None
    age_hours: float | None
    state: StageState
    ag_visible: bool


@dataclass(frozen=True)
class FunnelReport:
    """The full computed report: per-stage results plus a one-glance verdict."""

    generated_at: datetime
    stages: tuple[StageReport, ...]
    has_velocity: bool
    verdict: str

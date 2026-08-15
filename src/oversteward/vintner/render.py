# ABOUTME: Renders a FunnelReport as a scannable Chestertron-format funnel table for /pipeline-status.
# ABOUTME: Pure formatting — takes a computed report, returns markdown text. No DB, no LLM.

from __future__ import annotations

from .models import FunnelReport, StageReport, StageState

_STATE_GLYPH = {
    StageState.RUNNING: "running",
    StageState.STALE: "STALE",
    StageState.STOPPED: "STOPPED",
    StageState.EMPTY: "empty",
    StageState.UNKNOWN: "n/a",
}


def _fmt_count(n: int) -> str:
    return f"{n:,}"


def _fmt_coverage(pct: float | None) -> str:
    if pct is None:
        return "—"
    return f"{pct:.1f}%"


def _fmt_delta(delta: int | None) -> str:
    if delta is None:
        return "—"
    if delta > 0:
        return f"+{delta:,}"
    if delta < 0:
        return f"{delta:,}"
    return "0"


def _fmt_age(age_hours: float | None) -> str:
    if age_hours is None:
        return "—"
    if age_hours < 48:
        return f"{age_hours:.0f}h"
    return f"{age_hours / 24:.0f}d"


def _fmt_ag(row: StageReport) -> str:
    return "yes" if row.ag_visible else "INVISIBLE"


def _table_lines(report: FunnelReport) -> list[str]:
    lines = [
        "| Stage | Count | Coverage | Δ since last | Freshness | State | AG-visible |",
        "|---|---:|---:|---:|---:|:---:|:---:|",
    ]
    for r in report.stages:
        parent_note = f"<br><sub>of {r.parent}</sub>" if r.parent else ""
        cells = [
            f"{r.stage}{parent_note}",
            _fmt_count(r.count),
            _fmt_coverage(r.coverage_pct),
            _fmt_delta(r.delta),
            _fmt_age(r.age_hours),
            _STATE_GLYPH[r.state],
            _fmt_ag(r),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _footer_lines(report: FunnelReport) -> list[str]:
    lines: list[str] = []
    invisible = [r.stage for r in report.stages if not r.ag_visible]
    if invisible:
        lines.append(
            "**AG-visible gap:** only foundations/grants reach the AG matchmaker. "
            "Structurally invisible to AG: " + ", ".join(invisible) + "."
        )
        lines.append("")
    lines.append(
        f"_Generated {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')} · "
        "read-only via vintner_reader · deterministic, zero LLM._"
    )
    return lines


def render(report: FunnelReport) -> str:
    """Render the report as a markdown funnel table with a top-line verdict."""
    lines = [
        "# Pipeline status — corpus & enrichment funnel",
        "",
        f"**Verdict:** {report.verdict}",
        "",
    ]
    if not report.has_velocity:
        lines += ["_First run — velocity (Δ) appears on the next run._", ""]
    lines += _table_lines(report)
    lines.append("")
    lines += _footer_lines(report)
    return "\n".join(lines) + "\n"

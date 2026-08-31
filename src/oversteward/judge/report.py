# ABOUTME: Renders a judged manifest two ways — markdown for a human, JSON for the next run.
# ABOUTME: Pure formatting; the caller owns where the bytes land.

"""Turn a report into the two artifacts an operator wants.

The markdown is what gets read; the JSON is what a second round is compared
against. Both always carry the spend, because a quality verdict whose cost is
not on the page is a verdict nobody can budget the next round from.
"""

from __future__ import annotations

from oversteward.judge.models import DIMENSIONS, Usage
from oversteward.judge.service import CompareReport, ScoreReport

#: Markdown table punctuation, named once so a column change is one edit.
_CELL = " | "
_ROW = "|" + _CELL
_END = _CELL.rstrip() + "|"

_SCORE_HEADER = f"{_ROW}URL{_CELL}" + _CELL.join(DIMENSIONS) + f"{_CELL}mean{_END}"
_SCORE_DIVIDER = "| --- |" + " --- |" * (len(DIMENSIONS) + 1)


def score_json(report: ScoreReport) -> dict:
    """The machine-readable score report."""
    return {
        "name": report.name,
        "kind": "score",
        "pages": [
            {
                "url": scored.page.url,
                "page_type": scored.page_type,
                "title": scored.page.title,
                "mean": round(scored.score.mean, 2),
                "scores": {
                    name: {"score": dimension.score, "reason": dimension.reason}
                    for name, dimension in scored.score.dimensions.items()
                },
            }
            for scored in report.pages
        ],
        "usage": _usage_json(report.usage),
    }


def compare_json(report: CompareReport) -> dict:
    """The machine-readable pairwise report."""
    return {
        "name": report.name,
        "kind": "compare",
        "tallies": [
            {
                "a": tally.a,
                "b": tally.b,
                "a_wins": tally.a_wins,
                "b_wins": tally.b_wins,
                "ties": tally.ties,
                "samples": tally.samples,
            }
            for tally in report.tallies
        ],
        "usage": _usage_json(report.usage),
    }


def score_markdown(report: ScoreReport) -> str:
    """One table per page type, then every reason, then the spend."""
    lines = [f"# Page judge — {report.name}", "", "Scored 1-5, higher is better on every dimension.", ""]
    for page_type in dict.fromkeys(scored.page_type for scored in report.pages):
        lines += [f"## {page_type}", "", _SCORE_HEADER, _SCORE_DIVIDER]
        for scored in (s for s in report.pages if s.page_type == page_type):
            cells = _CELL.join(str(scored.score.dimensions[name].score) for name in DIMENSIONS)
            lines.append(
                f"{_ROW}{scored.page.url}{_CELL}{cells}{_CELL}{scored.score.mean:.1f}{_END}"
            )
        lines.append("")
        lines += _reason_lines(report, page_type)
    lines += _spend_lines(report.usage)
    return "\n".join(lines) + "\n"


def compare_markdown(report: CompareReport) -> str:
    """The tally table — every pair judged in both orders, so a sweep means something."""
    lines = [
        f"# Page judge — {report.name} (pairwise)",
        "",
        "Each pair was judged in both orders and the swapped verdict mapped back, "
        "so an even split is what position bias looks like.",
        "",
        _ROW + _CELL.join(("A", "B", "A wins", "B wins", "ties", "judgements")) + _END,
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for tally in report.tallies:
        cells = _CELL.join(
            str(value)
            for value in (tally.a, tally.b, tally.a_wins, tally.b_wins, tally.ties, tally.samples)
        )
        lines.append(f"{_ROW}{cells}{_END}")
    lines.append("")
    lines += _spend_lines(report.usage)
    return "\n".join(lines) + "\n"


def _reason_lines(report: ScoreReport, page_type: str) -> list[str]:
    lines: list[str] = []
    for scored in (s for s in report.pages if s.page_type == page_type):
        lines += [f"### {scored.page.title or scored.page.url}", "", f"<{scored.page.url}>", ""]
        for name, dimension in scored.score.dimensions.items():
            lines.append(f"- **{name}** {dimension.score}/5 — {dimension.reason}")
        lines.append("")
    return lines


def _spend_lines(usage: Usage) -> list[str]:
    return [
        "## Spend",
        "",
        f"- prompt tokens: {usage.prompt_tokens:,}",
        f"- output tokens: {usage.output_tokens:,}",
        f"- total: ${usage.cost_usd:.4f}",
    ]


def _usage_json(usage: Usage) -> dict:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": usage.cost_usd,
    }


__all__ = ["compare_json", "compare_markdown", "score_json", "score_markdown"]

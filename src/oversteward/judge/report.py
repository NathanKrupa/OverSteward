# ABOUTME: Renders a judged manifest two ways — markdown for a human, JSON for the next run.
# ABOUTME: Pure formatting; the caller owns where the bytes land.

"""Turn a report into the two artifacts an operator wants.

The markdown is what gets read; the JSON is what a second round is compared
against. Both always carry the spend, because a quality verdict whose cost is
not on the page is a verdict nobody can budget the next round from.
"""

from __future__ import annotations

from oversteward.judge.models import (
    GROUNDEDNESS,
    CompareTally,
    Rubric,
    SideGroundedness,
    Usage,
)
from oversteward.judge.service import CompareReport, ScoredPage, ScoreReport

#: Markdown table punctuation, named once so a column change is one edit.
_CELL = " | "
_ROW = "|" + _CELL
_END = _CELL.rstrip() + "|"

#: A page in a grounded table that carries no ground truth of its own.
_UNSCORED = "—"


def score_json(report: ScoreReport) -> dict:
    """The machine-readable score report."""
    return {
        "name": report.name,
        "kind": "score",
        "rubric": report.rubric.value,
        "pages": [_page_json(scored) for scored in report.pages],
        "usage": _usage_json(report.usage),
    }


def _page_json(scored: ScoredPage) -> dict:
    """One page's scores, plus the unsupported claims when it was judged against facts."""
    payload = {
        "url": scored.page.url,
        "page_type": scored.page_type,
        "title": scored.page.title,
        "mean": round(scored.score.mean, 2),
        "scores": {
            name: {"score": dimension.score, "reason": dimension.reason}
            for name, dimension in scored.score.dimensions.items()
        },
    }
    if GROUNDEDNESS in scored.score.scores:
        payload["unsupported_claims"] = list(scored.score.unsupported_claims)
    return payload


def compare_json(report: CompareReport) -> dict:
    """The machine-readable pairwise report."""
    return {
        "name": report.name,
        "kind": "compare",
        "rubric": report.rubric.value,
        "tallies": [_tally_json(tally) for tally in report.tallies],
        "usage": _usage_json(report.usage),
    }


def _tally_json(tally: CompareTally) -> dict:
    """One pair: the head-to-head count, then whatever the rubric and facts added."""
    payload = {
        "a": tally.a,
        "b": tally.b,
        "a_wins": tally.a_wins,
        "b_wins": tally.b_wins,
        "ties": tally.ties,
        "samples": tally.samples,
    }
    if tally.per_question:
        payload["per_question"] = {
            name: {"a_wins": q.a_wins, "b_wins": q.b_wins, "ties": q.ties}
            for name, q in tally.per_question.items()
        }
    if tally.groundedness:
        payload["groundedness"] = [_side_json(side) for side in tally.groundedness]
    return payload


def _side_json(side: SideGroundedness) -> dict:
    """One side's reading. Kept whole: a difference of two scores is not a finding."""
    return {
        "url": side.url,
        "score": side.score,
        "unsupported_claims": list(side.unsupported_claims),
    }


def score_markdown(report: ScoreReport) -> str:
    """One table per page type, then every reason, then the spend."""
    lines = [
        f"# Page judge — {report.name}",
        "",
        f"Rubric: **{report.rubric.value}**. Scored 1-5, higher is better on every dimension.",
        "",
    ]
    for page_type in dict.fromkeys(scored.page_type for scored in report.pages):
        group = [s for s in report.pages if s.page_type == page_type]
        columns = _columns(report.rubric, group)
        lines += [f"## {page_type}", "", _header(columns), _divider(columns)]
        for scored in group:
            cells = _CELL.join(_cell(scored, name) for name in columns)
            lines.append(
                f"{_ROW}{scored.page.url}{_CELL}{cells}{_CELL}{scored.score.mean:.1f}{_END}"
            )
        lines.append("")
        lines += _reason_lines(group)
    lines += _spend_lines(report.usage)
    return "\n".join(lines) + "\n"


def _columns(rubric: Rubric, group: list[ScoredPage]) -> tuple[str, ...]:
    """The rubric's dimensions, plus groundedness once any page in the group has it."""
    grounded = any(GROUNDEDNESS in scored.score.scores for scored in group)
    return rubric.dimensions + ((GROUNDEDNESS,) if grounded else ())


def _header(columns: tuple[str, ...]) -> str:
    return f"{_ROW}URL{_CELL}" + _CELL.join(columns) + f"{_CELL}mean{_END}"


def _divider(columns: tuple[str, ...]) -> str:
    return "| --- |" + " --- |" * (len(columns) + 1)


def _cell(scored: ScoredPage, name: str) -> str:
    """A page judged without ground truth leaves the column empty rather than scoring 5."""
    dimension = scored.score.scores.get(name)
    return _UNSCORED if dimension is None else str(dimension.score)


def compare_markdown(report: CompareReport) -> str:
    """The tally table — every pair judged in both orders, so a sweep means something."""
    lines = [
        f"# Page judge — {report.name} (pairwise)",
        "",
        f"Rubric: **{report.rubric.value}**. Each pair was judged in both orders and the "
        "swapped verdict mapped back, so an even split is what position bias looks like.",
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
    for tally in report.tallies:
        lines += _question_lines(tally)
        lines += _groundedness_lines(tally)
    lines += _spend_lines(report.usage)
    return "\n".join(lines) + "\n"


def _question_lines(tally: CompareTally) -> list[str]:
    """Which page answered each question better — the reading a single winner flattens."""
    if not tally.per_question:
        return []
    lines = [
        f"### {tally.a} vs {tally.b} — by question",
        "",
        _ROW + _CELL.join(("question", "A better", "B better", "tie")) + _END,
        "| --- | --- | --- | --- |",
    ]
    for name, question in tally.per_question.items():
        cells = _CELL.join(str(v) for v in (question.a_wins, question.b_wins, question.ties))
        lines.append(f"{_ROW}{name}{_CELL}{cells}{_END}")
    lines.append("")
    return lines


def _groundedness_lines(tally: CompareTally) -> list[str]:
    """Both sides' readings, side by side and never subtracted from one another."""
    if not tally.groundedness:
        return []
    lines = [f"### {tally.a} vs {tally.b} — groundedness", ""]
    for side in tally.groundedness:
        lines += [f"**{side.url}** — {side.score}/5", ""]
        lines += _claim_lines(side.unsupported_claims)
    return lines


def _reason_lines(group: list[ScoredPage]) -> list[str]:
    lines: list[str] = []
    for scored in group:
        lines += [f"### {scored.page.title or scored.page.url}", "", f"<{scored.page.url}>", ""]
        for name, dimension in scored.score.dimensions.items():
            lines.append(f"- **{name}** {dimension.score}/5 — {dimension.reason}")
        lines.append("")
        if GROUNDEDNESS in scored.score.scores:
            lines += _claim_lines(scored.score.unsupported_claims)
    return lines


def _claim_lines(claims: tuple[str, ...]) -> list[str]:
    """The claims verbatim. The list is the finding; the score is only its length."""
    if not claims:
        return ["Unsupported claims: none — the ground truth supports every claim on the page.", ""]
    return ["Unsupported claims:", "", *[f"- {claim}" for claim in claims], ""]


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

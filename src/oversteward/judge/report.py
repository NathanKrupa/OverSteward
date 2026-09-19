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

#: The heading each per-pair and per-page detail block opens with.
_H3 = "### "


def _table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
    """A markdown table. The one place a row's punctuation is spelled out."""
    return [
        _ROW + _CELL.join(headers) + _END,
        "| --- |" + " --- |" * (len(headers) - 1),
        *[_ROW + _CELL.join(row) + _END for row in rows],
    ]


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
            name: _with_score(dimension.score, reason=dimension.reason)
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
        **_wins_json(tally.a_wins, tally.b_wins, tally.ties),
        "samples": tally.samples,
    }
    if tally.per_question:
        payload["per_question"] = {
            name: _wins_json(q.a_wins, q.b_wins, q.ties)
            for name, q in tally.per_question.items()
        }
    if tally.groundedness:
        payload["groundedness"] = [_side_json(side) for side in tally.groundedness]
    return payload


def _wins_json(a_wins: int, b_wins: int, ties: int) -> dict:
    """The one shape a count of preferences takes, whole pair or single question."""
    return {"a_wins": a_wins, "b_wins": b_wins, "ties": ties}


def _side_json(side: SideGroundedness) -> dict:
    """One side's reading. Kept whole: a difference of two scores is not a finding."""
    return {
        "url": side.url,
        **_with_score(side.score, unsupported_claims=list(side.unsupported_claims)),
    }


def _with_score(score: int, **rest) -> dict:
    """A payload that leads with its 1-5 score — one dimension, or one side's reading."""
    return {"score": score, **rest}


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
        rows = [_score_row(scored, columns) for scored in group]
        lines += [f"## {page_type}", "", *_table(("URL", *columns, "mean"), rows), ""]
        lines += _reason_lines(group)
    lines += _spend_lines(report.usage)
    return "\n".join(lines) + "\n"


def _columns(rubric: Rubric, group: list[ScoredPage]) -> tuple[str, ...]:
    """The rubric's dimensions, plus groundedness once any page in the group has it."""
    grounded = any(GROUNDEDNESS in scored.score.scores for scored in group)
    return rubric.dimensions + ((GROUNDEDNESS,) if grounded else ())


def _score_row(scored: ScoredPage, columns: tuple[str, ...]) -> tuple[str, ...]:
    return (scored.page.url, *(_cell(scored, name) for name in columns), f"{scored.score.mean:.1f}")


def _cell(scored: ScoredPage, name: str) -> str:
    """A page judged without ground truth leaves the column empty rather than scoring 5."""
    dimension = scored.score.scores.get(name)
    return _UNSCORED if dimension is None else str(dimension.score)


def compare_markdown(report: CompareReport) -> str:
    """The tally table — every pair judged in both orders, so a sweep means something."""
    rows = [
        (t.a, t.b, str(t.a_wins), str(t.b_wins), str(t.ties), str(t.samples))
        for t in report.tallies
    ]
    lines = [
        f"# Page judge — {report.name} (pairwise)",
        "",
        f"Rubric: **{report.rubric.value}**. Each pair was judged in both orders and the "
        "swapped verdict mapped back, so an even split is what position bias looks like.",
        "",
        *_table(("A", "B", "A wins", "B wins", "ties", "judgements"), rows),
        "",
    ]
    for tally in report.tallies:
        lines += _question_lines(tally)
        lines += _groundedness_lines(tally)
    lines += _spend_lines(report.usage)
    return "\n".join(lines) + "\n"


def _question_lines(tally: CompareTally) -> list[str]:
    """Which page answered each question better — the reading a single winner flattens."""
    if not tally.per_question:
        return []
    rows = [
        (name, str(q.a_wins), str(q.b_wins), str(q.ties))
        for name, q in tally.per_question.items()
    ]
    header = ("question", "A better", "B better", "tie")
    return [f"{_H3}{tally.a} vs {tally.b} — by question", "", *_table(header, rows), ""]


def _groundedness_lines(tally: CompareTally) -> list[str]:
    """Both sides' readings, side by side and never subtracted from one another."""
    if not tally.groundedness:
        return []
    lines = [f"{_H3}{tally.a} vs {tally.b} — groundedness", ""]
    for side in tally.groundedness:
        lines += [f"**{side.url}** — {side.score}/5", ""]
        lines += _claim_lines(side.unsupported_claims)
    return lines


def _reason_lines(group: list[ScoredPage]) -> list[str]:
    lines: list[str] = []
    for scored in group:
        lines += [f"{_H3}{scored.page.title or scored.page.url}", "", f"<{scored.page.url}>", ""]
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

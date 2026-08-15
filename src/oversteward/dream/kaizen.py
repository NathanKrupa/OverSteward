# ABOUTME: Session-start kaizen queue (OS#332) — durable verdicts so the process backlog drains.
# ABOUTME: Deterministic only: keys candidates, merges the two sources, ranks, and picks the next item.

"""The session-start kaizen queue (OS#332).

Every session opens by fixing **one** recurring process defect, then proceeds to
the day's actual work. Over weeks that drains a backlog the estate had been
re-encountering rather than fixing — nine error classes recurring across 9-11
distinct PRs each, as of the 2026-08-08 analysis.

This module is the deterministic substrate. It never fixes anything and never
writes doctrine; it decides *what is next* and remembers *what was already ruled
on*, which is the part the monthly promotion pass (OS#325) lacked.

**Why verdicts exist.** :func:`oversteward.dream.promotion.build_worklist` is
stateless: it ranks by recurrence and caps, so the highest-recurrence cluster is
the head of the list every single time. A per-session pass over it would propose
the same item forever and drain nothing. A verdict ledger turns the list into a
queue.

Two sources feed it, because measured recurrence and human judgement each catch
what the other misses:

- **promotion clusters** — lessons the corpus shows recurring, tagged for
  promotion by their own authors;
- **`kaizen`-labelled issues** — process defects someone already judged real
  enough to file.

Verdict vocabulary is deliberately three-valued. ``promoted`` and ``declined``
are terminal. ``deferred`` records a decision *to wait*, not a decision to drop,
so a deferred item stays in the queue — otherwise "not today" would silently
become "never", which is the failure mode this whole queue exists to correct.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from oversteward.dream.promotion import PromotionCandidate, verify_report_is_measurable

#: Terminal verdicts remove an item from the queue; `deferred` does not.
VERDICTS: tuple[str, ...] = ("promoted", "declined", "deferred")
TERMINAL_VERDICTS: frozenset[str] = frozenset({"promoted", "declined"})

#: The label that marks an issue as a process defect belonging in this queue.
KAIZEN_LABEL = "kaizen"

DEFAULT_REPO = "oversteward"

_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _SPACE_RE.sub(" ", _PUNCT_RE.sub(" ", text.lower())).strip()


def candidate_key(candidate: PromotionCandidate) -> str:
    """A stable identity for a promotion cluster, independent of its recurrence.

    Keyed on the normalized canonical text, so the same lesson keeps its verdict
    as its recurrence count grows.

    **Known limitation, stated rather than hidden:** cluster canonical text is
    the first member's normalized form, so as the corpus grows a cluster can be
    re-canonicalised around a different bullet and present a new key. A ruled-on
    lesson resurfacing *once* after such a drift is acceptable; silently
    re-proposing a declined lesson every session is not, and this key prevents
    the common case. Semantic clustering (Fiscus `embeddings` extra) would make
    the identity considerably steadier.
    """
    return "cluster:" + hashlib.sha256(_normalize(candidate.canonical_text).encode()).hexdigest()[:16]


def issue_key(repo: str, number: int) -> str:
    """A stable identity for a filed finding."""
    return f"issue:{repo}#{number}"


def read_verdicts(path: Path) -> dict[str, dict]:
    """Every recorded verdict, keyed by item key. A missing or damaged ledger reads empty.

    A corrupt ledger must not take the session's opening step down with it — the
    worst consequence of an unreadable ledger is re-proposing a settled item.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    verdicts = data.get("verdicts") if isinstance(data, dict) else None
    return verdicts if isinstance(verdicts, dict) else {}


def record_verdict(
    path: Path,
    *,
    key: str,
    verdict: str,
    on: date,
    note: str = "",
) -> None:
    """Rule on one item. A later verdict supersedes an earlier one for the same key."""
    if verdict not in VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r} — expected one of {VERDICTS}")
    verdicts = read_verdicts(path)
    verdicts[key] = {"verdict": verdict, "on": on.isoformat(), "note": note}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"verdicts": verdicts}, indent=1, sort_keys=True), encoding="utf-8")


@dataclass
class KaizenItem:
    """One thing to fix, with the evidence for why it is worth fixing."""

    key: str
    source: str
    title: str
    reference: str
    count: int
    target: str
    detail: str
    labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "source": self.source,
            "title": self.title,
            "reference": self.reference,
            "count": self.count,
            "target": self.target,
            "detail": self.detail,
            "labels": list(self.labels),
        }


def _is_resolved(key: str, verdicts: dict[str, dict]) -> bool:
    return (verdicts.get(key) or {}).get("verdict") in TERMINAL_VERDICTS


def build_queue(
    *,
    candidates: list[PromotionCandidate],
    issues: list[dict],
    verdicts: dict[str, dict],
    repo: str = DEFAULT_REPO,
    report: dict | None = None,
) -> list[KaizenItem]:
    """Merge both sources into one ranked queue, minus anything already ruled on.

    Ranked by recurrence, so the queue reflects what the corpus actually shows
    rather than filing order. A filed issue carries no recurrence count and
    sorts below counted clusters — but is never dropped, because someone already
    judged it real enough to file.

    When ``report`` is supplied it is checked first: an empty backlog must never
    be reported when the detector that produced it is broken (Fiscus #101).
    """
    if report is not None:
        verify_report_is_measurable(report)

    items: list[KaizenItem] = []

    for candidate in candidates:
        key = candidate_key(candidate)
        if _is_resolved(key, verdicts):
            continue
        prs = ", ".join(candidate.prs[:6])
        items.append(
            KaizenItem(
                key=key,
                source="promotion",
                title=candidate.canonical_text,
                reference=candidate.prs[0] if candidate.prs else "",
                count=candidate.count,
                target=candidate.target,
                detail=f"{candidate.count}x across {', '.join(candidate.repos)} · PRs: {prs}",
            )
        )

    for issue in issues:
        labels = [label.get("name", "") for label in issue.get("labels") or []]
        if KAIZEN_LABEL not in labels:
            continue
        number = int(issue.get("number", 0))
        key = issue_key(repo, number)
        if _is_resolved(key, verdicts):
            continue
        items.append(
            KaizenItem(
                key=key,
                source="issue",
                title=issue.get("title", ""),
                reference=f"{repo}#{number}",
                count=0,
                target="issue",
                detail=f"filed finding, labels: {', '.join(labels)}",
                labels=labels,
            )
        )

    items.sort(key=lambda item: (-item.count, item.source, item.title))
    return items


def next_item(queue: list[KaizenItem]) -> KaizenItem | None:
    """The one item this session opens with, or ``None`` when the queue is empty."""
    return queue[0] if queue else None


def format_next(item: KaizenItem | None, *, queue_size: int) -> str:
    """The session-start surface: one item, its evidence, and what remains behind it."""
    if item is None:
        return (
            "**Nothing queued.** No unresolved kaizen item — every surfaced cluster and\n"
            "every `kaizen`-labelled issue has been ruled on. The pattern report was\n"
            "verified non-empty first, so this is a measured backlog rather than a\n"
            "silent instrument failure.\n"
        )

    remaining = max(0, queue_size - 1)
    # Recurrence leads, because it is the whole argument for fixing this one
    # first. A filed finding has no count and says so rather than showing 0.
    recurrence = f"{item.count}x recurrence" if item.count else "filed finding"
    lines = [
        "# Kaizen — this session's item",
        "",
        f"## {item.title}",
        "",
        f"- **{recurrence}** · reference: {item.reference or '—'}",
        f"- source: `{item.source}` · target: `{item.target}`",
        f"- evidence: {item.detail}",
        f"- key: `{item.key}`",
        "",
        f"{remaining} item(s) behind it in the queue ({queue_size} total).",
        "",
        "Fix this first, then move to the session's work — unless Nathan opened the",
        "session with an explicit task, in which case his task goes first and this",
        "follows. Record the outcome with `dream kaizen resolve`.",
        "",
    ]
    return "\n".join(lines)

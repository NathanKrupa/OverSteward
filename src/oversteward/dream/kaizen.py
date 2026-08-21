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

from oversteward.dream.promotion import (
    ClusteringStatus,
    PromotionCandidate,
    verify_report_is_measurable,
)

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


#: What a lexically-clustered count is worth, said in the count's own place.
UNMEASURED_HINT = "read the cluster members before trusting the rank"


#: The fallback engaged: nobody asked for lexical clustering and it ran anyway.
DEGRADED_BANNER: tuple[str, ...] = (
    "> **DEGRADED — the pattern detector fell back to lexical clustering.**",
    "> Semantic clustering was unavailable (the fiscus `embeddings` extra is not",
    "> installed), so clusters were grouped by shared wording rather than by",
    "> meaning. Every recurrence count below is a lexical artifact, **not a",
    f"> measurement** — {UNMEASURED_HINT}.",
    "",
)

#: Lexical clustering that was asked for. Honest, and still not a measurement.
LEXICAL_REQUESTED_NOTICE: tuple[str, ...] = (
    "> **Lexical clustering (explicitly requested).** Clusters were grouped by",
    "> shared wording rather than by meaning, so the recurrence counts below are",
    f"> not measurements — {UNMEASURED_HINT}.",
    "",
)

#: The report predates Fiscus #119. Unknown — which is not "semantic".
UNREPORTED_MODE_NOTICE: tuple[str, ...] = (
    "> **This report does not report its clustering mode.** It predates the",
    "> `clustering` block (Fiscus #119), so the counts below may be lexical",
    "> artifacts rather than measured recurrence. Rebuild it with a current",
    "> fiscus to know which.",
    "",
)


def _unfamiliar_mode_notice(mode: str | None) -> list[str]:
    """A mode this consumer has no opinion about is disclosed, never trusted."""
    return [
        f"> **Unfamiliar clustering mode `{mode}`.** This consumer knows",
        "> `semantic` and `lexical` only, so it cannot certify the counts below as",
        f"> measured — {UNMEASURED_HINT}.",
        "",
    ]


def clustering_notice(clustering: ClusteringStatus | None) -> list[str]:
    """The lines that must sit *above* the item, given how the report was clustered.

    Empty for a semantic report and for a run with no report at all — there is
    nothing to disclose. Every other state discloses something, because the
    ranking this surface prints is only as good as the engine behind it, and a
    degraded report is worse than an empty one: it looks like a working one
    (OS#352).
    """
    if clustering is None or clustering.measured:
        return []
    if clustering.degraded:
        return list(DEGRADED_BANNER)
    if clustering.lexical:
        return list(LEXICAL_REQUESTED_NOTICE)
    if clustering.reported:
        return _unfamiliar_mode_notice(clustering.mode)
    return list(UNREPORTED_MODE_NOTICE)


def _recurrence_label(item: KaizenItem, clustering: ClusteringStatus | None) -> str:
    """The count, carrying its own provenance where the count is read.

    A caveat parked at the top of the page is skimmed past; the mark belongs on
    the number itself, because the number is what a session acts on.
    """
    if not item.count:
        return "filed finding"
    if clustering is not None and clustering.lexical:
        fallback = "lexical fallback" if clustering.degraded else "lexical clustering"
        return f"{item.count}x recurrence (UNMEASURED — {fallback}; {UNMEASURED_HINT})"
    return f"{item.count}x recurrence"


#: The measured-empty backlog. Its claim of measurement is about the *corpus*;
#: any doubt about the clustering engine is disclosed by the notice above it.
NOTHING_QUEUED: tuple[str, ...] = (
    "**Nothing queued.** No unresolved kaizen item — every surfaced cluster and",
    "every `kaizen`-labelled issue has been ruled on. The pattern report was",
    "verified non-empty first, so this is a measured backlog rather than a",
    "silent instrument failure.",
    "",
)


def _item_lines(
    item: KaizenItem, *, queue_size: int, clustering: ClusteringStatus | None
) -> list[str]:
    """One item, evidence first — recurrence leads because it is the whole argument."""
    remaining = max(0, queue_size - 1)
    return [
        f"## {item.title}",
        "",
        f"- **{_recurrence_label(item, clustering)}** · reference: {item.reference or '—'}",
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


def format_next(
    item: KaizenItem | None,
    *,
    queue_size: int,
    clustering: ClusteringStatus | None = None,
) -> str:
    """The session-start surface: one item, its evidence, and what remains behind it.

    ``clustering`` is the provenance of the report the queue was built from
    (:func:`oversteward.dream.promotion.read_clustering_status`). ``None`` means
    no report was supplied at all, so there are no counted clusters to qualify.
    The notice it produces sits *above* the item, because a caveat printed under
    a confident number is read after the number has already been believed.
    """
    notice = clustering_notice(clustering)
    if item is None:
        return "\n".join([*notice, *NOTHING_QUEUED])
    return "\n".join(
        [
            "# Kaizen — this session's item",
            "",
            *notice,
            *_item_lines(item, queue_size=queue_size, clustering=clustering),
        ]
    )

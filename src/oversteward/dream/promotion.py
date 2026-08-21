# ABOUTME: Trajectory-promotion pass (design §13.5, OS#325) — cadence probe + promotion worklist.
# ABOUTME: Deterministic only: probes the cadence, guards the false green, ranks and caps the worklist.

"""Deterministic half of the dream cycle's trajectory-promotion pass (OS#325).

The estate captures lessons well and consumes them never. As of 2026-08-08 it
held 425 trajectory notes carrying ~1,270 lesson bullets, of which 84 were
explicitly self-tagged ``promote: doctrine`` or ``promote: memory`` — against a
promotion corpus of 19 entries. Nine error classes were recurring across 9-11
distinct PRs each, because a lesson written into a trajectory note and never
promoted changes no behaviour.

This pass closes that loop on a monthly cadence: run the cross-repo pattern
report, keep the clusters that recur often enough *and* whose authors already
asked for promotion, and hand the in-session step a bounded, evidence-carrying
worklist. Promotion itself stays a reviewed change — this module never writes
doctrine, exactly as :mod:`oversteward.dream.roadmap` never writes the roadmap.

**The false-green guard is the point, not a detail.** The analyzer this pass
consumes spent its entire life reporting "no patterns detected" over the whole
corpus (Fiscus #101) — three defects deep, and silent, because nothing treated
an empty answer as suspicious. :func:`verify_report_is_measurable` refuses to
let that recur: zero clusters over a large corpus raises rather than reports a
clean bill of health. "Found nothing" and "could not look" must never render the
same.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# `→ promote: <target>` as the trajectory TEMPLATE prescribes it. The trailing
# sentence period is optional and not part of the value.
PROMOTE_RE = re.compile(r"promote:\s*([a-z.]+?)\.?\s*$", re.IGNORECASE | re.MULTILINE)

#: Targets a promotion worklist can act on. `none` is a deliberate authorial
#: judgement that the lesson is not worth promoting, and is honoured, not
#: second-guessed; `lessons.jsonl` belongs to Fiscus's own promotion cycle.
PROMOTABLE_TARGETS: tuple[str, ...] = ("doctrine", "memory")
KNOWN_TARGETS: tuple[str, ...] = ("doctrine", "memory", "lessons.jsonl", "none")

#: A monthly floor, matching the roadmap pass's reconciliation cadence.
HARD_CAP_DAYS = 28

#: Below this many notes a corpus may legitimately have nothing recurring, so an
#: empty report is believable. Above it, an empty report is a broken instrument.
MEASURABLE_CORPUS_NOTES = 50

#: Recurrence at or above which a cluster is worth a promotion decision.
MIN_RECURRENCE = 3

#: The key Fiscus stamps a report with to declare how its clusters were computed
#: (Fiscus #119) — `{"clustering": {"mode": "semantic"|"lexical", "degraded": bool}}`.
CLUSTERING_KEY = "clustering"

#: Clustering engines a report can name. `semantic` groups by embedded meaning;
#: `lexical` groups by shared wording and invents recurrence out of phrasing.
SEMANTIC_MODE = "semantic"
LEXICAL_MODE = "lexical"

#: Worklist cap. A promotion pass that proposes forty changes gets deferred
#: whole; one that proposes a dozen gets done.
DEFAULT_CAP = 12


class FalseGreenError(RuntimeError):
    """The report claims nothing recurs across a corpus far too large for that.

    Raised instead of returning an empty worklist, because an empty worklist is
    indistinguishable from a healthy estate and would be filed as good news.
    """


def parse_promote_target(bullet: str) -> str:
    """The `promote:` target a lesson bullet asks for, or `""` if it names none.

    An absent tag and an off-vocabulary one both return `""` — the caller treats
    both as "no promotion requested", which keeps a typo from silently promoting
    something into doctrine.
    """
    match = PROMOTE_RE.search(bullet.strip())
    if match is None:
        return ""
    value = match.group(1).lower().rstrip(".")
    return value if value in KNOWN_TARGETS else ""


@dataclass
class PromotionProbe:
    """Cadence verdict: is the promotion pass due, and why."""

    due: bool
    stamp: date | None
    days_old: int | None
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "due": self.due,
            "stamp": self.stamp.isoformat() if self.stamp else None,
            "days_old": self.days_old,
            "reasons": list(self.reasons),
        }


def probe_due(
    last_run: date | None,
    *,
    today: date,
    hard_cap_days: int = HARD_CAP_DAYS,
) -> PromotionProbe:
    """Whether the monthly promotion pass is due.

    Deliberately simpler than the roadmap probe: there is no activity signal to
    weigh, because the corpus grows with every merged PR estate-wide and is
    therefore always accumulating. Time since the last pass is the whole policy.
    """
    if last_run is None:
        return PromotionProbe(
            due=True,
            stamp=None,
            days_old=None,
            reasons=["never run — no promotion pass recorded"],
        )

    days_old = (today - last_run).days
    if days_old > hard_cap_days:
        return PromotionProbe(
            due=True,
            stamp=last_run,
            days_old=days_old,
            reasons=[f"{days_old}d since the last pass (cap {hard_cap_days}d)"],
        )
    return PromotionProbe(
        due=False,
        stamp=last_run,
        days_old=days_old,
        reasons=[f"{days_old}d since the last pass — inside the {hard_cap_days}d window"],
    )


@dataclass
class PromotionCandidate:
    """One cluster the estate has asked, repeatedly, to have promoted."""

    canonical_text: str
    category: str
    count: int
    repos: list[str]
    target: str
    section: str
    prs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "canonical_text": self.canonical_text,
            "category": self.category,
            "count": self.count,
            "repos": list(self.repos),
            "target": self.target,
            "section": self.section,
            "prs": list(self.prs),
        }


def corpus_size(report: dict) -> int | None:
    """How many notes the report was built from, or ``None`` if it does not say.

    The two report shapes count differently: a single-repo report carries a
    ``notes`` list, while the cross-repo (``--all-active``) form carries
    ``per_repo_counts``. The cadence uses the cross-repo form, so a reader that
    knows only about ``notes`` scores a 346-note corpus as zero — and a zero
    corpus is exactly the case the false-green guard waves through.

    ``None`` means *the report did not say*, which is not the same as zero and
    must not resolve to the same verdict.
    """
    if "notes" in report:
        return len(report.get("notes") or [])
    if "per_repo_counts" in report:
        return sum(int(row.get("count", 0)) for row in report.get("per_repo_counts") or [])
    return None


def verify_report_is_measurable(
    report: dict,
    *,
    min_notes: int = MEASURABLE_CORPUS_NOTES,
) -> None:
    """Raise when the report is empty over a corpus too large to be genuinely quiet.

    A small corpus may honestly have nothing recurring; a large one that reports
    nothing is a broken instrument reporting health. This is the guard whose
    absence let Fiscus #101 stay invisible for the analyzer's whole life.

    A report that declares no corpus size at all also raises: an unknown corpus
    cannot be certified quiet, and "could not look" must never render the same
    as "looked and found little".
    """
    cluster_count = len(report.get("recurring_drag") or []) + len(
        report.get("candidate_lessons") or []
    )
    if cluster_count:
        return

    notes = corpus_size(report)
    if notes is None:
        raise FalseGreenError(
            "pattern report found 0 clusters and declares no corpus size "
            "(neither `notes` nor `per_repo_counts`) — the corpus is unknown, "
            "not empty. Refusing to certify an unmeasured estate as quiet."
        )
    if notes >= min_notes:
        raise FalseGreenError(
            f"pattern report found 0 clusters across {notes} notes — "
            "that is the false-green signature of a broken detector, not a "
            "clean bill of health (see Fiscus #101). Refusing to report an "
            "empty promotion worklist as good news."
        )


@dataclass(frozen=True)
class ClusteringStatus:
    """How a pattern report's clusters were computed, as the report itself declares it.

    Three states, and they must stay three (OS#352). A report clustered by
    embedded meaning carries counts that were *measured*. A report clustered by
    shared wording carries counts the phrasing invented — six bullets about
    unrelated lessons, glued by the word "inert". A report that declares nothing
    is *unknown*, which is neither, and must never be optimistically read as the
    first.

    ``degraded`` is Fiscus's own word for the fallback case — lexical clustering
    that was fallen back to rather than asked for. It is not derivable from
    ``mode``, which is why the producer sends both.
    """

    mode: str | None
    degraded: bool
    reported: bool

    @property
    def lexical(self) -> bool:
        """True when the report says its clusters came from wording, not meaning."""
        return self.mode == LEXICAL_MODE

    @property
    def measured(self) -> bool:
        """True only when the report positively declares the semantic path ran.

        An absent, malformed or unfamiliar mode is not measured. Silence about
        the instrument is never evidence that the instrument was working.
        """
        return self.reported and self.mode == SEMANTIC_MODE


def read_clustering_status(report: dict) -> ClusteringStatus:
    """The clustering provenance a report declares, or an explicit *unknown*.

    Reads the ``clustering`` block Fiscus #119 added to both report shapes. A
    block that is missing, is not an object, or names no string ``mode`` reads
    as unreported — "could not read the mode" lands beside "the report predates
    mode reporting", and neither lands on measured.
    """
    block = report.get(CLUSTERING_KEY)
    if not isinstance(block, dict):
        return ClusteringStatus(mode=None, degraded=False, reported=False)
    mode = block.get("mode")
    if not isinstance(mode, str) or not mode:
        return ClusteringStatus(mode=None, degraded=False, reported=False)
    return ClusteringStatus(mode=mode, degraded=bool(block.get("degraded")), reported=True)


def _dominant_target(cluster: dict) -> str:
    """The promote target most of a cluster's bullets ask for.

    Ties break toward the earlier :data:`KNOWN_TARGETS` entry so the result does
    not depend on bullet ordering. A cluster whose bullets ask for nothing
    resolves to `""` and is dropped by the caller.
    """
    tallies: dict[str, int] = {}
    for item in cluster.get("items") or []:
        target = parse_promote_target(item.get("bullet", ""))
        if target:
            tallies[target] = tallies.get(target, 0) + 1
    if not tallies:
        return ""
    best = max(tallies.values())
    for candidate in KNOWN_TARGETS:
        if tallies.get(candidate) == best:
            return candidate
    return ""


def build_worklist(
    report: dict,
    *,
    min_recurrence: int = MIN_RECURRENCE,
    targets: tuple[str, ...] = PROMOTABLE_TARGETS,
    cap: int = DEFAULT_CAP,
) -> list[PromotionCandidate]:
    """Rank the report's clusters into a bounded promotion worklist.

    Kept when the cluster recurs at least ``min_recurrence`` times *and* its
    bullets ask for one of ``targets``. Both conditions matter: recurrence alone
    surfaces noise the authors already judged not worth promoting, and the tag
    alone surfaces one-offs.

    Raises :class:`FalseGreenError` when the underlying report is empty over a
    large corpus — an empty worklist must never be reported as a healthy estate.
    """
    verify_report_is_measurable(report)

    candidates: list[PromotionCandidate] = []
    for section in ("recurring_drag", "candidate_lessons"):
        for cluster in report.get(section) or []:
            count = int(cluster.get("count", 0))
            if count < min_recurrence:
                continue
            target = _dominant_target(cluster)
            if target not in targets:
                continue
            candidates.append(
                PromotionCandidate(
                    canonical_text=cluster.get("canonical_text", ""),
                    category=cluster.get("category", "uncategorized"),
                    count=count,
                    repos=list(cluster.get("repos") or []),
                    target=target,
                    section=section,
                    prs=[i.get("pr", "") for i in (cluster.get("items") or []) if i.get("pr")],
                )
            )

    candidates.sort(key=lambda c: (-c.count, c.canonical_text))
    return candidates[:cap]


def format_packet(candidates: list[PromotionCandidate], *, generated_on: date) -> str:
    """The context packet the in-session promotion step drafts from.

    Every line carries its evidence — recurrence count and contributing PRs — so
    a promotion decision can be audited without re-running the report.
    """
    lines = [
        f"# Trajectory promotion worklist — {generated_on.isoformat()}",
        "",
    ]
    if not candidates:
        lines += [
            "**Nothing to promote.** No cluster met both the recurrence floor and a",
            "`promote: doctrine|memory` tag. The report was verified non-empty first,",
            "so this is a measured result rather than a silent instrument failure.",
            "",
        ]
        return "\n".join(lines)

    lines += [
        f"{len(candidates)} candidate(s), ranked by recurrence. Each recurred often",
        "enough to matter and was tagged for promotion by its own author.",
        "",
    ]
    for index, candidate in enumerate(candidates, start=1):
        repos = ", ".join(candidate.repos) or "—"
        prs = ", ".join(candidate.prs[:8])
        if len(candidate.prs) > 8:
            prs += f", +{len(candidate.prs) - 8} more"
        lines += [
            f"## {index}. → {candidate.target} ({candidate.count}x · {repos})",
            "",
            f"{candidate.canonical_text}",
            "",
            f"- category: `{candidate.category}` · section: `{candidate.section}`",
            f"- contributing PRs: {prs}",
            "",
        ]
    return "\n".join(lines)


# --- run ledger -------------------------------------------------------------
#
# The pass records every run, not just the latest, so a skipped month is
# visible as a gap rather than inferred from a single stamp's age.


def default_promotion_ledger_path(repo_root: Path) -> Path:
    """Where the promotion pass records its runs, beside the other dream state."""
    return repo_root / "data" / "dream" / "promotion.json"


def read_run_history(path: Path) -> list[dict]:
    """Every recorded run, oldest first. A missing or damaged ledger reads empty.

    A corrupt ledger must not take the dream cycle down with it — the worst
    consequence of an unreadable ledger is running the pass a month early.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    runs = data.get("runs") if isinstance(data, dict) else None
    return runs if isinstance(runs, list) else []


def read_last_run(path: Path) -> date | None:
    """The most recent recorded run date, or ``None`` if the pass never ran."""
    history = read_run_history(path)
    if not history:
        return None
    try:
        return date.fromisoformat(history[-1]["ran_on"])
    except (KeyError, TypeError, ValueError):
        return None


def record_run(path: Path, *, ran_on: date, candidates: int) -> None:
    """Append this run to the ledger, creating it on first use."""
    history = read_run_history(path)
    history.append({"ran_on": ran_on.isoformat(), "candidates": candidates})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"runs": history}, indent=1), encoding="utf-8")

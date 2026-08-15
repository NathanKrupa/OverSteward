# ABOUTME: Roadmap intent-reconciliation pass (design §13.4, OS#231) — staleness probe + context packet.
# ABOUTME: Deterministic only: parses the roadmap stamp, counts merges, formats the reconciliation packet.

"""Deterministic half of the dream cycle's intent-reconciliation pass (OS#231).

The pass keeps ``documentation/ROADMAP.md`` from silently decaying: every dream
cycle probes whether the roadmap has fallen behind reality, and when it has, the
in-session LLM step drafts a dated reconciliation section from the context
packet built here. This module is the deterministic substrate — nothing in it
calls a model, and everything takes injectable inputs so tests never touch the
real roadmap or repo.

Staleness policy (probe):

- no ``*Last updated:*`` stamp → stale (the file lost its clock);
- stamp older than ``hard_cap_days`` (default 28) → stale regardless of
  activity — a monthly reconciliation floor;
- merges landed on master since the stamp AND the stamp is older than
  ``grace_days`` (default 7) → stale — activity is outpacing the doc, but a
  fresh reconciliation is not re-triggered by its own merge.

The write path is owned by the skill step, not this module: a stale verdict
leads to a session worktree and a doc-only PR — never a direct commit to the
primary checkout's master (OS#90).
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

LAST_UPDATED_RE = re.compile(r"\*Last updated:\s*(\d{4}-\d{2}-\d{2})")

GRACE_DAYS = 7
HARD_CAP_DAYS = 28


def parse_last_updated(roadmap_text: str) -> date | None:
    """The roadmap's ``*Last updated: YYYY-MM-DD`` stamp (last occurrence wins)."""
    matches = LAST_UPDATED_RE.findall(roadmap_text)
    if not matches:
        return None
    return date.fromisoformat(matches[-1])


@dataclass
class RoadmapStaleness:
    """Probe verdict: is the roadmap due for a reconciliation pass, and why."""

    stale: bool
    stamp: date | None
    days_old: int | None
    merges_since: int
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "stale": self.stale,
            "stamp": self.stamp.isoformat() if self.stamp else None,
            "days_old": self.days_old,
            "merges_since": self.merges_since,
            "reasons": self.reasons,
        }


def probe_staleness(
    roadmap_text: str,
    *,
    merges_since: int,
    now: date,
    grace_days: int = GRACE_DAYS,
    hard_cap_days: int = HARD_CAP_DAYS,
) -> RoadmapStaleness:
    """Apply the staleness policy to the roadmap stamp and master's merge activity."""
    stamp = parse_last_updated(roadmap_text)
    if stamp is None:
        return RoadmapStaleness(
            stale=True,
            stamp=None,
            days_old=None,
            merges_since=merges_since,
            reasons=["no *Last updated:* stamp found"],
        )
    days_old = (now - stamp).days
    reasons: list[str] = []
    if days_old >= hard_cap_days:
        reasons.append(f"stamp is {days_old} days old (hard cap {hard_cap_days})")
    if merges_since > 0 and days_old >= grace_days:
        reasons.append(
            f"{merges_since} merge(s) on master since the stamp, which is {days_old} days old"
        )
    return RoadmapStaleness(
        stale=bool(reasons),
        stamp=stamp,
        days_old=days_old,
        merges_since=merges_since,
        reasons=reasons,
    )


def _merge_ref(repo_root: Path) -> str:
    """``origin/master`` when the ref exists, else ``master``.

    The primary checkout's local master habitually runs behind origin (OS#64) —
    counting merges against it would silently miss just-merged PRs.
    """
    probe = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "-q", "origin/master"],
        capture_output=True,
        text=True,
    )
    return "origin/master" if probe.returncode == 0 else "master"


def _merge_log(repo_root: Path, since: date, fmt: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "log",
            "--merges",
            f"--since={since.isoformat()}",
            f"--format={fmt}",
            _merge_ref(repo_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def count_merges_since(repo_root: Path, since: date) -> int:
    """Merge commits on master since ``since`` (the probe's activity signal)."""
    return len(_merge_log(repo_root, since, "%H"))


def list_merges_since(repo_root: Path, since: date) -> list[str]:
    """Merge-commit subject lines on master since ``since`` (packet feed)."""
    return _merge_log(repo_root, since, "%s")


_NO_STAMP_FLOOR = date(2000, 1, 1)


def probe_repo(roadmap_path: Path, repo_root: Path, *, now: date) -> RoadmapStaleness:
    """Read the roadmap on disk and probe it against the repo's merge activity."""
    text = roadmap_path.read_text(encoding="utf-8")
    since = parse_last_updated(text) or _NO_STAMP_FLOOR
    return probe_staleness(text, merges_since=count_merges_since(repo_root, since), now=now)


def packet_for_repo(
    roadmap_path: Path, repo_root: Path, *, issues: list[dict], prs: list[dict]
) -> str:
    """Build the reconciliation packet for the roadmap + repo on disk."""
    text = roadmap_path.read_text(encoding="utf-8")
    since = parse_last_updated(text) or _NO_STAMP_FLOOR
    return gather_packet(
        roadmap_text=text,
        merges=list_merges_since(repo_root, since),
        issues=issues,
        prs=prs,
    )


def gather_packet(
    *,
    roadmap_text: str,
    merges: list[str],
    issues: list[dict],
    prs: list[dict],
) -> str:
    """The reconciliation context packet the in-session LLM step drafts from.

    Pure formatting over injected snapshots — the caller supplies merge subjects
    (:func:`list_merges_since`) and issue/PR snapshots (``gh … --json
    number,title,state``); nothing is fetched here.
    """
    stamp = parse_last_updated(roadmap_text)
    lines = [
        "# Roadmap reconciliation packet",
        "",
        f"Roadmap last updated: {stamp.isoformat() if stamp else 'unknown'}",
        "",
        "## Merges on master since the stamp",
        "",
    ]
    if merges:
        lines.extend(f"- {subject}" for subject in merges)
    else:
        lines.append("(none)")
    lines += ["", "## Issues", ""]
    if issues:
        lines.extend(f"- {i['state']} #{i['number']} — {i['title']}" for i in issues)
    else:
        lines.append("(none)")
    lines += ["", "## Pull requests", ""]
    if prs:
        lines.extend(f"- {p['state']} #{p['number']} — {p['title']}" for p in prs)
    else:
        lines.append("(none)")
    lines.append("")
    return "\n".join(lines)

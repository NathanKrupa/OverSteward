# ABOUTME: Renders the estate map's digest, loaded by every OverSteward session, and one slice per repo.
# ABOUTME: Pure and deterministic, so each committed render can be compared byte for byte with a fresh one.

from __future__ import annotations

import re

from .model import Capability, EstateMap
from .outcome import Finding

#: A sentence ends at `.`, `!` or `?` followed by whitespace and a capital, a code
#: span or a parenthesis, so `v2.0`, `1.5 kB` and `e.g. two` do not end one.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z`(])")

DIGEST_HEADER = (
    "<!-- Generated from estate-map.yaml by `scripts/estate_map.py render --write`. "
    "Do not edit by hand: a test compares this file with a fresh render. -->"
)


def digest(estate: EstateMap) -> str:
    lines = [
        DIGEST_HEADER,
        "",
        "# Estate map — digest",
        "",
        f"**North star.** {estate.north_star.strip()}",
        "",
        "**Products.** "
        + "; ".join(f"`{p.id}` ({p.repo}) serves {p.serves.strip()}" for p in estate.products),
        "",
        "## Capabilities (`id` · status · purpose)",
        "",
    ]
    lines += [f"- `{c.id}` · {c.status} · {c.purpose.strip()}" for c in estate.capabilities]
    lines += [
        "",
        f"Claims, current and target shape, seams ({_span(estate.seams)}), invariants "
        f"({_span(estate.invariants)}) and liabilities live in `estate-map.yaml`. "
        "Read it at scope time; `scripts/estate_map.py check` is the seventh session-start sweep. "
        "Each repo's own slice is `shared/references/estate-map/<repo>.md`.",
    ]
    return "\n".join(lines) + "\n"


def _span(rows) -> str:
    ids = [r.id for r in rows]
    return f"{ids[0]}..{ids[-1]}" if ids else "none"


def budget_findings(estate: EstateMap, text: str) -> list[Finding]:
    return _over_budget("digest-budget", "digest", text, estate.policy.digest_budget_bytes)


def slice_budget_findings(estate: EstateMap, repo: str, text: str) -> list[Finding]:
    return _over_budget("slice-budget", repo, text, estate.policy.slice_budget_bytes)


def _over_budget(check: str, subject: str, text: str, budget: int) -> list[Finding]:
    size = len(text.encode("utf-8"))
    if size > budget:
        return [Finding(check, subject, f"{size} bytes exceeds the {budget}-byte budget")]
    return []


def _repos_of(estate: EstateMap, cap: Capability) -> set[str]:
    """The repo whose product a capability belongs to, plus every repo it claims paths in."""
    owners = {p.id: p.repo for p in estate.products}
    owner = owners.get(cap.id.split(".", 1)[0])
    return set(cap.claims) | ({owner} if owner else set())


def slice_repos(estate: EstateMap) -> tuple[str, ...]:
    """Every repo at least one capability belongs to: the repos that get a slice."""
    return tuple(sorted(set().union(*(_repos_of(estate, c) for c in estate.capabilities))))


def slice_name(repo: str) -> str:
    return f"{repo}.md"


def stale_slices(present: list[str], estate: EstateMap) -> list[str]:
    """The `.md` names in a slice directory that no repo's slice renders to."""
    rendered = {slice_name(repo) for repo in slice_repos(estate)}
    return sorted(name for name in present if name.endswith(".md") and name not in rendered)


def repo_slice(estate: EstateMap, repo: str) -> str:
    """One repo's share of the map: its capabilities, and the rows that touch it.

    A seam touches the repo when the repo produces or consumes it. A live
    invariant touches it when one of its capabilities or seams cites it; a
    liability, likewise, or when the repo owns it. Citation is read from the
    capability and seam side only: validate holds each row's `capabilities`
    list to exactly the capabilities citing it.
    """
    caps = [c for c in estate.capabilities if repo in _repos_of(estate, c)]
    seams = [s for s in estate.seams if repo in s.producer or repo in s.consumer]
    cited_invariants = {i for c in caps for i in c.invariants} | {i for s in seams for i in s.invariants}
    cited_liabilities = {i for c in caps for i in c.liabilities} | {
        i for s in seams for i in s.liabilities
    }
    invariants = [i for i in estate.invariants if i.status == "live" and i.id in cited_invariants]
    liabilities = [
        item
        for item in estate.liabilities
        if item.id in cited_liabilities or item.owner.split(" ", 1)[0] == repo
    ]
    lines = [
        DIGEST_HEADER,
        "",
        f"# Estate map — {repo}",
        "",
        f"**North star.** {estate.north_star.strip()}",
        "",
        "This repo's share of OverSteward's `estate-map.yaml`. A wrong row is fixed in the map, "
        "never here.",
        "",
        "## Capabilities (`id` · status · purpose, then current → target shape)",
        "",
        "Each current shape is its first sentence; the full measurement is in the map.",
        "",
    ]
    for cap in caps:
        lines.append(f"- `{cap.id}` · {cap.status} · {cap.purpose.strip()}")
        lines.append(f"  - {_headline(cap.current_shape)} → {cap.target_shape.strip()}")
    lines += _section("Seams", [f"- {s.id} {s.label}: {s.flows.strip()}" for s in seams])
    lines += _section(
        "Invariants", [f"- {i.id}: {i.text.strip()} ({i.cite.strip()})" for i in invariants]
    )
    lines += _section(
        "Liabilities",
        [f"- {i.id} ({i.owner}; {i.tracking.strip()}): {i.text.strip()}" for i in liabilities],
    )
    return "\n".join(lines) + "\n"


def _headline(shape: str) -> str:
    """A shape's first sentence: the measurement. The rest stays in the map."""
    return _SENTENCE_END.split(shape.strip(), maxsplit=1)[0]


def _section(title: str, rows: list[str]) -> list[str]:
    return ["", f"## {title}", "", *(rows or ["none"])]

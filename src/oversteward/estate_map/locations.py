# ABOUTME: The locations check — every claim and repo-typed location must exist on the tree its repo ships.
# ABOUTME: `unverified: true` locations are counted and printed, never read; a repo that cannot be read is exit 2.

from __future__ import annotations

from collections import defaultdict

from .checkouts import CouldNotLook, TreeReader
from .model import EstateMap
from .outcome import Finding, Outcome
from .validate import REPO_LOCATION_TYPES, split_location


def check_locations(estate: EstateMap, reader: TreeReader) -> Outcome:
    wanted, unverified = _wanted(estate)
    if not wanted:
        return Outcome(could_not_look=("no claims or repo locations to check",))
    findings: list[Finding] = []
    blind: list[str] = []
    checked = 0
    for repo, owners in sorted(wanted.items()):
        try:
            present = reader.existing(repo, owners)
        except CouldNotLook as exc:
            blind.append(str(exc))
            continue
        checked += len(owners)
        for path, caps in sorted(owners.items()):
            if path.rstrip("/") not in present:
                for cap in caps:
                    findings.append(Finding("missing-path", cap, f"{repo}:{path} is not on the tree read"))
    note = (
        f"locations: {checked} paths checked across {len(wanted) - len(blind)} repos; "
        f"{unverified} unverified locations counted, not checked"
    )
    return Outcome(tuple(findings), tuple(blind), (note,))


def _wanted(estate: EstateMap) -> tuple[dict[str, dict[str, list[str]]], int]:
    """repo -> path -> capabilities naming it, plus the count of unverified locations."""
    wanted: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    unverified = 0
    for cap in estate.capabilities:
        for repo, paths in cap.claims.items():
            for path in paths:
                wanted[repo][path].append(cap.id)
        for loc in cap.locations:
            if loc.unverified:
                unverified += 1
                continue
            parts = split_location(loc) if loc.type in REPO_LOCATION_TYPES else None
            if parts is not None:
                wanted[parts[0]][parts[1]].append(cap.id)
    return wanted, unverified

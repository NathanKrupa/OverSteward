# ABOUTME: Semantic checks on a parsed estate map — every finding names its entry; nothing is silently dropped.
# ABOUTME: Pure: takes the map and the registry's context ids, returns findings.

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Collection, Iterable, Iterator

from .coverage import COVERAGE_ROOTS
from .model import Capability, EstateMap, Location
from .outcome import Finding

KINDS = frozenset({"code", "process", "content"})
STATUSES = frozenset({"planned", "building", "live", "retired"})
INVARIANT_STATUSES = frozenset({"live", "retired"})

#: Location types whose ref is `<repo>:<path>` and can be read from a git tree.
REPO_LOCATION_TYPES = frozenset({"path", "report", "workflow", "timer"})
#: Location types no git tree holds. They must say so with `unverified: true`.
OFF_REPO_LOCATION_TYPES = frozenset({"vault", "todoist", "dashboard"})

#: A seam party that is not an estate repo (Railway, Sentry, GA4) is written `ext:<name>`.
EXTERNAL_PREFIX = "ext:"

_CAPABILITY_ID = re.compile(r"^(?P<product>[a-z][a-z0-9]*)\.[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate(estate: EstateMap, registry_ids: Collection[str]) -> list[Finding]:
    return [
        *_duplicates(estate),
        *_registry(estate, registry_ids),
        *_floor_keys(estate),
        *_capability_shapes(estate),
        *_references(estate),
        *_link_agreement(estate),
        *_orphans(estate),
        *_explicit_only(estate),
        *_locations(estate),
    ]


def split_location(location: Location) -> tuple[str, str] | None:
    """`(repo, path)` for a repo-typed location written `<repo>:<path>`, else None."""
    repo, sep, path = location.ref.partition(":")
    if not sep or not repo or not path:
        return None
    return repo, path


def _duplicates(estate: EstateMap) -> Iterator[Finding]:
    groups = {
        "capability": (c.id for c in estate.capabilities),
        "seam": (s.id for s in estate.seams),
        "invariant": (i.id for i in estate.invariants),
        "liability": (item.id for item in estate.liabilities),
        "repo": (r.id for r in estate.repos),
        "product": (p.id for p in estate.products),
    }
    for kind, ids in groups.items():
        for ident, count in Counter(ids).items():
            if count > 1:
                yield Finding("duplicate-id", ident, f"{kind} id appears {count} times")


def _registry(estate: EstateMap, registry_ids: Collection[str]) -> Iterator[Finding]:
    for repo in estate.repos:
        if repo.id not in registry_ids:
            yield Finding("registry", repo.id, "repo id is not a registry.yaml context id")


def _floor_keys(estate: EstateMap) -> Iterator[Finding]:
    """A measurable repo must say `null` to be unmeasured; an absent key would skip it unseen."""
    for repo in estate.repos:
        if repo.id in COVERAGE_ROOTS and repo.id not in estate.policy.coverage_floor:
            yield Finding(
                "coverage-floor-key", repo.id, "repo has coverage roots but no policy.coverage_floor key"
            )


def _capability_shapes(estate: EstateMap) -> Iterator[Finding]:
    products = {p.id for p in estate.products}
    for cap in estate.capabilities:
        match = _CAPABILITY_ID.match(cap.id)
        if match is None or match["product"] not in products:
            yield Finding("id-format", cap.id, "id must be <product>.<kebab> with a known product")
        if cap.kind not in KINDS:
            yield Finding("unknown-value", cap.id, f"kind {cap.kind!r} not in {sorted(KINDS)}")
        if cap.status not in STATUSES:
            yield Finding("unknown-value", cap.id, f"status {cap.status!r} not in {sorted(STATUSES)}")
        if not cap.target_shape.strip():
            yield Finding("target-shape", cap.id, "target_shape is required (prose, or `hold`)")
        if not cap.current_shape.strip():
            yield Finding("current-shape", cap.id, "current_shape is required")
    for inv in estate.invariants:
        if inv.status not in INVARIANT_STATUSES:
            yield Finding("unknown-value", inv.id, f"status {inv.status!r} not in {sorted(INVARIANT_STATUSES)}")


def _references(estate: EstateMap) -> Iterator[Finding]:
    caps = {c.id for c in estate.capabilities}
    invariants = {i.id for i in estate.invariants}
    liabilities = {item.id for item in estate.liabilities}
    repos = {r.id for r in estate.repos}
    for product in estate.products:
        yield from _missing(product.id, "repo", [product.repo], repos)
    for cap in estate.capabilities:
        for field in ("serves", "depends_on", "feeds"):
            yield from _missing(cap.id, field, getattr(cap, field), caps)
        yield from _missing(cap.id, "invariants", cap.invariants, invariants)
        yield from _missing(cap.id, "liabilities", cap.liabilities, liabilities)
        yield from _missing(cap.id, "claims", cap.claims, repos)
    for seam in estate.seams:
        parties = [p for p in (*seam.producer, *seam.consumer) if not p.startswith(EXTERNAL_PREFIX)]
        yield from _missing(seam.id, "producer/consumer", parties, repos)
        yield from _missing(seam.id, "invariants", seam.invariants, invariants)
        yield from _missing(seam.id, "liabilities", seam.liabilities, liabilities)
    for inv in estate.invariants:
        yield from _missing(inv.id, "capabilities", inv.capabilities, caps)
    for item in estate.liabilities:
        yield from _missing(item.id, "capabilities", item.capabilities, caps)


def _missing(subject: str, field: str, refs: Iterable[str], known: Collection[str]) -> Iterator[Finding]:
    for ref in refs:
        if ref not in known:
            yield Finding("dangling-ref", subject, f"`{field}` names {ref!r}, which is not defined")


def _link_agreement(estate: EstateMap) -> Iterator[Finding]:
    """An invariant's or liability's `capabilities` must equal the capabilities citing it."""
    tables = (
        (estate.invariants, lambda c: c.invariants),
        (estate.liabilities, lambda c: c.liabilities),
    )
    for rows, cited in tables:
        for row in rows:
            citing = {c.id for c in estate.capabilities if row.id in cited(c)}
            if citing != set(row.capabilities):
                yield Finding(
                    "link-mismatch",
                    row.id,
                    f"lists capabilities {sorted(row.capabilities)}, cited by {sorted(citing)}",
                )


def _orphans(estate: EstateMap) -> Iterator[Finding]:
    cited_invariants = {ref for c in estate.capabilities for ref in c.invariants}
    cited_invariants |= {ref for s in estate.seams for ref in s.invariants}
    cited_liabilities = {ref for c in estate.capabilities for ref in c.liabilities}
    cited_liabilities |= {ref for s in estate.seams for ref in s.liabilities}
    for inv in estate.invariants:
        if inv.status == "live" and inv.id not in cited_invariants:
            yield Finding("orphan", inv.id, "live invariant cited by no capability or seam")
    for item in estate.liabilities:
        if item.id not in cited_liabilities:
            yield Finding("orphan", item.id, "liability cited by no capability or seam")


def _explicit_only(estate: EstateMap) -> Iterator[Finding]:
    """Under an explicit-only root every claim names one file, so coverage cannot be vacuous."""
    for cap in estate.capabilities:
        for repo, paths in cap.claims.items():
            for root in estate.policy.explicit_only.get(repo, ()):
                for path in paths:
                    if _claims_subtree_of(path, root):
                        yield Finding(
                            "explicit-only",
                            cap.id,
                            f"{repo}:{path} is not a file claim under explicit-only {root}",
                        )


def _claims_subtree_of(path: str, root: str) -> bool:
    """True when `path` is a directory claim at, inside, or above `root`."""
    clean = path.rstrip("/")
    base = root.rstrip("/")
    if is_file_claim(path) and clean.startswith(base + "/"):
        return False
    inside = clean == base or clean.startswith(base + "/")
    above = base.startswith(clean + "/")
    return inside or above


def is_file_claim(path: str) -> bool:
    """A claim names a file when it does not end in `/` and its last segment has a suffix."""
    return not path.endswith("/") and "." in path.rsplit("/", 1)[-1]


def _locations(estate: EstateMap) -> Iterator[Finding]:
    repos = {r.id for r in estate.repos}
    known = REPO_LOCATION_TYPES | OFF_REPO_LOCATION_TYPES
    for cap in estate.capabilities:
        for loc in cap.locations:
            yield from _location(cap, loc, repos, known)


def _location(cap: Capability, loc: Location, repos: Collection[str], known: Collection[str]) -> Iterator[Finding]:
    if loc.type not in known:
        yield Finding("unknown-value", cap.id, f"location type {loc.type!r} not in {sorted(known)}")
    elif loc.type in OFF_REPO_LOCATION_TYPES and not loc.unverified:
        yield Finding("location", cap.id, f"{loc.type} location {loc.ref!r} must be `unverified: true`")
    elif loc.type in REPO_LOCATION_TYPES:
        parts = split_location(loc)
        if parts is None:
            yield Finding("location", cap.id, f"{loc.type} location {loc.ref!r} must be `<repo>:<path>`")
        elif parts[0] not in repos:
            yield Finding("location", cap.id, f"{loc.type} location names unknown repo {parts[0]!r}")

# ABOUTME: Coverage — every tracked module under a repo's roots claimed by exactly one capability.
# ABOUTME: The floor is compared both ways: a breach is a finding, and so is an improvement the floor has not recorded.

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from .checkouts import CouldNotLook
from .model import EstateMap, Floor
from .outcome import Finding, Outcome

#: Where a repo's modules live. A repo absent here has no coverage to measure.
COVERAGE_ROOTS: dict[str, tuple[str, ...]] = {
    "oversteward": ("src/oversteward/",),
    "grantspider": ("src/grantspider/",),
    "aigranthelper": ("apps/",),
}
#: Path segments below a root that hold no product modules.
EXCLUDED_SEGMENTS: dict[str, frozenset[str]] = {
    "aigranthelper": frozenset({"migrations", "tests"}),
}
LARGEST_SHOWN = 10

#: Lists every tracked file under the given roots of a repo; raises CouldNotLook.
Lister = Callable[[str, Sequence[str]], Iterable[str]]


@dataclass(frozen=True)
class Coverage:
    repo: str
    modules: tuple[str, ...]
    orphans: tuple[str, ...]
    #: module -> the capabilities claiming it, when more than one does.
    overlaps: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: (capability, modules claimed), largest first.
    claim_sizes: tuple[tuple[str, int], ...] = ()
    holds: int = 0


def modules(repo: str, files: Iterable[str]) -> list[str]:
    """Tracked `.py` files under the repo's roots, minus excluded segments. KeyError if no roots."""
    roots = COVERAGE_ROOTS[repo]
    excluded = EXCLUDED_SEGMENTS.get(repo, frozenset())
    found = []
    for path in files:
        root = next((r for r in roots if path.startswith(r)), None)
        if root is None or not path.endswith(".py"):
            continue
        if excluded & set(path[len(root) :].split("/")[:-1]):
            continue
        found.append(path)
    return sorted(found)


def claims_path(claim: str, path: str) -> bool:
    """A claim covers `path` when it is that file or an ancestor directory of it."""
    base = claim.rstrip("/")
    return path == base or path.startswith(base + "/")


def measure(estate: EstateMap, repo: str, files: Iterable[str]) -> Coverage:
    mods = modules(repo, files)
    claimants = [c for c in estate.capabilities if c.claims.get(repo)]
    owners: dict[str, list[str]] = {m: [] for m in mods}
    sizes: dict[str, int] = {c.id: 0 for c in claimants}
    for cap in claimants:
        for mod in mods:
            if any(claims_path(claim, mod) for claim in cap.claims[repo]):
                owners[mod].append(cap.id)
                sizes[cap.id] += 1
    ranked = sorted(sizes.items(), key=lambda item: (-item[1], item[0]))
    return Coverage(
        repo=repo,
        modules=tuple(mods),
        orphans=tuple(m for m, caps in owners.items() if not caps),
        overlaps={m: tuple(sorted(caps)) for m, caps in owners.items() if len(caps) > 1},
        claim_sizes=tuple(ranked),
        holds=sum(1 for c in claimants if c.is_hold),
    )


def compare(cov: Coverage, floor: Floor) -> list[Finding]:
    findings = []
    for name, measured, recorded, names in (
        ("orphans", len(cov.orphans), floor.orphans, cov.orphans),
        ("overlaps", len(cov.overlaps), floor.overlaps, tuple(cov.overlaps)),
    ):
        if measured > recorded:
            listed = ", ".join(names)
            findings.append(
                Finding("coverage-floor", cov.repo, f"{name} {measured} above floor {recorded}: {listed}")
            )
        elif measured < recorded:
            findings.append(
                Finding(
                    "coverage-floor",
                    cov.repo,
                    f"{name} {measured} below floor {recorded}: lower the floor to {measured}",
                )
            )
    return findings


def coverage_outcome(estate: EstateMap, repo: str, lister: Lister) -> Outcome:
    if repo not in COVERAGE_ROOTS:
        return Outcome(could_not_look=(f"{repo}: no coverage roots are defined",))
    if not any(c.claims.get(repo) for c in estate.capabilities):
        return Outcome(could_not_look=(f"{repo}: no capability claims a path in this repo",))
    try:
        files = list(lister(repo, COVERAGE_ROOTS[repo]))
    except CouldNotLook as exc:
        return Outcome(could_not_look=(str(exc),))
    cov = measure(estate, repo, files)
    if not cov.modules:
        return Outcome(could_not_look=(f"{repo}: no modules found under {COVERAGE_ROOTS[repo]}",))
    floor = estate.policy.coverage_floor.get(repo)
    findings = compare(cov, floor) if floor is not None else []
    return Outcome(tuple(findings), (), tuple(summary(cov, floor)))


def summary(cov: Coverage, floor: Floor | None) -> list[str]:
    recorded = "unmeasured" if floor is None else f"orphans {floor.orphans}, overlaps {floor.overlaps}"
    lines = [
        f"coverage {cov.repo}: {len(cov.modules)} modules, {len(cov.claim_sizes)} claiming capabilities, "
        f"{len(cov.orphans)} orphans, {len(cov.overlaps)} overlaps, {cov.holds} holds (floor: {recorded})",
    ]
    lines += [f"  orphan {m}" for m in cov.orphans]
    lines += [f"  overlap {m}: {', '.join(caps)}" for m, caps in cov.overlaps.items()]
    lines += [f"  largest {cap}: {n}" for cap, n in cov.claim_sizes[:LARGEST_SHOWN]]
    return lines

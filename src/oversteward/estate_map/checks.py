# ABOUTME: The estate-map commands as outcomes — validate, locations, coverage, and check (all three).
# ABOUTME: The OUTER script parses arguments and prints; which repos are measured is decided here.

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .checkouts import TreeReader
from .coverage import coverage_outcome
from .locations import check_locations
from .model import EstateMap
from .outcome import Outcome, combine
from .validate import validate


def registry_ids(registry: Mapping[str, Any]) -> list[str]:
    return [str(ctx.get("id")) for ctx in registry.get("contexts") or []]


def validate_outcome(estate: EstateMap, registry: Mapping[str, Any]) -> Outcome:
    findings = validate(estate, registry_ids(registry))
    note = (
        f"validate: {len(estate.capabilities)} capabilities, {len(estate.seams)} seams, "
        f"{len(estate.invariants)} invariants, {len(estate.liabilities)} liabilities"
    )
    return Outcome(tuple(findings), (), (note,))


def coverage_repos(estate: EstateMap, requested: str | None) -> list[str]:
    """The named repo, else every repo whose floor is measured. Unmeasured floors are printed, not read."""
    if requested is not None:
        return [requested]
    return [repo for repo, floor in estate.policy.coverage_floor.items() if floor is not None]


def coverage_report(estate: EstateMap, reader: TreeReader, repos: Sequence[str]) -> Outcome:
    if not repos:
        return Outcome(could_not_look=("coverage: no repo has a measured floor",))
    unmeasured = [r for r, f in estate.policy.coverage_floor.items() if f is None and r not in repos]
    notes = tuple(f"coverage {r}: unmeasured (floor is null)" for r in unmeasured)
    return combine([*(coverage_outcome(estate, r, reader.files) for r in repos), Outcome(notes=notes)])


def check(estate: EstateMap, registry: Mapping[str, Any], reader: TreeReader) -> Outcome:
    return combine(
        [
            validate_outcome(estate, registry),
            check_locations(estate, reader),
            coverage_report(estate, reader, coverage_repos(estate, None)),
        ]
    )


def run(
    command: str,
    estate: EstateMap,
    registry: Mapping[str, Any],
    reader: TreeReader,
    *,
    repo: str | None = None,
) -> Outcome:
    if command == "validate":
        return validate_outcome(estate, registry)
    if command == "locations":
        return check_locations(estate, reader)
    if command == "coverage":
        return coverage_report(estate, reader, coverage_repos(estate, repo))
    if command == "check":
        return check(estate, registry, reader)
    raise ValueError(f"unknown estate-map command {command!r}")

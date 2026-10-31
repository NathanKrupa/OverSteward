# ABOUTME: Typed shapes for estate-map.yaml — capabilities, seams, invariants, liabilities — and its loader.
# ABOUTME: Parsing only: a structurally broken map raises MapError; every semantic check lives in validate.

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: The value `target_shape` takes when no edit is planned. Counted and printed,
#: never treated as absent.
HOLD = "hold"


class MapError(ValueError):
    """The map's structure cannot be read. Always names the entry and field."""


@dataclass(frozen=True)
class Location:
    type: str
    ref: str
    unverified: bool = False


@dataclass(frozen=True)
class Capability:
    id: str
    kind: str
    purpose: str
    status: str
    current_shape: str
    target_shape: str
    serves: tuple[str, ...] = ()
    claims: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    locations: tuple[Location, ...] = ()
    entry_points: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    feeds: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    liabilities: tuple[str, ...] = ()

    @property
    def is_hold(self) -> bool:
        return self.target_shape.strip() == HOLD


@dataclass(frozen=True)
class Seam:
    id: str
    label: str
    producer: tuple[str, ...]
    consumer: tuple[str, ...]
    flows: str
    cite: str
    invariants: tuple[str, ...] = ()
    liabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class Invariant:
    id: str
    status: str
    text: str
    cite: str
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class Liability:
    id: str
    text: str
    owner: str
    tracking: str
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class Repo:
    id: str
    purpose: str
    stack: str
    surfaces: str = ""


@dataclass(frozen=True)
class Product:
    id: str
    serves: str
    repo: str


@dataclass(frozen=True)
class Floor:
    orphans: int
    overlaps: int


@dataclass(frozen=True)
class Policy:
    digest_budget_bytes: int
    explicit_only: Mapping[str, tuple[str, ...]]
    #: None means the repo's coverage is unmeasured; it is printed, never compared.
    coverage_floor: Mapping[str, Floor | None]


@dataclass(frozen=True)
class EstateMap:
    version: int
    north_star: str
    products: tuple[Product, ...]
    policy: Policy
    repos: tuple[Repo, ...]
    capabilities: tuple[Capability, ...]
    seams: tuple[Seam, ...]
    invariants: tuple[Invariant, ...]
    liabilities: tuple[Liability, ...]


def load(path: Path) -> EstateMap:
    """Read and parse the map at `path`. A missing file raises FileNotFoundError."""
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))


def parse(data: Any) -> EstateMap:
    if not isinstance(data, Mapping):
        raise MapError("estate map: the document is not a mapping")
    mission = _mapping(data, "mission", "estate map")
    policy = _mapping(data, "policy", "estate map")
    return EstateMap(
        version=int(_require(data, "version", "estate map")),
        north_star=str(_require(mission, "north_star", "mission")),
        products=tuple(_product(p) for p in _list(mission, "products", "mission")),
        policy=_policy(policy),
        repos=tuple(_repo(r) for r in _list(data, "repos", "estate map")),
        capabilities=tuple(_capability(c) for c in _list(data, "capabilities", "estate map")),
        seams=tuple(_seam(s) for s in _list(data, "seams", "estate map")),
        invariants=tuple(_invariant(i) for i in _list(data, "invariants", "estate map")),
        liabilities=tuple(_liability(item) for item in _list(data, "liabilities", "estate map")),
    )


def _require(entry: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in entry or entry[key] is None:
        raise MapError(f"{where}: missing required field `{key}`")
    return entry[key]


def _mapping(entry: Mapping[str, Any], key: str, where: str) -> Mapping[str, Any]:
    value = _require(entry, key, where)
    if not isinstance(value, Mapping):
        raise MapError(f"{where}: `{key}` is not a mapping")
    return value


def _list(entry: Mapping[str, Any], key: str, where: str) -> list[Mapping[str, Any]]:
    value = entry.get(key) or []
    if not isinstance(value, list) or not all(isinstance(v, Mapping) for v in value):
        raise MapError(f"{where}: `{key}` is not a list of mappings")
    return value


def _strings(entry: Mapping[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = entry.get(key) or []
    if isinstance(value, str) or not isinstance(value, list):
        raise MapError(f"{where}: `{key}` is not a list")
    return tuple(str(v) for v in value)


def _ident(entry: Mapping[str, Any], where: str) -> str:
    return str(_require(entry, "id", where))


def _product(entry: Mapping[str, Any]) -> Product:
    where = f"product {entry.get('id')!r}"
    return Product(
        id=_ident(entry, where),
        serves=str(_require(entry, "serves", where)),
        repo=str(_require(entry, "repo", where)),
    )


def _policy(entry: Mapping[str, Any]) -> Policy:
    explicit = entry.get("explicit_only") or {}
    floors = entry.get("coverage_floor") or {}
    if not isinstance(explicit, Mapping) or not isinstance(floors, Mapping):
        raise MapError("policy: `explicit_only` and `coverage_floor` must be mappings")
    return Policy(
        digest_budget_bytes=int(_require(entry, "digest_budget_bytes", "policy")),
        explicit_only={repo: _strings(explicit, repo, "policy.explicit_only") for repo in explicit},
        coverage_floor={repo: _floor(repo, floors[repo]) for repo in floors},
    )


def _floor(repo: str, value: Any) -> Floor | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise MapError(f"policy.coverage_floor.{repo}: must be null or a mapping")
    where = f"policy.coverage_floor.{repo}"
    return Floor(
        orphans=int(_require(value, "orphans", where)),
        overlaps=int(_require(value, "overlaps", where)),
    )


def _repo(entry: Mapping[str, Any]) -> Repo:
    where = f"repo {entry.get('id')!r}"
    return Repo(
        id=_ident(entry, where),
        purpose=str(_require(entry, "purpose", where)),
        stack=str(_require(entry, "stack", where)),
        surfaces=str(entry.get("surfaces") or ""),
    )


def _capability(entry: Mapping[str, Any]) -> Capability:
    where = f"capability {entry.get('id')!r}"
    claims = entry.get("claims") or {}
    if not isinstance(claims, Mapping):
        raise MapError(f"{where}: `claims` is not a mapping of repo to paths")
    return Capability(
        id=_ident(entry, where),
        kind=str(_require(entry, "kind", where)),
        purpose=str(_require(entry, "purpose", where)),
        status=str(_require(entry, "status", where)),
        current_shape=str(entry.get("current_shape") or ""),
        target_shape=str(entry.get("target_shape") or ""),
        serves=_strings(entry, "serves", where),
        claims={repo: _strings(claims, repo, f"{where} claims") for repo in claims},
        locations=tuple(_location(loc, where) for loc in _list(entry, "locations", where)),
        entry_points=_strings(entry, "entry_points", where),
        depends_on=_strings(entry, "depends_on", where),
        feeds=_strings(entry, "feeds", where),
        invariants=_strings(entry, "invariants", where),
        liabilities=_strings(entry, "liabilities", where),
    )


def _location(entry: Mapping[str, Any], where: str) -> Location:
    return Location(
        type=str(_require(entry, "type", f"{where} location")),
        ref=str(_require(entry, "ref", f"{where} location")),
        unverified=bool(entry.get("unverified", False)),
    )


def _seam(entry: Mapping[str, Any]) -> Seam:
    where = f"seam {entry.get('id')!r}"
    return Seam(
        id=_ident(entry, where),
        label=str(_require(entry, "label", where)),
        producer=_strings(entry, "producer", where),
        consumer=_strings(entry, "consumer", where),
        flows=str(_require(entry, "flows", where)),
        cite=str(_require(entry, "cite", where)),
        invariants=_strings(entry, "invariants", where),
        liabilities=_strings(entry, "liabilities", where),
    )


def _invariant(entry: Mapping[str, Any]) -> Invariant:
    where = f"invariant {entry.get('id')!r}"
    return Invariant(
        id=_ident(entry, where),
        status=str(_require(entry, "status", where)),
        text=str(_require(entry, "text", where)),
        cite=str(_require(entry, "cite", where)),
        capabilities=_strings(entry, "capabilities", where),
    )


def _liability(entry: Mapping[str, Any]) -> Liability:
    where = f"liability {entry.get('id')!r}"
    return Liability(
        id=_ident(entry, where),
        text=str(_require(entry, "text", where)),
        owner=str(_require(entry, "owner", where)),
        tracking=str(_require(entry, "tracking", where)),
        capabilities=_strings(entry, "capabilities", where),
    )

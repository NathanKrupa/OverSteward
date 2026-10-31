# ABOUTME: What the estate is working on, per capability — open issues and PRs attributed at read time, never stored.
# ABOUTME: Priority: a `Capability:` body line, then a PR's changed files, then repo paths named in title or body.

"""Attribute open GitHub work to estate-map capabilities.

Nothing here is written back: the attribution is derived from the map's claims
every time it is read, so it can never drift from them. The tiers run in order
and the first that names a capability decides:

1. ``explicit`` — a ``Capability: <id>[, <id>]`` line in the body. Ids the map
   does not hold are reported and ignored, so a typo falls through to inference.
2. ``files`` — a PR's changed files, each matched as a full repo-relative path
   against the longest claim covering it.
3. ``paths`` — paths named in the title or body. A named path may be partial
   (``services/website_resolver.py``) or absolute, so it matches a claim whose
   trailing segments line up with its leading ones, or a claim it contains
   whole; the claim aligning the most segments wins. A partial match must align
   two segments, unless it is a bare filename only one capability claims.
4. ``unmapped`` — none of the above. Counted and listed, never hidden.

An item may land on several capabilities; it is counted under each, and the
multi-mapped count says how often.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .checkouts import CouldNotLook
from .model import EstateMap

EXPLICIT = "explicit"
FILES = "files"
PATHS = "paths"
UNMAPPED = "unmapped"

_EXPLICIT_LINE = re.compile(r"^[ \t>*-]*\**Capability\**\s*:\s*\**(?P<ids>.*?)\**\s*$", re.I | re.M)
_ID_SPLIT = re.compile(r"[,\s]+")
#: A GitHub blob or tree link's prefix; what follows it is a repo-relative path.
_GITHUB_LINK = re.compile(r"https?://github\.com/[^/\s]+/[^/\s]+/(?:blob|tree)/[^/\s]+/")
_URL = re.compile(r"\w+://\S+")
_TOKEN = re.compile(r"[\w./-]+")
#: A token names a path when it holds a slash or ends in a file extension.
_FILE_EXT = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,7}$")

#: Every open item in one repo; raises CouldNotLook when the repo cannot be read.
Fetch = Callable[[str], Sequence["Item"]]


@dataclass(frozen=True)
class Item:
    repo: str
    #: "issue" or "pr".
    kind: str
    number: int
    title: str
    body: str
    #: A PR's changed files, repo-relative; empty for an issue.
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class Attribution:
    capabilities: tuple[str, ...]
    via: str
    unknown_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Report:
    repos: tuple[str, ...]
    #: Capability ids in map order, so the printed report follows the map.
    order: tuple[str, ...]
    rows: tuple[tuple[Item, Attribution], ...] = field(default_factory=tuple)


def explicit_ids(body: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _EXPLICIT_LINE.finditer(body):
        for raw in _ID_SPLIT.split(match.group("ids")):
            ident = raw.strip("`*_")
            if ident and ident not in found:
                found.append(ident)
    return tuple(found)


def mentioned_paths(text: str) -> list[str]:
    text = _URL.sub(" ", _GITHUB_LINK.sub(" ", text))
    found: list[str] = []
    for token in _TOKEN.findall(text):
        path = token.rstrip(".").removeprefix("./").strip("/")
        if path and ("/" in path or _FILE_EXT.search(path)) and path not in found:
            found.append(path)
    return found


def _aligned(claim: str, path: str, *, partial: bool) -> int:
    """How many of the claim's segments line up with `path`; 0 when they do not.

    Full alignment means the claim is `path` or an ancestor of it. A named path
    may also be partial or absolute, so it aligns when some trailing run of the
    claim's segments equals its leading ones (``services/x.py``), or when the
    whole claim appears inside it (``/home/natha/grantspider/src/.../x.py``).
    """
    claim_parts = claim.strip("/").split("/")
    path_parts = path.strip("/").split("/")
    if not partial:
        return len(claim_parts) if path_parts[: len(claim_parts)] == claim_parts else 0
    for start in range(len(claim_parts)):
        tail = claim_parts[start:]
        offsets = range(len(path_parts) - len(tail) + 1) if start == 0 else range(1)
        if any(path_parts[k : k + len(tail)] == tail for k in offsets):
            return len(tail)
    return 0


def _claims(estate: EstateMap, repo: str) -> list[tuple[str, str]]:
    return [(cap.id, claim) for cap in estate.capabilities for claim in cap.claims.get(repo, ())]


def _match(claims: Sequence[tuple[str, str]], paths: Iterable[str], *, partial: bool) -> list[str]:
    hits: list[str] = []
    for path in paths:
        scored = [(_aligned(claim, path, partial=partial), cap) for cap, claim in claims]
        best = max((score for score, _ in scored), default=0)
        winners = {cap for score, cap in scored if score == best}
        if best and (best > 1 or not partial or _unambiguous_basename(path, winners)):
            hits.extend(cap for cap in sorted(winners) if cap not in hits)
    return hits


def _unambiguous_basename(path: str, winners: set[str]) -> bool:
    """A one-segment partial match counts only for a bare filename exactly one capability claims.

    One shared segment is otherwise noise: ``docs/x.md`` at a repo's top level is
    not ``apps/docs/``, and ``models.py`` names a file in every app.
    """
    return "/" not in path and len(winners) == 1


def attribute(item: Item, estate: EstateMap) -> Attribution:
    known = {cap.id for cap in estate.capabilities}
    named = explicit_ids(item.body)
    unknown = tuple(i for i in named if i not in known)
    explicit = tuple(i for i in named if i in known)
    if explicit:
        return Attribution(explicit, EXPLICIT, unknown)
    claims = _claims(estate, item.repo)
    by_files = _match(claims, item.files, partial=False)
    if by_files:
        return Attribution(_in_map_order(estate, by_files), FILES, unknown)
    by_paths = _match(claims, mentioned_paths(f"{item.title}\n{item.body}"), partial=True)
    if by_paths:
        return Attribution(_in_map_order(estate, by_paths), PATHS, unknown)
    return Attribution((), UNMAPPED, unknown)


def _in_map_order(estate: EstateMap, ids: Iterable[str]) -> tuple[str, ...]:
    wanted = set(ids)
    return tuple(cap.id for cap in estate.capabilities if cap.id in wanted)


def status_repos(estate: EstateMap, requested: str | None) -> list[str]:
    """The named repo, else every map repo some capability claims a path in, in map order."""
    if requested is not None:
        return [requested]
    claimed = {repo for cap in estate.capabilities for repo, paths in cap.claims.items() if paths}
    return [repo.id for repo in estate.repos if repo.id in claimed]


def gather(repos: Sequence[str], fetch: Fetch) -> tuple[list[Item], list[str]]:
    """Every open item across `repos`, and the reason for each repo that could not be read."""
    items: list[Item] = []
    blind: list[str] = []
    for repo in repos:
        try:
            items.extend(fetch(repo))
        except CouldNotLook as exc:
            blind.append(str(exc))
    return items, blind


def build(estate: EstateMap, repos: Sequence[str], items: Iterable[Item]) -> Report:
    rows = tuple((item, attribute(item, estate)) for item in items)
    return Report(tuple(repos), tuple(cap.id for cap in estate.capabilities), rows)


def to_dict(report: Report) -> dict[str, Any]:
    repos = {
        repo: {
            "issues": sum(1 for i, _ in report.rows if i.repo == repo and i.kind == "issue"),
            "prs": sum(1 for i, _ in report.rows if i.repo == repo and i.kind == "pr"),
            "unmapped": sum(1 for i, a in report.rows if i.repo == repo and not a.capabilities),
        }
        for repo in report.repos
    }
    capabilities = {
        cap: [_entry(i, a) for i, a in report.rows if cap in a.capabilities]
        for cap in report.order
        if any(cap in a.capabilities for _, a in report.rows)
    }
    return {
        "repos": repos,
        "capabilities": capabilities,
        "unmapped": [_entry(i, a) for i, a in report.rows if not a.capabilities],
        "multi_mapped": sum(1 for _, a in report.rows if len(a.capabilities) > 1),
        "unknown_ids": [
            {"repo": i.repo, "kind": i.kind, "number": i.number, "id": unknown}
            for i, a in report.rows
            for unknown in a.unknown_ids
        ],
    }


def _entry(item: Item, attribution: Attribution) -> dict[str, Any]:
    return {
        "repo": item.repo,
        "kind": item.kind,
        "number": item.number,
        "title": item.title,
        "via": attribution.via,
    }


def lines(report: Report) -> list[str]:
    data = to_dict(report)
    out = []
    for repo, n in data["repos"].items():
        total = n["issues"] + n["prs"]
        ratio = f" ({100 * n['unmapped'] // total}%)" if total else ""
        out.append(
            f"status {repo}: {total} open ({n['issues']} issues, {n['prs']} PRs), "
            f"{n['unmapped']} unmapped{ratio}"
        )
    for cap, entries in data["capabilities"].items():
        out.append(f"{cap}: {len(entries)} open")
        for repo in report.repos:
            mine = [e for e in entries if e["repo"] == repo]
            if mine:
                out.append(f"  {repo}")
                out += [f"    {e['kind']} #{e['number']} {e['title']} [{e['via']}]" for e in mine]
    out.append(f"unmapped: {len(data['unmapped'])}")
    out += [f"  {e['repo']} {e['kind']} #{e['number']} {e['title']}" for e in data["unmapped"]]
    out.append(f"multi-mapped: {data['multi_mapped']}")
    out += [
        f"unknown capability id {u['id']!r} on {u['repo']} {u['kind']} #{u['number']} (ignored)"
        for u in data["unknown_ids"]
    ]
    return out

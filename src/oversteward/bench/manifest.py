# ABOUTME: MIDDLE layer — builds a page_judge manifest for published bench variants, validated by the judge's own reader.
# ABOUTME: Pairs are every unordered combination; the judge itself runs each in both orders. No file is written here.

"""A judge manifest for a round of bench variants.

The document built here is the mapping ``scripts/page_judge.py`` reads, in
the key order ``reports/judge/manifests/example.yaml`` documents. It is run
through :func:`oversteward.judge.models.manifest_from_mapping` before it is
returned, so a manifest this module hands back is one the judge will accept.

``pairs`` lists each unordered pair once — n·(n−1)/2 of them for n variants.
Position bias is the judge's problem, not the manifest's: ``compare`` shows
every pair in both orders itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import combinations
from pathlib import Path
from typing import Any

from oversteward.bench.checks import html_pages
from oversteward.judge.models import DEFAULT_SAMPLES, Rubric, manifest_from_mapping

#: The bench judges whether a page answers a seeker's questions — Workstream B's rubric (OS#421).
DEFAULT_RUBRIC = Rubric.SEEKER.value


def all_pairs(urls: Iterable[str]) -> tuple[tuple[str, str], ...]:
    """Every unordered pair of ``urls``, each once, in listing order."""
    return tuple(combinations(tuple(urls), 2))


def page_urls(base_url: str, directory: Path) -> tuple[str, ...]:
    """The URL Pages serves each ``.html`` under ``directory`` at, beneath ``base_url``.

    ``index.html`` is its directory (``/``, ``/v2/``); any other ``.html``
    page is its extensionless path (``/v3``), the canonical form Pages
    redirects ``/v3.html`` to. Any other spelling (``.htm``, ``.HTML``) is
    served at its own path and listed as such.
    """
    base = base_url.rstrip("/")
    urls = []
    for page in html_pages(directory):
        relative = page.relative_to(directory)
        if relative.name == "index.html":
            parent = relative.parent.as_posix()
            urls.append(f"{base}/" if parent == "." else f"{base}/{parent}/")
        elif relative.suffix == ".html":
            urls.append(f"{base}/{relative.with_suffix('').as_posix()}")
        else:
            urls.append(f"{base}/{relative.as_posix()}")
    return tuple(urls)


def urls_from_listing(text: str) -> tuple[str, ...]:
    """One URL per line; blank lines and ``#`` comments are skipped, anything else is refused."""
    urls = []
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        if not candidate.startswith(("https://", "http://")):
            raise ValueError(f"not a URL: {candidate!r}")
        urls.append(candidate)
    return tuple(urls)


def build_manifest(
    *,
    name: str,
    page_type: str,
    urls: Iterable[str],
    pairs: bool,
    rubric: str = DEFAULT_RUBRIC,
    samples: int = DEFAULT_SAMPLES,
    facts: str | None = None,
) -> dict[str, Any]:
    """The manifest mapping, in the example's key order, already validated by the judge's reader.

    ``facts`` is a path to the JSON fixture the variants were rendered from,
    written against every URL — one round renders one fixture, so the same
    ground truth applies to each variant. It is stored as given; the judge
    resolves a relative path against the manifest's own directory.
    """
    listed = tuple(urls)
    if not listed:
        raise ValueError("a manifest needs at least one URL; no URLs were given")
    duplicates = sorted({url for url in listed if listed.count(url) > 1})
    if duplicates:
        raise ValueError(f"duplicate URL(s) in the manifest: {', '.join(duplicates)}")
    data: dict[str, Any] = {
        "name": name,
        "samples": samples,
        "rubric": rubric,
        "page_types": {page_type: list(listed)},
        "pairs": [list(pair) for pair in all_pairs(listed)] if pairs else [],
    }
    if facts is not None:
        data["ground_truth"] = dict.fromkeys(listed, facts)
    manifest_from_mapping(data)
    return data


__all__ = ["DEFAULT_RUBRIC", "all_pairs", "build_manifest", "page_urls", "urls_from_listing"]

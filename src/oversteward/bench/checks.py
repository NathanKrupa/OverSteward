# ABOUTME: The bench's fail-closed publish checks — every page noindexed, _headers and robots.txt in place.
# ABOUTME: Pure over a directory: it names every problem and decides nothing about uploading.

"""What a directory must carry before it may go to ab.aigranthelper.com.

The bench exists so page shapes can be judged without Google ever indexing
them, so the checks are content checks, not presence checks: a ``_headers``
that exists but sets no ``X-Robots-Tag`` is a guard satisfied by doing nothing.
Each check yields one reason per problem, and every reason is reported — an
operator fixing a bench directory should see the whole list once.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

HEADERS_FILE = "_headers"
ROBOTS_FILE = "robots.txt"

_NOINDEX_META = '<meta name="robots" content="noindex">'


class _RobotsMeta(HTMLParser):
    """Collects the ``content`` of every ``<meta name="robots">`` in a document."""

    def __init__(self) -> None:
        super().__init__()
        self.contents: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "meta":
            return
        found = {(name or "").lower(): value or "" for name, value in attrs}
        if found.get("name", "").strip().lower() == "robots":
            self.contents.append(found.get("content", ""))


def has_noindex_meta(html: str) -> bool:
    """True when a ``<meta name="robots">`` carries ``noindex`` as a whole directive."""
    parser = _RobotsMeta()
    parser.feed(html)
    return any(
        "noindex" in {directive.strip().lower() for directive in content.split(",")}
        for content in parser.contents
    )


def refusals(directory: Path) -> tuple[str, ...]:
    """Every reason ``directory`` may not be published, in a stable order; empty means it may."""
    if not directory.is_dir():
        raise NotADirectoryError(f"{directory} is not a directory")
    reasons: list[str] = []
    pages = sorted(directory.rglob("*.html"))
    if not pages:
        reasons.append(f"no .html files under {directory}")
    for page in pages:
        if not has_noindex_meta(page.read_text(encoding="utf-8", errors="replace")):
            reasons.append(f"{page.relative_to(directory).as_posix()} lacks {_NOINDEX_META}")
    reasons.extend(_headers_reasons(directory / HEADERS_FILE))
    reasons.extend(_robots_reasons(directory / ROBOTS_FILE))
    return tuple(reasons)


def _headers_reasons(headers: Path) -> list[str]:
    if not headers.is_file():
        return [f"{HEADERS_FILE} is missing"]
    for line in headers.read_text(encoding="utf-8", errors="replace").splitlines():
        name, sep, value = line.strip().partition(":")
        if sep and name.strip().lower() == "x-robots-tag" and "noindex" in value.lower():
            return []
    return [f"{HEADERS_FILE} sets no X-Robots-Tag: noindex"]


def _robots_reasons(robots: Path) -> list[str]:
    if not robots.is_file():
        return [f"{ROBOTS_FILE} is missing"]
    for line in robots.read_text(encoding="utf-8", errors="replace").splitlines():
        name, sep, value = line.strip().partition(":")
        if sep and name.strip().lower() == "disallow" and value.strip() == "/":
            return []
    return [f"{ROBOTS_FILE} carries no 'Disallow: /' line"]


__all__ = ["HEADERS_FILE", "ROBOTS_FILE", "has_noindex_meta", "refusals"]

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

#: Pages serves these as HTML whatever the case of the extension.
HTML_SUFFIXES = frozenset({".html", ".htm"})

_NOINDEX_META = '<meta name="robots" content="noindex">'
#: The one `_headers` path block that covers every page.
_CATCH_ALL_PATH = "/*"


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


def html_pages(directory: Path) -> tuple[Path, ...]:
    """Every file under ``directory`` that Pages would serve as HTML, in a stable order."""
    return tuple(
        sorted(path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in HTML_SUFFIXES)
    )


def refusals(directory: Path) -> tuple[str, ...]:
    """Every reason ``directory`` may not be published, in a stable order; empty means it may."""
    if not directory.is_dir():
        raise NotADirectoryError(f"{directory} is not a directory")
    reasons: list[str] = []
    pages = html_pages(directory)
    if not pages:
        reasons.append(f"no .html files under {directory}")
    for page in pages:
        if not has_noindex_meta(page.read_text(encoding="utf-8", errors="replace")):
            reasons.append(f"{page.relative_to(directory).as_posix()} lacks {_NOINDEX_META}")
    reasons.extend(_headers_reasons(directory / HEADERS_FILE))
    reasons.extend(_robots_reasons(directory / ROBOTS_FILE))
    return tuple(reasons)


def _headers_reasons(headers: Path) -> list[str]:
    """``X-Robots-Tag: noindex`` must sit under the ``/*`` block — a narrower path leaves the rest indexable.

    The ``_headers`` format: an unindented line names a path pattern, and the
    indented lines beneath it are that pattern's headers.
    """
    if not headers.is_file():
        return [f"{HEADERS_FILE} is missing"]
    path = ""
    for line in headers.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace():
            path = line.strip()
            continue
        name, sep, value = line.strip().partition(":")
        if path == _CATCH_ALL_PATH and sep and name.strip().lower() == "x-robots-tag" and "noindex" in value.lower():
            return []
    return [f"{HEADERS_FILE} sets no X-Robots-Tag: noindex under {_CATCH_ALL_PATH}"]


def _robots_reasons(robots: Path) -> list[str]:
    """``Disallow: /`` must sit in a group naming ``User-agent: *`` — one for a single bot leaves the rest in.

    Consecutive ``User-agent`` lines open one group; the rules that follow
    belong to it until the next ``User-agent`` line after a rule.
    """
    if not robots.is_file():
        return [f"{ROBOTS_FILE} is missing"]
    agents: set[str] = set()
    in_rules = False
    for line in robots.read_text(encoding="utf-8", errors="replace").splitlines():
        name, sep, value = line.strip().partition(":")
        if not sep or name.strip().startswith("#"):
            continue
        field, value = name.strip().lower(), value.split("#", 1)[0].strip()
        if field == "user-agent":
            if in_rules:
                agents, in_rules = set(), False
            agents.add(value)
        elif field == "disallow":
            in_rules = True
            if value == "/" and "*" in agents:
                return []
        else:
            in_rules = True
    return [f"{ROBOTS_FILE} carries no 'Disallow: /' under 'User-agent: *'"]


__all__ = ["HEADERS_FILE", "HTML_SUFFIXES", "ROBOTS_FILE", "has_noindex_meta", "html_pages", "refusals"]

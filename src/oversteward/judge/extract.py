# ABOUTME: HTML → the visible text a rater would read; markup and scripts never reach the model.
# ABOUTME: Stdlib html.parser only — no bs4, so this deploys anywhere the repo does.

"""Reduce a page to its readable text.

Judging raw markup measures the template, not the page: a rater sees rendered
words, so that is what the judge is given. Block-level tags become line breaks
so headings and paragraphs survive as structure, and the bodies of ``script``,
``style``, ``noscript`` and ``template`` are dropped outright — none of it is
read by a human, and all of it costs tokens.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

#: Elements whose text content is never visible to a reader.
_SILENT_TAGS = frozenset({"script", "style", "noscript", "template"})

#: Elements that end a line of visible text.
_BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "div", "dd", "dl", "dt",
        "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
        "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
        "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
)

#: Whitespace inside a text node — including source newlines, which are the
#: author's formatting rather than structure. Only block tags start a line.
_TEXT_WHITESPACE = re.compile(r"\s+")
_INLINE_WHITESPACE = re.compile(r"[ \t\r\f\v ]+")
_BLANK_RUN = re.compile(r"\n{3,}")


class _VisibleText(HTMLParser):
    """Collects text, one line per block element, skipping non-visible subtrees."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._silent_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        _ = attrs
        if tag in _SILENT_TAGS:
            self._silent_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        _ = attrs
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SILENT_TAGS:
            self._silent_depth = max(0, self._silent_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._silent_depth == 0:
            self._parts.append(_TEXT_WHITESPACE.sub(" ", data))

    def text(self) -> str:
        return "".join(self._parts)


def visible_text(html: str) -> str:
    """The readable text of ``html``, with structure kept as line breaks."""
    parser = _VisibleText()
    parser.feed(html)
    parser.close()
    lines = (_INLINE_WHITESPACE.sub(" ", line).strip() for line in parser.text().splitlines())
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


__all__ = ["visible_text"]

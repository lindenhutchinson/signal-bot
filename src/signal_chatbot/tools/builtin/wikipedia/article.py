"""Pure parsing of whole-article plaintext into an intro, a table of contents,
and per-section text.

The client fetches article plaintext with ``exsectionformat=wiki``, so headings
arrive as lines like ``== History ==`` (``==`` = top level, ``===`` = nested,
…). Everything here is computed locally over that text — once an article is
cached, the TOC and any section are served without further network calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A heading line: 2–6 '=' on each side, e.g. "== History ==" or "=== Early life ===".
_HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1$")


@dataclass(frozen=True, slots=True)
class Section:
    """A flat article segment: the body between one heading and the next."""

    index: int  # 1-based, in order of appearance
    level: int  # 1 for '==', 2 for '===', …
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class ParsedArticle:
    """An article split into its lead and its (flat) list of sections."""

    intro: str
    sections: list[Section]


def parse(full_text: str) -> ParsedArticle:
    """Split whole-article plaintext into the intro and a flat list of sections."""
    intro_lines: list[str] = []
    sections: list[Section] = []
    current: dict | None = None
    body: list[str] = []

    def flush() -> None:
        if current is not None:
            sections.append(
                Section(
                    index=len(sections) + 1,
                    level=current["level"],
                    title=current["title"],
                    text="\n".join(body).strip(),
                )
            )

    for line in full_text.splitlines():
        heading = _HEADING_RE.match(line.strip())
        if heading:
            flush()
            current = {"level": len(heading.group(1)) - 1, "title": heading.group(2).strip()}
            body = []
        elif current is None:
            intro_lines.append(line)
        else:
            body.append(line)
    flush()

    return ParsedArticle(intro="\n".join(intro_lines).strip(), sections=sections)


def table_of_contents(article: ParsedArticle) -> str:
    """Render the section headings as an indented, numbered outline."""
    if not article.sections:
        return "(no sections)"
    lines = [f"{'  ' * (s.level - 1)}{s.index}. {s.title}" for s in article.sections]
    return "\n".join(lines)


def find_section(article: ParsedArticle, selector: str) -> Section | None:
    """Locate a section by 1-based index or by case-insensitive title match."""
    selector = selector.strip()
    if selector.isdigit():
        index = int(selector)
        if 1 <= index <= len(article.sections):
            return article.sections[index - 1]
        return None
    lowered = selector.casefold()
    for section in article.sections:
        if section.title.casefold() == lowered:
            return section
    return None

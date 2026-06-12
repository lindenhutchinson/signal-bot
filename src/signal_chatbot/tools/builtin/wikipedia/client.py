"""Thin async wrapper over the MediaWiki Action API — network only, no caching.

Two operations back the tools: full-text search, and plaintext article extracts
(an intro-only variant and a whole-article variant). The article extract uses
``exsectionformat=wiki`` so section headings come back as ``== Heading ==``
markers, which lets the article parser derive a table of contents and per-section
text locally — no extra request per section.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

import httpx

# Wikipedia search snippets come back as HTML with <span class="searchmatch">
# highlight markup; strip tags and unescape entities for a plain-text snippet.
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One search hit: a canonical article title and a plain-text snippet."""

    title: str
    snippet: str


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text)).strip()


class WikipediaClient:
    """Async client for ``{language}.wikipedia.org/w/api.php``."""

    def __init__(self, http: httpx.AsyncClient, *, language: str = "en"):
        self._http = http
        self._language = language

    @property
    def _api_url(self) -> str:
        return f"https://{self._language}.wikipedia.org/w/api.php"

    async def _query(self, params: dict) -> dict:
        resp = await self._http.get(
            self._api_url,
            params={"format": "json", "formatversion": "2", **params},
        )
        resp.raise_for_status()
        return resp.json()

    async def search(self, query: str, *, limit: int) -> list[SearchResult]:
        """Return up to ``limit`` search hits for ``query``, best match first."""
        data = await self._query(
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": str(limit),
            }
        )
        hits = data.get("query", {}).get("search", [])
        return [
            SearchResult(title=hit["title"], snippet=_strip_html(hit.get("snippet", "")))
            for hit in hits
        ]

    async def intro(self, title: str) -> str | None:
        """Return the lead-section plaintext for ``title``, or ``None`` if missing."""
        return await self._extract(title, intro_only=True)

    async def full(self, title: str) -> str | None:
        """Return the whole-article plaintext (with ``== Heading ==`` markers)."""
        return await self._extract(title, intro_only=False)

    async def _extract(self, title: str, *, intro_only: bool) -> str | None:
        params = {
            "action": "query",
            "prop": "extracts",
            "explaintext": "1",
            "exsectionformat": "wiki",
            "redirects": "1",
            "titles": title,
        }
        if intro_only:
            params["exintro"] = "1"
        data = await self._query(params)
        pages = data.get("query", {}).get("pages", [])
        if not pages:
            return None
        page = pages[0]
        if page.get("missing"):
            return None
        extract = page.get("extract")
        return extract or None

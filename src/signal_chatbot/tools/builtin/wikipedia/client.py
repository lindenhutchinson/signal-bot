"""Thin async wrapper over the MediaWiki Action API — network only, no caching.

Two operations back the tools: full-text search, and plaintext article extracts
(an intro-only variant and a whole-article variant). The article extract uses
``exsectionformat=wiki`` so section headings come back as ``== Heading ==``
markers, which lets the article parser derive a table of contents and per-section
text locally — no extra request per section.
"""

from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass

import httpx

from signal_chatbot.logging import get_logger

log = get_logger(__name__)

# Wikipedia search snippets come back as HTML with <span class="searchmatch">
# highlight markup; strip tags and unescape entities for a plain-text snippet.
_TAG_RE = re.compile(r"<[^>]+>")

# Wikimedia returns 429 when an IP/User-Agent exceeds its rate limit and 503 when
# the database replica lag exceeds our ``maxlag``. Both are transient and carry a
# ``Retry-After`` header; back off and retry rather than failing the whole reply.
_RETRYABLE_STATUS = frozenset({429, 503})
_MAX_RETRY_DELAY = 30.0


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One search hit: a canonical article title and a plain-text snippet."""

    title: str
    snippet: str


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text)).strip()


class WikipediaClient:
    """Async client for ``{language}.wikipedia.org/w/api.php``."""

    def __init__(self, http: httpx.AsyncClient, *, language: str = "en", max_retries: int = 3):
        self._http = http
        self._language = language
        self._max_retries = max_retries

    @property
    def _api_url(self) -> str:
        return f"https://{self._language}.wikipedia.org/w/api.php"

    async def _query(self, params: dict) -> dict:
        # maxlag asks Wikimedia to reject (with 503 + Retry-After) rather than serve
        # from a lagging replica; we honour that and 429 throttling with backoff.
        full = {"format": "json", "formatversion": "2", "maxlag": "5", **params}
        for attempt in range(self._max_retries + 1):
            resp = await self._http.get(self._api_url, params=full)
            if resp.status_code in _RETRYABLE_STATUS and attempt < self._max_retries:
                delay = self._retry_delay(resp, attempt)
                log.warning(
                    "wikipedia.throttled",
                    status=resp.status_code,
                    attempt=attempt + 1,
                    retry_in=delay,
                )
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()
        raise AssertionError("unreachable: loop returns or raises on the final attempt")

    @staticmethod
    def _retry_delay(resp: httpx.Response, attempt: int) -> float:
        """Seconds to wait before retrying — the ``Retry-After`` header if sane, else
        exponential backoff, capped."""
        header = resp.headers.get("Retry-After", "")
        if header.isdigit():
            return min(float(header), _MAX_RETRY_DELAY)
        return min(2.0**attempt, _MAX_RETRY_DELAY)

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

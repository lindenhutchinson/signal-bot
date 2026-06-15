"""Thin async client for the Tavily search API — network only, no caching.

We deliberately request ``search_depth=basic`` and never the raw/full page
content: the tool exposes short snippets the model can synthesise from, not
whole pages (cheaper, faster, and less untrusted text injected into the prompt).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_SEARCH_URL = "https://api.tavily.com/search"


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One web result: a title, its URL, and a short snippet."""

    title: str
    url: str
    snippet: str


class TavilyClient:
    """Async client for the Tavily ``/search`` endpoint."""

    def __init__(self, http: httpx.AsyncClient, api_key: str, *, result_limit: int):
        self._http = http
        self._api_key = api_key
        self._result_limit = result_limit

    async def search(self, query: str) -> list[SearchHit]:
        """Return up to ``result_limit`` snippet results for ``query``."""
        resp = await self._http.post(
            _SEARCH_URL,
            json={
                "api_key": self._api_key,
                "query": query,
                "max_results": self._result_limit,
                "search_depth": "basic",
            },
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return [
            SearchHit(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
            )
            for item in results
        ]

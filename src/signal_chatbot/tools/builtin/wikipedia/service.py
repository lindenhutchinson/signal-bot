"""Composes the client and cache: every lookup is served from cache or fetched
once and cached.

This is the single place caching happens — the tools above it and the client
below it know nothing about it. Successful results are cached; misses (no such
page) are not, since they are cheap to re-check and rare. Cache keys carry the
language so multi-language use never crosses wires.
"""

from __future__ import annotations

import json

from signal_chatbot.tools.builtin.wikipedia.cache import WikipediaCache
from signal_chatbot.tools.builtin.wikipedia.client import SearchResult, WikipediaClient


class WikipediaService:
    """Cached access to Wikipedia search and article plaintext."""

    def __init__(
        self,
        client: WikipediaClient,
        cache: WikipediaCache,
        *,
        language: str,
        ttl_seconds: int,
        search_limit: int,
    ):
        self._client = client
        self._cache = cache
        self._language = language
        self._ttl = ttl_seconds
        self._search_limit = search_limit

    async def search(self, query: str) -> list[SearchResult]:
        """Search Wikipedia, returning cached hits when available."""
        key = f"search:{self._language}:{self._search_limit}:{query.strip().casefold()}"
        cached = await self._cache.get(key)
        if cached is not None:
            return [SearchResult(**item) for item in json.loads(cached)]
        results = await self._client.search(query, limit=self._search_limit)
        if results:
            payload = json.dumps([{"title": r.title, "snippet": r.snippet} for r in results])
            await self._cache.put(key, payload, ttl_seconds=self._ttl)
        return results

    async def intro(self, title: str) -> str | None:
        """Return the lead-section plaintext for ``title`` (cached)."""
        return await self._cached_extract(f"intro:{self._language}:{title}", title, full=False)

    async def full(self, title: str) -> str | None:
        """Return the whole-article plaintext for ``title`` (cached)."""
        return await self._cached_extract(f"full:{self._language}:{title}", title, full=True)

    async def _cached_extract(self, key: str, title: str, *, full: bool) -> str | None:
        cached = await self._cache.get(key)
        if cached is not None:
            return cached
        text = await (self._client.full(title) if full else self._client.intro(title))
        if text is not None:
            await self._cache.put(key, text, ttl_seconds=self._ttl)
        return text

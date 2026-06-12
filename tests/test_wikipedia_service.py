from pathlib import Path

import pytest

from signal_chatbot.tools.builtin.wikipedia import (
    SearchResult,
    WikipediaCache,
    WikipediaService,
)


class CountingClient:
    """A stand-in client that records how often each method is hit."""

    def __init__(self) -> None:
        self.search_calls = 0
        self.intro_calls = 0
        self.full_calls = 0

    async def search(self, query: str, *, limit: int) -> list[SearchResult]:
        self.search_calls += 1
        return [SearchResult(title="Mercury (planet)", snippet="the planet")]

    async def intro(self, title: str) -> str | None:
        self.intro_calls += 1
        return None if title == "Missing" else "Intro text."

    async def full(self, title: str) -> str | None:
        self.full_calls += 1
        return "Intro\n\n== History =="


@pytest.fixture
async def cache(tmp_path: Path) -> WikipediaCache:
    c = WikipediaCache(tmp_path / "c.sqlite")
    await c.connect()
    yield c
    await c.aclose()


def _service(client: CountingClient, cache: WikipediaCache) -> WikipediaService:
    return WikipediaService(client, cache, language="en", ttl_seconds=3600, search_limit=5)


async def test_search_is_cached_after_first_call(cache: WikipediaCache) -> None:
    client = CountingClient()
    service = _service(client, cache)

    first = await service.search("mercury")
    second = await service.search("mercury")

    assert [r.title for r in first] == ["Mercury (planet)"]
    assert second == first
    assert client.search_calls == 1


async def test_search_cache_key_normalises_whitespace_and_case(cache: WikipediaCache) -> None:
    client = CountingClient()
    service = _service(client, cache)

    await service.search("Mercury")
    await service.search("  mercury  ")

    assert client.search_calls == 1


async def test_intro_is_cached(cache: WikipediaCache) -> None:
    client = CountingClient()
    service = _service(client, cache)

    assert await service.intro("Mercury") == "Intro text."
    assert await service.intro("Mercury") == "Intro text."
    assert client.intro_calls == 1


async def test_full_is_cached(cache: WikipediaCache) -> None:
    client = CountingClient()
    service = _service(client, cache)

    await service.full("Mercury")
    await service.full("Mercury")

    assert client.full_calls == 1


async def test_misses_are_not_cached(cache: WikipediaCache) -> None:
    client = CountingClient()
    service = _service(client, cache)

    assert await service.intro("Missing") is None
    assert await service.intro("Missing") is None
    assert client.intro_calls == 2  # re-fetched, not cached

from pathlib import Path

import pytest

from signal_chatbot.tools.builtin.wikipedia import WikipediaCache


class FakeClock:
    def __init__(self, now: int = 1000):
        self.now = now

    def __call__(self) -> int:
        return self.now


@pytest.fixture
async def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def cache(tmp_path: Path, clock: FakeClock) -> WikipediaCache:
    c = WikipediaCache(tmp_path / "cache.sqlite", now=clock)
    await c.connect()
    yield c
    await c.aclose()


async def test_get_returns_none_on_miss(cache: WikipediaCache) -> None:
    assert await cache.get("absent") is None


async def test_put_then_get_round_trips(cache: WikipediaCache) -> None:
    await cache.put("k", "payload", ttl_seconds=60)
    assert await cache.get("k") == "payload"


async def test_get_returns_none_after_expiry(cache: WikipediaCache, clock: FakeClock) -> None:
    await cache.put("k", "payload", ttl_seconds=60)
    clock.now += 61
    assert await cache.get("k") is None


async def test_entry_is_valid_one_second_before_expiry(
    cache: WikipediaCache, clock: FakeClock
) -> None:
    await cache.put("k", "payload", ttl_seconds=60)
    clock.now += 59
    assert await cache.get("k") == "payload"


async def test_put_overwrites_existing_key(cache: WikipediaCache) -> None:
    await cache.put("k", "old", ttl_seconds=60)
    await cache.put("k", "new", ttl_seconds=60)
    assert await cache.get("k") == "new"

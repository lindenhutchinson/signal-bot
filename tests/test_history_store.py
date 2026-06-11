from pathlib import Path

import pytest

from signal_chatbot.history import HistoryStore


@pytest.fixture
async def store(tmp_path: Path) -> HistoryStore:
    s = HistoryStore(tmp_path / "h.sqlite", window_max=3)
    await s.connect()
    yield s
    await s.aclose()


async def test_append_and_recent_returns_in_order(store: HistoryStore) -> None:
    await store.append("g1", sender="Alice", text="hello", timestamp=1)
    await store.append("g1", sender="Bob", text="hi", timestamp=2)

    recent = await store.recent("g1")

    assert [(m.sender, m.text) for m in recent] == [("Alice", "hello"), ("Bob", "hi")]


async def test_recent_is_capped_to_window_keeping_newest(store: HistoryStore) -> None:
    for i in range(5):
        await store.append("g1", sender="A", text=f"m{i}", timestamp=i)

    recent = await store.recent("g1")

    assert [m.text for m in recent] == ["m2", "m3", "m4"]


async def test_history_is_isolated_per_group(store: HistoryStore) -> None:
    await store.append("g1", sender="A", text="one", timestamp=1)
    await store.append("g2", sender="B", text="two", timestamp=1)

    assert [m.text for m in await store.recent("g1")] == ["one"]
    assert [m.text for m in await store.recent("g2")] == ["two"]


async def test_history_persists_across_reconnect(tmp_path: Path) -> None:
    path = tmp_path / "h.sqlite"
    s1 = HistoryStore(path, window_max=10)
    await s1.connect()
    await s1.append("g1", sender="A", text="persisted", timestamp=1)
    await s1.aclose()

    s2 = HistoryStore(path, window_max=10)
    await s2.connect()
    recent = await s2.recent("g1")
    await s2.aclose()

    assert [m.text for m in recent] == ["persisted"]

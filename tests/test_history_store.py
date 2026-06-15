from pathlib import Path

import aiosqlite
import pytest

from signal_chatbot.history import HistoryStore


@pytest.fixture
async def store(tmp_path: Path) -> HistoryStore:
    s = HistoryStore(tmp_path / "h.sqlite", window_max=3)
    await s.connect()
    yield s
    await s.aclose()


async def test_append_and_recent_returns_in_order(store: HistoryStore) -> None:
    await store.append("g1", sender="Alice", text="hello", timestamp=1, sender_number="+1")
    await store.append("g1", sender="Bob", text="hi", timestamp=2, sender_number="+2")

    recent = await store.recent("g1")

    assert [(m.sender, m.text) for m in recent] == [("Alice", "hello"), ("Bob", "hi")]


async def test_append_and_recent_round_trip_sender_number(store: HistoryStore) -> None:
    await store.append("g1", sender="Alice", text="hello", timestamp=1, sender_number="+61400")
    await store.append("g1", sender="__bot__", text="hi", timestamp=2, sender_number="")

    recent = await store.recent("g1")

    assert [m.sender_number for m in recent] == ["+61400", ""]


async def test_recent_is_capped_to_window_keeping_newest(store: HistoryStore) -> None:
    for i in range(5):
        await store.append("g1", sender="A", text=f"m{i}", timestamp=i, sender_number="+1")

    recent = await store.recent("g1")

    assert [m.text for m in recent] == ["m2", "m3", "m4"]


async def test_history_is_isolated_per_group(store: HistoryStore) -> None:
    await store.append("g1", sender="A", text="one", timestamp=1, sender_number="+1")
    await store.append("g2", sender="B", text="two", timestamp=1, sender_number="+2")

    assert [m.text for m in await store.recent("g1")] == ["one"]
    assert [m.text for m in await store.recent("g2")] == ["two"]


async def test_clear_removes_only_the_target_group(store: HistoryStore) -> None:
    await store.append("g1", sender="A", text="one", timestamp=1, sender_number="+1")
    await store.append("g2", sender="B", text="two", timestamp=1, sender_number="+2")

    await store.clear("g1")

    assert await store.recent("g1") == []
    assert [m.text for m in await store.recent("g2")] == ["two"]


async def test_history_persists_across_reconnect(tmp_path: Path) -> None:
    path = tmp_path / "h.sqlite"
    s1 = HistoryStore(path, window_max=10)
    await s1.connect()
    await s1.append("g1", sender="A", text="persisted", timestamp=1, sender_number="+1")
    await s1.aclose()

    s2 = HistoryStore(path, window_max=10)
    await s2.connect()
    recent = await s2.recent("g1")
    await s2.aclose()

    assert [m.text for m in recent] == ["persisted"]


async def test_connect_migrates_a_database_lacking_sender_number(tmp_path: Path) -> None:
    # Simulate a pre-quote DB: a messages table created without the sender_number column.
    path = tmp_path / "old.sqlite"
    legacy = await aiosqlite.connect(path)
    await legacy.execute(
        "CREATE TABLE messages ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  group_id TEXT NOT NULL,"
        "  sender TEXT NOT NULL,"
        "  text TEXT NOT NULL,"
        "  timestamp INTEGER NOT NULL"
        ")"
    )
    await legacy.execute(
        "INSERT INTO messages (group_id, sender, text, timestamp) VALUES (?, ?, ?, ?)",
        ("g1", "Alice", "legacy", 1),
    )
    await legacy.commit()
    await legacy.close()

    store = HistoryStore(path, window_max=10)
    await store.connect()
    try:
        # The old row reads back with the empty-string default...
        recent = await store.recent("g1")
        assert [(m.text, m.sender_number) for m in recent] == [("legacy", "")]
        # ...and new appends carrying a number work against the migrated table.
        await store.append("g1", sender="Bob", text="new", timestamp=2, sender_number="+2")
        assert (await store.recent("g1"))[-1].sender_number == "+2"
    finally:
        await store.aclose()

from pathlib import Path

import pytest

from signal_chatbot.state import StateStore


@pytest.fixture
async def store(tmp_path: Path) -> StateStore:
    s = StateStore(tmp_path / "state.sqlite", command_log_window=3)
    await s.connect()
    yield s
    await s.aclose()


async def test_add_and_read_directives_bucketed_by_kind_oldest_first(store: StateStore) -> None:
    await store.add_directive(
        "g1", kind="rule", author_name="Alice", author_number="+1", text="no puns", created_at=1
    )
    await store.add_directive(
        "g1", kind="rule", author_name="Bob", author_number="+2", text="haiku only", created_at=2
    )
    await store.add_directive(
        "g1",
        kind="lore",
        author_name="Alice",
        author_number="+1",
        text="Dave fears geese",
        created_at=3,
    )

    directives = await store.directives("g1")

    assert [d.text for d in directives.rules] == ["no puns", "haiku only"]
    assert [d.text for d in directives.lore] == ["Dave fears geese"]
    assert directives.patches == []
    assert directives.rules[0].author_name == "Alice"
    assert directives.rules[0].created_at == 1


async def test_directives_are_isolated_per_group(store: StateStore) -> None:
    await store.add_directive(
        "g1", kind="patch", author_name="A", author_number="+1", text="x", created_at=1
    )
    await store.add_directive(
        "g2", kind="patch", author_name="B", author_number="+2", text="y", created_at=1
    )

    assert [d.text for d in (await store.directives("g1")).patches] == ["x"]
    assert [d.text for d in (await store.directives("g2")).patches] == ["y"]


async def test_clear_directives_removes_only_the_target_group(store: StateStore) -> None:
    await store.add_directive(
        "g1", kind="patch", author_name="A", author_number="+1", text="x", created_at=1
    )
    await store.add_directive(
        "g2", kind="patch", author_name="B", author_number="+2", text="y", created_at=1
    )

    await store.clear_directives("g1")

    assert (await store.directives("g1")).patches == []
    assert [d.text for d in (await store.directives("g2")).patches] == ["y"]


async def test_command_log_windows_to_newest_keeping_oldest_first(store: StateStore) -> None:
    for i in range(5):
        await store.log_command("g1", author_name="A", command=f"@c{i}", created_at=i)

    log = await store.recent_commands("g1")

    assert [c.command for c in log] == ["@c2", "@c3", "@c4"]
    assert log[0].author_name == "A"


async def test_command_log_is_isolated_per_group(store: StateStore) -> None:
    await store.log_command("g1", author_name="A", command="@reset", created_at=1)
    await store.log_command("g2", author_name="B", command="@clear", created_at=1)

    assert [c.command for c in await store.recent_commands("g1")] == ["@reset"]
    assert [c.command for c in await store.recent_commands("g2")] == ["@clear"]


async def test_disclaimers_are_stored_and_returned_newest_first(store: StateStore) -> None:
    await store.add_disclaimer("g1", message="doomed", disclaimer="jk", created_at=1)
    await store.add_disclaimer("g1", message="awful", disclaimer="satire", created_at=2)

    disclaimers = await store.recent_disclaimers("g1")

    assert [(d.message, d.disclaimer) for d in disclaimers] == [
        ("awful", "satire"),
        ("doomed", "jk"),
    ]


async def test_disclaimers_window_to_newest_and_isolate_per_group(store: StateStore) -> None:
    for i in range(5):
        await store.add_disclaimer("g1", message=f"m{i}", disclaimer=f"d{i}", created_at=i)
    await store.add_disclaimer("g2", message="other", disclaimer="x", created_at=1)

    g1 = await store.recent_disclaimers("g1")

    # window_max=3 keeps the newest three, returned newest-first
    assert [d.disclaimer for d in g1] == ["d4", "d3", "d2"]
    assert [d.message for d in await store.recent_disclaimers("g2")] == ["other"]

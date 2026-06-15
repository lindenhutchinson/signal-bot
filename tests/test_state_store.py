from pathlib import Path

import pytest

from signal_chatbot.state import Database


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    d = Database(tmp_path / "state.sqlite", command_log_window=3)
    await d.connect()
    yield d
    await d.aclose()


# --- directives -----------------------------------------------------------


async def test_add_and_read_directives_bucketed_by_kind_oldest_first(db: Database) -> None:
    store = db.directives
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
    assert directives.rules[0].author_name == "Alice"
    assert directives.rules[0].created_at == 1


async def test_directives_are_isolated_per_group(db: Database) -> None:
    store = db.directives
    await store.add_directive(
        "g1", kind="rule", author_name="A", author_number="+1", text="x", created_at=1
    )
    await store.add_directive(
        "g2", kind="rule", author_name="B", author_number="+2", text="y", created_at=1
    )

    assert [d.text for d in (await store.directives("g1")).rules] == ["x"]
    assert [d.text for d in (await store.directives("g2")).rules] == ["y"]


async def test_legacy_patch_rows_are_not_surfaced(db: Database) -> None:
    # Existing 'patch' rows from before the kind was removed must simply not show up.
    store = db.directives
    await store.add_directive(
        "g1", kind="patch", author_name="A", author_number="+1", text="old patch", created_at=1
    )
    await store.add_directive(
        "g1", kind="rule", author_name="A", author_number="+1", text="a rule", created_at=2
    )

    directives = await store.directives("g1")

    assert [d.text for d in directives.rules] == ["a rule"]
    assert [d.text for d in directives.lore] == []


async def test_clear_directives_removes_only_the_target_group(db: Database) -> None:
    store = db.directives
    await store.add_directive(
        "g1", kind="rule", author_name="A", author_number="+1", text="x", created_at=1
    )
    await store.add_directive(
        "g2", kind="rule", author_name="B", author_number="+2", text="y", created_at=1
    )

    await store.clear_directives("g1")

    assert (await store.directives("g1")).rules == []
    assert [d.text for d in (await store.directives("g2")).rules] == ["y"]


# --- command log ----------------------------------------------------------


async def test_command_log_windows_to_newest_keeping_oldest_first(db: Database) -> None:
    store = db.commands
    for i in range(5):
        await store.log_command("g1", author_name="A", command=f"@c{i}", created_at=i)

    log = await store.recent_commands("g1")

    assert [c.command for c in log] == ["@c2", "@c3", "@c4"]
    assert log[0].author_name == "A"


async def test_command_log_is_isolated_per_group(db: Database) -> None:
    store = db.commands
    await store.log_command("g1", author_name="A", command="@reset", created_at=1)
    await store.log_command("g2", author_name="B", command="@lobotomy", created_at=1)

    assert [c.command for c in await store.recent_commands("g1")] == ["@reset"]
    assert [c.command for c in await store.recent_commands("g2")] == ["@lobotomy"]


# --- arming ---------------------------------------------------------------


async def test_suicide_arming_round_trips_and_is_per_group(db: Database) -> None:
    store = db.arming
    assert await store.is_suicide_armed("g1") is False

    await store.arm_suicide("g1", at=123)

    assert await store.is_suicide_armed("g1") is True
    assert await store.is_suicide_armed("g2") is False  # isolated per group


async def test_arming_is_idempotent(db: Database) -> None:
    store = db.arming
    await store.arm_suicide("g1", at=1)
    await store.arm_suicide("g1", at=2)  # re-arming must not blow up on the PK

    assert await store.is_suicide_armed("g1") is True


async def test_disarm_suicide_clears_only_the_target_group(db: Database) -> None:
    store = db.arming
    await store.arm_suicide("g1", at=1)
    await store.arm_suicide("g2", at=1)

    await store.disarm_suicide("g1")

    assert await store.is_suicide_armed("g1") is False
    assert await store.is_suicide_armed("g2") is True


async def test_arming_persists_across_reconnect(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    d1 = Database(path, command_log_window=3)
    await d1.connect()
    await d1.arming.arm_suicide("g1", at=1)
    await d1.aclose()

    d2 = Database(path, command_log_window=3)
    await d2.connect()
    armed = await d2.arming.is_suicide_armed("g1")
    await d2.aclose()

    assert armed is True


# --- disclaimers ----------------------------------------------------------


async def test_disclaimers_are_stored_and_returned_newest_first(db: Database) -> None:
    store = db.disclaimers
    await store.add_disclaimer("g1", message="doomed", disclaimer="jk", created_at=1)
    await store.add_disclaimer("g1", message="awful", disclaimer="satire", created_at=2)

    disclaimers = await store.recent_disclaimers("g1")

    assert [(d.message, d.disclaimer) for d in disclaimers] == [
        ("awful", "satire"),
        ("doomed", "jk"),
    ]


async def test_disclaimers_window_to_newest_and_isolate_per_group(db: Database) -> None:
    store = db.disclaimers
    for i in range(5):
        await store.add_disclaimer("g1", message=f"m{i}", disclaimer=f"d{i}", created_at=i)
    await store.add_disclaimer("g2", message="other", disclaimer="x", created_at=1)

    g1 = await store.recent_disclaimers("g1")

    # window=3 keeps the newest three, returned newest-first
    assert [d.disclaimer for d in g1] == ["d4", "d3", "d2"]
    assert [d.message for d in await store.recent_disclaimers("g2")] == ["other"]


async def test_disclaimers_clear_removes_only_the_target_group(db: Database) -> None:
    store = db.disclaimers
    await store.add_disclaimer("g1", message="m", disclaimer="d", created_at=1)
    await store.add_disclaimer("g2", message="keep", disclaimer="x", created_at=1)

    await store.clear("g1")

    assert await store.recent_disclaimers("g1") == []
    assert [d.message for d in await store.recent_disclaimers("g2")] == ["keep"]

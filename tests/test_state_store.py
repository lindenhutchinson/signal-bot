from pathlib import Path

import pytest

from signal_chatbot.state import Database
from signal_chatbot.state.flags import SELF_DESTRUCT_ARMED, FlagRegistry


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


# --- flags ----------------------------------------------------------------


async def test_flag_store_round_trips_and_isolates_per_group(db: Database) -> None:
    store = db.flags
    assert await store.get("g1", "listen_next") is None  # unset

    await store.set("g1", "listen_next", True)

    assert await store.get("g1", "listen_next") is True
    assert await store.get("g2", "listen_next") is None  # isolated per group


async def test_flag_store_set_is_idempotent_via_upsert(db: Database) -> None:
    store = db.flags
    await store.set("g1", "listen_next", True)
    await store.set("g1", "listen_next", False)  # upsert, not a PK violation

    assert await store.get("g1", "listen_next") is False


async def test_flag_store_clear_removes_only_the_target_group(db: Database) -> None:
    store = db.flags
    await store.set("g1", "listen_next", True)
    await store.set("g2", "listen_next", True)

    await store.clear("g1")

    assert await store.get("g1", "listen_next") is None
    assert await store.get("g2", "listen_next") is True


async def test_flag_registry_arming_round_trips(db: Database) -> None:
    flags = FlagRegistry(db.flags)
    assert await flags.is_armed("g1") is False  # default

    await flags.arm("g1")

    assert await flags.is_armed("g1") is True
    await flags.clear("g1")
    assert await flags.is_armed("g1") is False  # cleared on wipe


async def test_flag_registry_consume_listen_is_one_shot(db: Database) -> None:
    flags = FlagRegistry(db.flags)
    assert await flags.consume_listen("g1") is False  # never set

    await flags.set_listen("g1")

    assert await flags.consume_listen("g1") is True  # set → fires once
    assert await flags.consume_listen("g1") is False  # ...and is cleared


async def test_flag_registry_view_and_reset(db: Database) -> None:
    flags = FlagRegistry(db.flags)
    await flags.arm("g1")

    view = await flags.view("g1")
    armed = next(f for f in view if f.name == SELF_DESTRUCT_ARMED)
    assert armed.value is True
    assert armed.index == 1

    name = await flags.reset("g1", armed.index)
    assert name == SELF_DESTRUCT_ARMED
    assert await flags.is_armed("g1") is False
    assert await flags.reset("g1", 99) is None  # unknown index


async def test_flags_persist_across_reconnect(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    d1 = Database(path, command_log_window=3)
    await d1.connect()
    await FlagRegistry(d1.flags).arm("g1")
    await d1.aclose()

    d2 = Database(path, command_log_window=3)
    await d2.connect()
    armed = await FlagRegistry(d2.flags).is_armed("g1")
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


# --- final words ----------------------------------------------------------


async def test_final_words_append_oldest_first_and_isolate_per_group(db: Database) -> None:
    store = db.final_words
    await store.add("g1", name="Greg", text="Beware Dave.", created_at=1)
    await store.add("g1", name="Mona", text="I told you so.", created_at=2)
    await store.add("g2", name="Other", text="elsewhere", created_at=1)

    g1 = await store.all("g1")
    assert [(fw.name, fw.text) for fw in g1] == [
        ("Greg", "Beware Dave."),
        ("Mona", "I told you so."),
    ]
    assert [fw.name for fw in await store.all("g2")] == ["Other"]


async def test_final_words_have_no_clear_and_survive_a_reconnect(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    d1 = Database(path, command_log_window=3)
    await d1.connect()
    await d1.final_words.add("g1", name="Greg", text="last words", created_at=1)
    # The store deliberately exposes no clear(): the archive outlives every wipe.
    assert not hasattr(d1.final_words, "clear")
    await d1.aclose()

    d2 = Database(path, command_log_window=3)
    await d2.connect()
    survived = await d2.final_words.all("g1")
    await d2.aclose()

    assert [fw.text for fw in survived] == ["last words"]

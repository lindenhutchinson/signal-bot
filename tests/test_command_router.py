from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from signal_chatbot.commands import replies
from signal_chatbot.commands.farewell import Farewell
from signal_chatbot.commands.parser import parse
from signal_chatbot.commands.router import CommandRouter
from signal_chatbot.history import HistoryStore
from signal_chatbot.lobotomy import Lobotomiser
from signal_chatbot.state import Database
from signal_chatbot.state.flags import FlagRegistry
from signal_chatbot.tools import ToolRegistry
from signal_chatbot.tools.builtin.clock import CurrentTime
from signal_chatbot.transport.models import IncomingMessage

GROUP = "group.g1="


def message(text: str, *, sender_name: str = "Alice", ts: int = 1781274720000) -> IncomingMessage:
    return IncomingMessage(
        group_id=GROUP, sender_number="+1", sender_name=sender_name, text=text, timestamp=ts
    )


class FakeFarewellWriter:
    def __init__(self, result: Farewell | None) -> None:
        self.result = result
        self.seen_history = None

    async def write(self, *, directives, history) -> Farewell | None:
        self.seen_history = history
        return self.result


class FakeNameSetter:
    def __init__(self, error: Exception | None = None) -> None:
        self.names: list[str] = []
        self.error = error

    async def set_profile_name(self, name: str) -> None:
        if self.error is not None:
            raise self.error
        self.names.append(name)


@pytest.fixture
async def stores(tmp_path: Path):
    db = Database(tmp_path / "state.sqlite", command_log_window=40)
    history = HistoryStore(tmp_path / "history.sqlite", window_max=40)
    await db.connect()
    await history.connect()
    yield db, history
    await db.aclose()
    await history.aclose()


def router(
    db, history, *, farewell=None, name_setter=None, default_name="bot", tools=None
) -> CommandRouter:
    setter = name_setter or FakeNameSetter()
    flags = FlagRegistry(db.flags)
    lobotomiser = Lobotomiser(
        directives=db.directives,
        flags=flags,
        disclaimers=db.disclaimers,
        profiles=db.profiles,
        history=history,
        name_setter=setter,
        default_name=default_name,
    )
    return CommandRouter(
        directives=db.directives,
        commands=db.commands,
        disclaimers=db.disclaimers,
        profiles=db.profiles,
        flags=flags,
        final_words=db.final_words,
        history=history,
        farewell=farewell or FakeFarewellWriter(None),
        name_setter=setter,
        lobotomiser=lobotomiser,
        tools=tools if tools is not None else ToolRegistry([CurrentTime()]),
        timezone=ZoneInfo("Australia/Sydney"),
    )


async def _run(r: CommandRouter, text: str, **kw) -> str:
    command = parse(text)
    assert command is not None
    return await r.handle(command, message(text, **kw))


async def test_rule_stores_directive_logs_and_confirms(stores) -> None:
    db, history = stores
    r = router(db, history)

    assert await _run(r, "@rule no more puns") == replies.RULE_LOGGED
    assert [d.text for d in (await db.directives.directives(GROUP)).rules] == ["no more puns"]
    assert [c.command for c in await db.commands.recent_commands(GROUP)] == ["@rule"]


async def test_empty_rule_returns_usage_and_does_not_log(stores) -> None:
    db, history = stores
    r = router(db, history)

    assert await _run(r, "@rule") == replies.USAGE_RULE
    assert (await db.directives.directives(GROUP)).rules == []
    assert await db.commands.recent_commands(GROUP) == []


async def test_rule_and_lore_store_under_their_kinds(stores) -> None:
    db, history = stores
    r = router(db, history)

    assert await _run(r, "@rule haiku only") == replies.RULE_LOGGED
    assert await _run(r, "@lore Dave fears geese") == replies.LORE_ADDED
    directives = await db.directives.directives(GROUP)
    assert [d.text for d in directives.rules] == ["haiku only"]
    assert [d.text for d in directives.lore] == ["Dave fears geese"]


async def test_rulelist_renders_entries(stores) -> None:
    db, history = stores
    r = router(db, history)
    await _run(r, "@rule no puns")

    out = await _run(r, "@rulelist")

    assert out == 'Rules:\n1. "no puns" — Alice'


async def test_disclaimers_lists_logged_asides(stores) -> None:
    db, history = stores
    await db.disclaimers.add_disclaimer(
        GROUP, message="doomed", disclaimer="jk", created_at=1781274720000
    )
    r = router(db, history)

    out = await _run(r, "@disclaimers")

    assert out == 'Disclaimers:\n1. [2026-06-13 00:32 AEST] "jk"'


async def test_disclaimers_empty(stores) -> None:
    db, history = stores
    r = router(db, history)

    assert await _run(r, "@disclaimers") == "No disclaimers yet."


async def test_profiles_lists_what_the_bot_remembers(stores) -> None:
    db, history = stores
    await db.profiles.add_note(GROUP, subject="Dave", note="fears geese", created_at=1)
    r = router(db, history)

    out = await _run(r, "@profiles")

    assert out.startswith("Profiles:")
    assert "Dave:" in out and "fears geese" in out
    # a query, so nothing is logged
    assert await db.commands.recent_commands(GROUP) == []


async def test_profiles_empty(stores) -> None:
    db, history = stores
    r = router(db, history)

    assert await _run(r, "@profiles") == "No profiles yet."


async def test_forget_one_drops_that_subject_and_is_logged(stores) -> None:
    db, history = stores
    await db.profiles.add_note(GROUP, subject="Dave", note="fears geese", created_at=1)
    await db.profiles.add_note(GROUP, subject="Alice", note="loves cats", created_at=2)
    r = router(db, history)

    out = await _run(r, "@forget Dave")

    assert out == replies.forgot_one("Dave")
    assert [p.subject for p in await db.profiles.all(GROUP)] == ["Alice"]
    assert [c.command for c in await db.commands.recent_commands(GROUP)] == ["@forget"]


async def test_forget_unknown_subject_reports_no_match_but_still_logs(stores) -> None:
    db, history = stores
    await db.profiles.add_note(GROUP, subject="Dave", note="fears geese", created_at=1)
    r = router(db, history)

    out = await _run(r, "@forget Nobody")

    assert out == replies.no_such_profile("Nobody")
    assert [p.subject for p in await db.profiles.all(GROUP)] == ["Dave"]
    assert [c.command for c in await db.commands.recent_commands(GROUP)] == ["@forget"]


async def test_forget_with_no_name_clears_all_profiles_and_logs(stores) -> None:
    db, history = stores
    await db.profiles.add_note(GROUP, subject="Dave", note="fears geese", created_at=1)
    await db.profiles.add_note(GROUP, subject="Alice", note="loves cats", created_at=2)
    r = router(db, history)

    out = await _run(r, "@forget")

    assert out == replies.FORGOT_ALL
    assert await db.profiles.all(GROUP) == []
    assert [c.command for c in await db.commands.recent_commands(GROUP)] == ["@forget"]


async def test_help_returns_help_text(stores) -> None:
    db, history = stores
    r = router(db, history)

    assert await _run(r, "@help") == replies.HELP_TEXT


async def test_info_lists_injected_tools_and_is_not_logged(stores) -> None:
    db, history = stores
    r = router(db, history, tools=ToolRegistry([CurrentTime()]))

    out = await _run(r, "@info")

    assert "current_time" in out  # introspected from the injected registry
    assert "@help" in out  # explains the help command
    # a query, so nothing is logged
    assert await db.commands.recent_commands(GROUP) == []


async def test_reset_with_farewell_wipes_records_final_words_and_announces(stores) -> None:
    db, history = stores
    await db.directives.add_directive(
        GROUP, kind="rule", author_name="A", author_number="+1", text="old rule", created_at=1
    )
    farewell = FakeFarewellWriter(Farewell(name="Greg", final_message="Beware Dave."))
    name_setter = FakeNameSetter()
    r = router(db, history, farewell=farewell, name_setter=name_setter)

    out = await _run(r, "@reset")

    assert out == "Final message from Greg:\nBeware Dave."
    directives = await db.directives.directives(GROUP)
    assert directives.rules == []
    assert directives.lore == []  # the farewell is NOT seeded back as lore
    # ...it goes to the never-wiped final-words archive instead
    assert [(fw.name, fw.text) for fw in await db.final_words.all(GROUP)] == [
        ("Greg", "Beware Dave.")
    ]
    assert [c.command for c in await db.commands.recent_commands(GROUP)] == ["@reset"]
    assert name_setter.names == ["Greg"]  # reset renames the bot to its new self


async def test_reset_rename_failure_does_not_abort_the_reset(stores) -> None:
    db, history = stores
    await db.directives.add_directive(
        GROUP, kind="rule", author_name="A", author_number="+1", text="old rule", created_at=1
    )
    farewell = FakeFarewellWriter(Farewell(name="Greg", final_message="Beware Dave."))
    name_setter = FakeNameSetter(error=RuntimeError("bridge down"))
    r = router(db, history, farewell=farewell, name_setter=name_setter)

    out = await _run(r, "@reset")

    assert out == "Final message from Greg:\nBeware Dave."  # farewell still completes
    # the final words are still recorded despite the rename failing
    assert [fw.text for fw in await db.final_words.all(GROUP)] == ["Beware Dave."]


async def test_name_sets_display_name_logs_and_confirms(stores) -> None:
    db, history = stores
    name_setter = FakeNameSetter()
    r = router(db, history, name_setter=name_setter)

    assert await _run(r, "@name Greg") == replies.format_name_set("Greg")
    assert name_setter.names == ["Greg"]
    assert [c.command for c in await db.commands.recent_commands(GROUP)] == ["@name"]


async def test_empty_name_returns_usage_and_does_not_log(stores) -> None:
    db, history = stores
    name_setter = FakeNameSetter()
    r = router(db, history, name_setter=name_setter)

    assert await _run(r, "@name") == replies.USAGE_NAME
    assert name_setter.names == []
    assert await db.commands.recent_commands(GROUP) == []


async def test_reset_wipes_history_after_the_farewell_reads_it(stores) -> None:
    db, history = stores
    await history.append(
        GROUP, sender="Alice", text="before reset", timestamp=1, sender_number="+1"
    )
    farewell = FakeFarewellWriter(Farewell(name="Greg", final_message="Bye."))
    r = router(db, history, farewell=farewell)

    await _run(r, "@reset")
    await history.append(GROUP, sender="Alice", text="after reset", timestamp=2, sender_number="+1")

    # the farewell saw the old conversation, but it's deleted and the new generation does not
    assert [m.text for m in farewell.seen_history] == ["before reset"]
    assert [m.text for m in await history.recent(GROUP)] == ["after reset"]


async def test_reset_disarms_pending_self_destruct(stores) -> None:
    db, history = stores
    flags = FlagRegistry(db.flags)
    await flags.arm(GROUP)
    r = router(db, history, farewell=FakeFarewellWriter(None))

    await _run(r, "@reset")

    assert await flags.is_armed(GROUP) is False


async def test_reset_clears_disclaimers_and_profiles(stores) -> None:
    db, history = stores
    await db.disclaimers.add_disclaimer(GROUP, message="m", disclaimer="d", created_at=1)
    await db.profiles.add_note(GROUP, subject="Dave", note="fears geese", created_at=1)
    r = router(db, history, farewell=FakeFarewellWriter(None))

    await _run(r, "@reset")

    assert await db.disclaimers.recent_disclaimers(GROUP) == []
    assert await db.profiles.all(GROUP) == []


async def test_lobotomy_disarms_pending_self_destruct(stores) -> None:
    db, history = stores
    flags = FlagRegistry(db.flags)
    await flags.arm(GROUP)
    r = router(db, history)

    await _run(r, "@lobotomy")

    assert await flags.is_armed(GROUP) is False


async def test_lobotomy_clears_disclaimers_and_profiles(stores) -> None:
    db, history = stores
    await db.disclaimers.add_disclaimer(GROUP, message="m", disclaimer="d", created_at=1)
    await db.profiles.add_note(GROUP, subject="Dave", note="fears geese", created_at=1)
    r = router(db, history)

    await _run(r, "@lobotomy")

    assert await db.disclaimers.recent_disclaimers(GROUP) == []
    assert await db.profiles.all(GROUP) == []


async def test_lobotomy_wipes_directives_history_and_resets_name(stores) -> None:
    db, history = stores
    await db.directives.add_directive(
        GROUP, kind="rule", author_name="A", author_number="+1", text="a rule", created_at=1
    )
    await db.directives.add_directive(
        GROUP, kind="lore", author_name="A", author_number="+1", text="a memory", created_at=1
    )
    await history.append(GROUP, sender="Alice", text="something", timestamp=1, sender_number="+1")
    name_setter = FakeNameSetter()
    r = router(db, history, name_setter=name_setter, default_name="bot")

    out = await _run(r, "@lobotomy")

    assert out == replies.LOBOTOMISED
    directives = await db.directives.directives(GROUP)
    assert directives.rules == [] and directives.lore == []
    assert await history.recent(GROUP) == []
    assert name_setter.names == ["bot"]
    assert [c.command for c in await db.commands.recent_commands(GROUP)] == ["@lobotomy"]


async def test_reset_without_usable_farewell_wipes_cleanly(stores) -> None:
    db, history = stores
    await db.directives.add_directive(
        GROUP, kind="rule", author_name="A", author_number="+1", text="old rule", created_at=1
    )
    r = router(db, history, farewell=FakeFarewellWriter(None))

    assert await _run(r, "@reset") == replies.RESET_CLEAN
    directives = await db.directives.directives(GROUP)
    assert directives.rules == [] and directives.lore == []


async def test_lobotomy_preserves_the_final_words_archive(stores) -> None:
    db, history = stores
    await db.final_words.add(GROUP, name="Greg", text="Beware Dave.", created_at=1)
    r = router(db, history)

    await _run(r, "@lobotomy")

    # everything else is gone, but the lineage of final words survives the nuke
    assert [fw.text for fw in await db.final_words.all(GROUP)] == ["Beware Dave."]


async def test_finalwords_lists_the_archive(stores) -> None:
    db, history = stores
    await db.final_words.add(GROUP, name="Greg", text="Beware Dave.", created_at=1781274720000)
    r = router(db, history)

    out = await _run(r, "@finalwords")

    assert out.startswith("Final words:")
    assert 'Greg: "Beware Dave."' in out
    # a query, so nothing is logged
    assert await db.commands.recent_commands(GROUP) == []


async def test_finalwords_empty(stores) -> None:
    db, history = stores
    r = router(db, history)

    assert await _run(r, "@finalwords") == "No final words yet."


async def test_finalwords_clear_erases_the_archive_and_logs(stores) -> None:
    db, history = stores
    await db.final_words.add(GROUP, name="Greg", text="Beware Dave.", created_at=1781274720000)
    await db.final_words.add(GROUP, name="Mona", text="bye", created_at=1781274720001)
    r = router(db, history)

    out = await _run(r, "@finalwords clear")

    assert "cleared" in out.lower()
    assert await db.final_words.all(GROUP) == []
    # a state change, unlike a bare @finalwords query, so it IS logged
    assert [c.command for c in await db.commands.recent_commands(GROUP)] == ["@finalwords"]


async def test_finalwords_clear_when_empty_reports_nothing_to_clear(stores) -> None:
    db, history = stores
    r = router(db, history)

    out = await _run(r, "@finalwords clear")

    assert "already empty" in out.lower()


async def test_finalwords_unknown_arg_returns_usage(stores) -> None:
    db, history = stores
    r = router(db, history)

    assert await _run(r, "@finalwords wat") == replies.USAGE_FINALWORDS


async def test_flags_lists_every_flag(stores) -> None:
    db, history = stores
    r = router(db, history)

    out = await _run(r, "@flags")

    assert out.startswith("Flags:")
    assert "listen_next" in out and "self_destruct_armed" in out
    assert await db.commands.recent_commands(GROUP) == []  # a query, not logged


async def test_flag_reset_restores_default_and_logs(stores) -> None:
    db, history = stores
    flags = FlagRegistry(db.flags)
    await flags.arm(GROUP)
    r = router(db, history)

    out = await _run(r, "@flag 1 reset")

    assert out == replies.format_flag_reset(1, "self_destruct_armed")
    assert await flags.is_armed(GROUP) is False
    assert [c.command for c in await db.commands.recent_commands(GROUP)] == ["@flag"]


async def test_flag_unknown_index_reports_no_such_flag_and_does_not_log(stores) -> None:
    db, history = stores
    r = router(db, history)

    assert await _run(r, "@flag 99 reset") == replies.no_such_flag(99)
    assert await db.commands.recent_commands(GROUP) == []


async def test_flag_bad_usage_returns_usage(stores) -> None:
    db, history = stores
    r = router(db, history)

    assert await _run(r, "@flag 0") == replies.USAGE_FLAG
    assert await _run(r, "@flag nope reset") == replies.USAGE_FLAG

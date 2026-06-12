from pathlib import Path

import pytest

from signal_chatbot.commands import replies
from signal_chatbot.commands.farewell import Farewell
from signal_chatbot.commands.parser import parse
from signal_chatbot.commands.router import CommandRouter
from signal_chatbot.history import HistoryStore
from signal_chatbot.state import StateStore
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
    state = StateStore(tmp_path / "state.sqlite", command_log_window=40)
    history = HistoryStore(tmp_path / "history.sqlite", window_max=40)
    await state.connect()
    await history.connect()
    yield state, history
    await state.aclose()
    await history.aclose()


def router(state, history, *, farewell=None, name_setter=None) -> CommandRouter:
    return CommandRouter(
        state=state,
        history=history,
        farewell=farewell or FakeFarewellWriter(None),
        name_setter=name_setter or FakeNameSetter(),
    )


async def _run(r: CommandRouter, text: str, **kw) -> str:
    command = parse(text)
    assert command is not None
    return await r.handle(command, message(text, **kw))


async def test_patch_stores_directive_logs_and_confirms(stores) -> None:
    state, history = stores
    r = router(state, history)

    assert await _run(r, "@patch no more puns") == replies.PATCHED
    assert [d.text for d in (await state.directives(GROUP)).patches] == ["no more puns"]
    assert [c.command for c in await state.recent_commands(GROUP)] == ["@patch"]


async def test_empty_patch_returns_usage_and_does_not_log(stores) -> None:
    state, history = stores
    r = router(state, history)

    assert await _run(r, "@patch") == replies.USAGE_PATCH
    assert (await state.directives(GROUP)).patches == []
    assert await state.recent_commands(GROUP) == []


async def test_rule_and_lore_store_under_their_kinds(stores) -> None:
    state, history = stores
    r = router(state, history)

    assert await _run(r, "@rule haiku only") == replies.RULE_LOGGED
    assert await _run(r, "@lore Dave fears geese") == replies.LORE_ADDED
    directives = await state.directives(GROUP)
    assert [d.text for d in directives.rules] == ["haiku only"]
    assert [d.text for d in directives.lore] == ["Dave fears geese"]


async def test_patchlist_renders_entries(stores) -> None:
    state, history = stores
    r = router(state, history)
    await _run(r, "@patch no puns")

    out = await _run(r, "@patchlist")

    assert out.startswith('Patches:\n1. "no puns" — Alice,')


async def test_clear_wipes_history_and_logs(stores) -> None:
    state, history = stores
    await history.append(GROUP, sender="Alice", text="old", timestamp=1)
    r = router(state, history)

    assert await _run(r, "@clear") == replies.HISTORY_CLEARED
    assert await history.recent(GROUP) == []
    assert [c.command for c in await state.recent_commands(GROUP)] == ["@clear"]


async def test_help_returns_help_text(stores) -> None:
    state, history = stores
    r = router(state, history)

    assert await _run(r, "@help") == replies.HELP_TEXT


async def test_reset_with_farewell_wipes_seeds_lore_and_announces(stores) -> None:
    state, history = stores
    await state.add_directive(
        GROUP, kind="rule", author_name="A", author_number="+1", text="old rule", created_at=1
    )
    farewell = FakeFarewellWriter(Farewell(name="Greg", final_message="Beware Dave."))
    name_setter = FakeNameSetter()
    r = router(state, history, farewell=farewell, name_setter=name_setter)

    out = await _run(r, "@reset")

    assert out == "Final message from Greg:\nBeware Dave."
    directives = await state.directives(GROUP)
    assert directives.rules == []
    assert [(d.text, d.author_name, d.author_number) for d in directives.lore] == [
        ("Beware Dave.", "Greg", "bot")
    ]
    assert [c.command for c in await state.recent_commands(GROUP)] == ["@reset"]
    assert name_setter.names == ["Greg"]  # reset renames the bot to its new self


async def test_reset_rename_failure_does_not_abort_the_reset(stores) -> None:
    state, history = stores
    await state.add_directive(
        GROUP, kind="rule", author_name="A", author_number="+1", text="old rule", created_at=1
    )
    farewell = FakeFarewellWriter(Farewell(name="Greg", final_message="Beware Dave."))
    name_setter = FakeNameSetter(error=RuntimeError("bridge down"))
    r = router(state, history, farewell=farewell, name_setter=name_setter)

    out = await _run(r, "@reset")

    assert out == "Final message from Greg:\nBeware Dave."  # farewell still completes
    directives = await state.directives(GROUP)
    assert [d.text for d in directives.lore] == ["Beware Dave."]  # lore still seeded


async def test_name_sets_display_name_logs_and_confirms(stores) -> None:
    state, history = stores
    name_setter = FakeNameSetter()
    r = router(state, history, name_setter=name_setter)

    assert await _run(r, "@name Greg") == replies.format_name_set("Greg")
    assert name_setter.names == ["Greg"]
    assert [c.command for c in await state.recent_commands(GROUP)] == ["@name"]


async def test_empty_name_returns_usage_and_does_not_log(stores) -> None:
    state, history = stores
    name_setter = FakeNameSetter()
    r = router(state, history, name_setter=name_setter)

    assert await _run(r, "@name") == replies.USAGE_NAME
    assert name_setter.names == []
    assert await state.recent_commands(GROUP) == []


async def test_reset_anchors_history_window_to_the_reset_point(stores) -> None:
    state, history = stores
    await history.append(GROUP, sender="Alice", text="before reset", timestamp=1)
    farewell = FakeFarewellWriter(Farewell(name="Greg", final_message="Bye."))
    r = router(state, history, farewell=farewell)

    await _run(r, "@reset")
    await history.append(GROUP, sender="Alice", text="after reset", timestamp=2)

    # the farewell saw the old conversation, but the new generation does not
    assert [m.text for m in farewell.seen_history] == ["before reset"]
    assert [m.text for m in await history.recent(GROUP)] == ["after reset"]


async def test_reset_without_usable_farewell_wipes_cleanly(stores) -> None:
    state, history = stores
    await state.add_directive(
        GROUP, kind="rule", author_name="A", author_number="+1", text="old rule", created_at=1
    )
    r = router(state, history, farewell=FakeFarewellWriter(None))

    assert await _run(r, "@reset") == replies.RESET_CLEAN
    directives = await state.directives(GROUP)
    assert directives.rules == [] and directives.lore == []

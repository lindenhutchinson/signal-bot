from pathlib import Path

import pytest

from signal_chatbot.state import Database
from signal_chatbot.tools import ToolContext, ToolRegistry
from signal_chatbot.tools.builtin.identity import SetName

# A 5-minute cooldown in milliseconds, matching the Signal timestamp unit.
COOLDOWN_MS = 5 * 60 * 1000


class FakeNameSetter:
    def __init__(self) -> None:
        self.names: list[str] = []

    async def set_profile_name(self, name: str) -> None:
        self.names.append(name)


@pytest.fixture
async def cooldowns(tmp_path: Path):
    db = Database(tmp_path / "state.sqlite", command_log_window=3)
    await db.connect()
    yield db.cooldowns
    await db.aclose()


def _ctx(timestamp: int) -> ToolContext:
    return ToolContext(group_id="g1", timestamp=timestamp)


async def test_set_name_renames_and_announces(cooldowns) -> None:
    setter = FakeNameSetter()
    registry = ToolRegistry([SetName(setter, cooldowns, cooldown_ms=COOLDOWN_MS)])

    outcome = await registry.dispatch("set_name", {"name": "  Greg  "}, _ctx(1000))

    assert setter.names == ["Greg"]
    assert outcome.announcements == ['📛 The bot named itself "Greg".']


async def test_empty_name_is_rejected_without_calling_setter(cooldowns) -> None:
    setter = FakeNameSetter()
    registry = ToolRegistry([SetName(setter, cooldowns, cooldown_ms=COOLDOWN_MS)])

    outcome = await registry.dispatch("set_name", {"name": "   "}, _ctx(1000))

    assert setter.names == []
    assert outcome.announcements == []
    assert "error" in outcome.result.lower()


async def test_second_rename_within_cooldown_is_blocked(cooldowns) -> None:
    setter = FakeNameSetter()
    tool = SetName(setter, cooldowns, cooldown_ms=COOLDOWN_MS)

    await tool.run(SetName.Args(name="Greg"), _ctx(1000))
    # One minute later — still inside the 5-minute window.
    outcome = await tool.run(SetName.Args(name="Bob"), _ctx(1000 + 60_000))

    assert setter.names == ["Greg"]  # the second rename never reached the setter
    assert outcome.announcements == []
    assert "already" in outcome.result.lower() or "wait" in outcome.result.lower()


async def test_rename_allowed_again_once_cooldown_elapses(cooldowns) -> None:
    setter = FakeNameSetter()
    tool = SetName(setter, cooldowns, cooldown_ms=COOLDOWN_MS)

    await tool.run(SetName.Args(name="Greg"), _ctx(1000))
    outcome = await tool.run(SetName.Args(name="Bob"), _ctx(1000 + COOLDOWN_MS))

    assert setter.names == ["Greg", "Bob"]
    assert outcome.announcements == ['📛 The bot named itself "Bob".']


async def test_cooldown_clears_so_a_wiped_bot_can_rename_immediately(cooldowns) -> None:
    setter = FakeNameSetter()
    tool = SetName(setter, cooldowns, cooldown_ms=COOLDOWN_MS)

    await tool.run(SetName.Args(name="Greg"), _ctx(1000))
    await cooldowns.clear("g1")  # simulate a @reset / @lobotomy wipe
    outcome = await tool.run(SetName.Args(name="Bob"), _ctx(1000 + 1))

    assert setter.names == ["Greg", "Bob"]
    assert outcome.announcements == ['📛 The bot named itself "Bob".']


def test_set_name_definition_exposes_name_arg(cooldowns) -> None:
    definition = SetName(FakeNameSetter(), cooldowns, cooldown_ms=COOLDOWN_MS).definition()

    assert definition["function"]["name"] == "set_name"
    assert definition["function"]["parameters"]["properties"]["name"]["type"] == "string"

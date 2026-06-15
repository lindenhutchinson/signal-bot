from pathlib import Path

import pytest

from signal_chatbot.state import Database
from signal_chatbot.tools.base import ToolContext, ToolOutcome
from signal_chatbot.tools.builtin.authoring import AddLore, AddRule

CTX = ToolContext(group_id="g1", timestamp=42)


class FakeName:
    """A minimal :class:`NameSource` returning a fixed display name."""

    def __init__(self, name: str) -> None:
        self.current = name


@pytest.fixture
async def directives(tmp_path: Path):
    db = Database(tmp_path / "state.sqlite", command_log_window=3)
    await db.connect()
    yield db.directives
    await db.aclose()


async def test_add_rule_writes_directive_and_announces(directives) -> None:
    tool = AddRule(directives, FakeName("Greg"))

    outcome = await tool.run(AddRule.Args(text="  no puns  "), CTX)

    stored = (await directives.directives("g1")).rules
    assert len(stored) == 1
    rule = stored[0]
    assert rule.kind == "rule"
    assert rule.text == "no puns"
    assert rule.author_name == "Greg"
    assert rule.author_number == "bot"
    assert rule.created_at == 42

    assert isinstance(outcome, ToolOutcome)
    assert outcome.announcements == ['⚖️ Greg added a rule: "no puns"']


async def test_add_lore_writes_directive_and_announces(directives) -> None:
    tool = AddLore(directives, FakeName("Greg"))

    outcome = await tool.run(AddLore.Args(text="Dave fears geese"), CTX)

    stored = (await directives.directives("g1")).lore
    assert len(stored) == 1
    lore = stored[0]
    assert lore.kind == "lore"
    assert lore.text == "Dave fears geese"
    assert lore.author_name == "Greg"
    assert lore.author_number == "bot"
    assert lore.created_at == 42

    assert outcome.announcements == ['📜 Greg added lore: "Dave fears geese"']


async def test_empty_rule_is_rejected_without_writing_or_announcing(directives) -> None:
    tool = AddRule(directives, FakeName("Greg"))

    outcome = await tool.run(AddRule.Args(text="   "), CTX)

    assert (await directives.directives("g1")).rules == []
    assert outcome.announcements == []
    assert "error" in outcome.result.lower()


async def test_empty_lore_is_rejected_without_writing_or_announcing(directives) -> None:
    tool = AddLore(directives, FakeName("Greg"))

    outcome = await tool.run(AddLore.Args(text=""), CTX)

    assert (await directives.directives("g1")).lore == []
    assert outcome.announcements == []
    assert "error" in outcome.result.lower()


def test_tool_names_and_definitions() -> None:
    assert AddRule.name == "add_rule"
    assert AddLore.name == "add_lore"
    definition = AddRule(None, FakeName("Greg")).definition()  # type: ignore[arg-type]
    assert definition["function"]["name"] == "add_rule"
    assert definition["function"]["parameters"]["properties"]["text"]["type"] == "string"

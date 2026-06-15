from pathlib import Path

import pytest

from signal_chatbot.botname import BotName
from signal_chatbot.state import Database
from signal_chatbot.tools import ToolRegistry
from signal_chatbot.tools.builtin import default_tools


class FakeNameSetter:
    async def set_profile_name(self, name: str) -> None:
        pass


@pytest.fixture
async def directives(tmp_path: Path):
    db = Database(tmp_path / "state.sqlite", command_log_window=3)
    await db.connect()
    yield db.directives
    await db.aclose()


async def test_default_tools_registers_authoring_tools(directives) -> None:
    name = BotName(FakeNameSetter(), initial="Bot")
    tools = default_tools(name, directives, None, wikipedia_max_section_chars=100)  # type: ignore[arg-type]

    registered = {d["function"]["name"] for d in ToolRegistry(tools).definitions()}

    assert {"add_rule", "add_lore", "set_name"} <= registered

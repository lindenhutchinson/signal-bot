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


def _names(tools) -> set[str]:
    return {d["function"]["name"] for d in ToolRegistry(tools).definitions()}


def _build(directives, **kw):
    """default_tools with the stateful deps stubbed as None (only names are inspected)."""
    name = BotName(FakeNameSetter(), initial="Bot")
    return default_tools(
        name,
        directives,
        None,  # profiles
        None,  # flags
        None,  # reactions
        None,  # wikipedia
        None,  # cooldowns (set_name not dispatched here — only names are inspected)
        wikipedia_max_section_chars=100,
        set_name_cooldown_ms=300_000,
        **kw,
    )  # type: ignore[arg-type]


async def test_default_tools_registers_authoring_tools(directives) -> None:
    assert {"add_rule", "add_lore", "set_name"} <= _names(_build(directives))


async def test_default_tools_registers_remember_about_user(directives) -> None:
    assert "remember_about_user" in _names(_build(directives))


async def test_default_tools_registers_listen_and_reaction(directives) -> None:
    assert {"listen_for_reply", "send_reaction"} <= _names(_build(directives))


async def test_seize_control_is_offered_to_the_model_but_hidden_from_info(directives) -> None:
    registry = ToolRegistry(_build(directives))
    # offered to the model (in the tool definitions)...
    assert "seize_control" in {d["function"]["name"] for d in registry.definitions()}
    # ...but never listed for humans via @info
    assert "seize_control" not in {n for n, _ in registry.summaries()}


async def test_web_search_included_only_when_provided(directives) -> None:
    assert "web_search" not in _names(_build(directives))

    class _StubWebSearch:
        name = "web_search"
        description = "stub"

        def definition(self) -> dict:
            return {"type": "function", "function": {"name": "web_search", "parameters": {}}}

    with_search = _build(directives, web_search=_StubWebSearch())
    assert "web_search" in _names(with_search)

from signal_chatbot.tools import ToolRegistry
from signal_chatbot.tools.builtin.identity import SetName


class FakeNameSetter:
    def __init__(self) -> None:
        self.names: list[str] = []

    async def set_profile_name(self, name: str) -> None:
        self.names.append(name)


async def test_set_name_calls_setter_and_confirms() -> None:
    setter = FakeNameSetter()
    registry = ToolRegistry([SetName(setter)])

    result = await registry.dispatch("set_name", {"name": "  Greg  "})

    assert setter.names == ["Greg"]
    assert "Greg" in result


async def test_empty_name_is_rejected_without_calling_setter() -> None:
    setter = FakeNameSetter()
    registry = ToolRegistry([SetName(setter)])

    result = await registry.dispatch("set_name", {"name": "   "})

    assert setter.names == []
    assert "error" in result.lower()


def test_set_name_definition_exposes_name_arg() -> None:
    definition = SetName(FakeNameSetter()).definition()

    assert definition["function"]["name"] == "set_name"
    assert definition["function"]["parameters"]["properties"]["name"]["type"] == "string"

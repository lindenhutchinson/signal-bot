import pytest
from pydantic import BaseModel

from signal_chatbot.tools import Tool, ToolRegistry


class Echo(Tool):
    name = "echo"
    description = "Echo the given text back."

    class Args(BaseModel):
        text: str

    async def run(self, args: "Echo.Args") -> str:
        return args.text.upper()


def test_definition_matches_openai_tool_schema() -> None:
    definition = Echo().definition()

    assert definition["type"] == "function"
    fn = definition["function"]
    assert fn["name"] == "echo"
    assert fn["description"] == "Echo the given text back."
    assert fn["parameters"]["properties"]["text"]["type"] == "string"


async def test_registry_dispatches_and_validates_args() -> None:
    registry = ToolRegistry([Echo()])

    result = await registry.dispatch("echo", {"text": "hi"})

    assert result == "HI"


async def test_registry_reports_unknown_tool() -> None:
    registry = ToolRegistry([Echo()])

    result = await registry.dispatch("nope", {})

    assert "unknown tool" in result.lower()


async def test_registry_reports_invalid_args_without_raising() -> None:
    registry = ToolRegistry([Echo()])

    result = await registry.dispatch("echo", {"wrong": "field"})

    assert "error" in result.lower()


async def test_registry_catches_tool_exceptions() -> None:
    class Boom(Tool):
        name = "boom"
        description = "Always fails."

        class Args(BaseModel):
            pass

        async def run(self, args: "Boom.Args") -> str:
            raise ValueError("kaboom")

    registry = ToolRegistry([Boom()])

    result = await registry.dispatch("boom", {})

    assert "error" in result.lower()


def test_definitions_returns_all_registered_tools() -> None:
    registry = ToolRegistry([Echo()])

    definitions = registry.definitions()

    assert [d["function"]["name"] for d in definitions] == ["echo"]


def test_duplicate_tool_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([Echo(), Echo()])

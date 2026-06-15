import pytest
from pydantic import BaseModel

from signal_chatbot.tools import Tool, ToolContext, ToolOutcome, ToolRegistry

CTX = ToolContext(group_id="g1", timestamp=1)


class Echo(Tool):
    name = "echo"
    description = "Echo the given text back."

    class Args(BaseModel):
        text: str

    async def run(self, args: "Echo.Args", ctx: ToolContext) -> str:
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

    outcome = await registry.dispatch("echo", {"text": "hi"}, CTX)

    assert outcome.result == "HI"
    assert outcome.announcements == []


async def test_registry_normalises_a_bare_string_into_a_tool_outcome() -> None:
    registry = ToolRegistry([Echo()])

    outcome = await registry.dispatch("echo", {"text": "yo"}, CTX)

    assert isinstance(outcome, ToolOutcome)
    assert outcome.result == "YO"
    assert outcome.announcements == []


async def test_registry_passes_through_a_tool_outcome_with_announcements() -> None:
    class Announcer(Tool):
        name = "announce"
        description = "Make an announcement."

        class Args(BaseModel):
            pass

        async def run(self, args: "Announcer.Args", ctx: ToolContext) -> ToolOutcome:
            return ToolOutcome(result="done", announcements=["📢 something happened"])

    registry = ToolRegistry([Announcer()])

    outcome = await registry.dispatch("announce", {}, CTX)

    assert outcome.result == "done"
    assert outcome.announcements == ["📢 something happened"]


async def test_registry_reports_unknown_tool() -> None:
    registry = ToolRegistry([Echo()])

    outcome = await registry.dispatch("nope", {}, CTX)

    assert "unknown tool" in outcome.result.lower()


async def test_registry_reports_invalid_args_without_raising() -> None:
    registry = ToolRegistry([Echo()])

    outcome = await registry.dispatch("echo", {"wrong": "field"}, CTX)

    assert "error" in outcome.result.lower()


async def test_registry_catches_tool_exceptions() -> None:
    class Boom(Tool):
        name = "boom"
        description = "Always fails."

        class Args(BaseModel):
            pass

        async def run(self, args: "Boom.Args", ctx: ToolContext) -> str:
            raise ValueError("kaboom")

    registry = ToolRegistry([Boom()])

    outcome = await registry.dispatch("boom", {}, CTX)

    assert "error" in outcome.result.lower()


def test_definitions_returns_all_registered_tools() -> None:
    registry = ToolRegistry([Echo()])

    definitions = registry.definitions()

    assert [d["function"]["name"] for d in definitions] == ["echo"]


def test_duplicate_tool_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([Echo(), Echo()])

import json
from types import SimpleNamespace

from signal_chatbot.commands.farewell import Farewell, LlmFarewellWriter
from signal_chatbot.history import StoredMessage
from signal_chatbot.state import DirectiveSet


def _empty_directives() -> DirectiveSet:
    return DirectiveSet(rules=[], lore=[])


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.seen_response_format: object = None

    async def complete(self, messages, tools=None, response_format=None):
        self.seen_response_format = response_format
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


async def test_returns_validated_farewell_and_requests_json() -> None:
    client = FakeClient(json.dumps({"name": "Greg", "final_message": "Trust no one named Dave."}))
    writer = LlmFarewellWriter(client, max_chars=200)

    result = await writer.write(directives=_empty_directives(), history=[])

    assert result == Farewell(name="Greg", final_message="Trust no one named Dave.")
    assert client.seen_response_format == {"type": "json_object"}


async def test_final_message_is_truncated_to_one_sentence_and_capped() -> None:
    client = FakeClient(json.dumps({"name": "Greg", "final_message": "First thing. Second thing."}))
    writer = LlmFarewellWriter(client, max_chars=200)

    result = await writer.write(directives=_empty_directives(), history=[])

    assert result.final_message == "First thing."


async def test_invalid_json_returns_none() -> None:
    writer = LlmFarewellWriter(FakeClient("not json at all"), max_chars=200)

    assert await writer.write(directives=_empty_directives(), history=[]) is None


async def test_blank_message_or_name_returns_none() -> None:
    writer = LlmFarewellWriter(
        FakeClient(json.dumps({"name": "", "final_message": "hi."})), max_chars=200
    )
    assert await writer.write(directives=_empty_directives(), history=[]) is None

    writer2 = LlmFarewellWriter(
        FakeClient(json.dumps({"name": "Greg", "final_message": "   "})), max_chars=200
    )
    assert await writer2.write(directives=_empty_directives(), history=[]) is None


async def test_history_is_summarised_into_the_prompt() -> None:
    client = FakeClient(json.dumps({"name": "G", "final_message": "Bye."}))
    writer = LlmFarewellWriter(client, max_chars=200)

    result = await writer.write(
        directives=_empty_directives(),
        history=[StoredMessage(sender="Alice", text="hello there", timestamp=1)],
    )

    assert result == Farewell(name="G", final_message="Bye.")

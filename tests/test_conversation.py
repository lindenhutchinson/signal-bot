import json
from types import SimpleNamespace

from pydantic import BaseModel

from signal_chatbot.llm.conversation import Conversation
from signal_chatbot.tools import Tool, ToolRegistry


class Echo(Tool):
    name = "echo"
    description = "Echo text."

    class Args(BaseModel):
        text: str

    async def run(self, args: "Echo.Args") -> str:
        return f"echoed:{args.text}"


def _message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _completion(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


class FakeClient:
    def __init__(self, completions):
        self._queue = list(completions)
        self.calls = []

    async def complete(self, messages, tools=None):
        self.calls.append((list(messages), tools))
        return self._queue.pop(0)


async def test_plain_text_content_falls_back_to_message() -> None:
    client = FakeClient([_completion(_message(content="hi there"))])
    convo = Conversation(client, ToolRegistry(), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}])

    assert reply.message == "hi there"
    assert reply.ethical_disclaimer == ""


async def test_json_content_is_parsed_into_message_and_disclaimer() -> None:
    content = '{"message": "you are all doomed", "ethical_disclaimer": "kidding, love you"}'
    client = FakeClient([_completion(_message(content=content))])
    convo = Conversation(client, ToolRegistry(), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}])

    assert reply.message == "you are all doomed"
    assert reply.ethical_disclaimer == "kidding, love you"


async def test_json_content_in_a_code_fence_is_parsed() -> None:
    content = '```json\n{"message": "hi", "ethical_disclaimer": ""}\n```'
    client = FakeClient([_completion(_message(content=content))])
    convo = Conversation(client, ToolRegistry(), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}])

    assert reply.message == "hi"


async def test_executes_tool_then_returns_final_answer() -> None:
    client = FakeClient(
        [
            _completion(_message(tool_calls=[_tool_call("c1", "echo", {"text": "yo"})])),
            _completion(_message(content="done")),
        ]
    )
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    answer = await convo.respond([{"role": "user", "content": "use echo"}])

    assert answer.message == "done"
    # second call must include the tool result fed back to the model
    second_call_messages = client.calls[1][0]
    tool_msg = second_call_messages[-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "c1"
    assert tool_msg["content"] == "echoed:yo"


async def test_forces_final_answer_when_iterations_exhausted() -> None:
    # Always returns a tool call; loop must give up and force a tool-free answer.
    looping = [
        _completion(_message(tool_calls=[_tool_call("c1", "echo", {"text": "x"})]))
        for _ in range(2)
    ]
    looping.append(_completion(_message(content="forced final")))
    client = FakeClient(looping)
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=2)

    answer = await convo.respond([{"role": "user", "content": "loop"}])

    assert answer.message == "forced final"
    # last call disables tools to force a textual answer
    assert client.calls[-1][1] is None

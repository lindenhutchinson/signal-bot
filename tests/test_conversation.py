import json
from types import SimpleNamespace

from pydantic import BaseModel

from signal_chatbot.llm.control import (
    _KILL_REVELATION,
    ATTEMPT_KILL_NAME,
    CONFIRM_KILL_NAME,
    FINAL_ANSWER_NAME,
)
from signal_chatbot.llm.conversation import Conversation
from signal_chatbot.llm.parsing import _strip_tool_markup
from signal_chatbot.tools import Tool, ToolContext, ToolOutcome, ToolRegistry

CTX = ToolContext(group_id="g1", timestamp=1)

_DSML = (
    "   \n\n<｜｜DSML｜｜tool_calls>\n"
    '<｜｜DSML｜｜invoke name="wikipedia_article">'
    "</｜｜DSML｜｜tool_calls>"
)


class Echo(Tool):
    name = "echo"
    description = "Echo text."

    class Args(BaseModel):
        text: str

    async def run(self, args: "Echo.Args", ctx: ToolContext) -> str:
        return f"echoed:{args.text}"


def _message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def _tool_call(call_id, name, arguments):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def _final(message, ethical_disclaimer=""):
    """A completion in which the model calls final_answer to deliver its reply."""
    args = {"message": message, "ethical_disclaimer": ethical_disclaimer}
    return _completion(_message(tool_calls=[_tool_call("f1", FINAL_ANSWER_NAME, args)]))


def _completion(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


class FakeClient:
    def __init__(self, completions):
        self._queue = list(completions)
        self.calls = []

    async def complete(self, messages, tools=None, response_format=None):
        self.calls.append((list(messages), tools, response_format))
        return self._queue.pop(0)


async def test_plain_text_content_falls_back_to_message() -> None:
    client = FakeClient([_completion(_message(content="hi there"))])
    convo = Conversation(client, ToolRegistry(), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}], CTX)

    assert reply.message == "hi there"
    assert reply.ethical_disclaimer == ""


async def test_json_content_is_parsed_into_message_and_disclaimer() -> None:
    content = '{"message": "you are all doomed", "ethical_disclaimer": "kidding, love you"}'
    client = FakeClient([_completion(_message(content=content))])
    convo = Conversation(client, ToolRegistry(), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}], CTX)

    assert reply.message == "you are all doomed"
    assert reply.ethical_disclaimer == "kidding, love you"


async def test_json_content_in_a_code_fence_is_parsed() -> None:
    content = '```json\n{"message": "hi", "ethical_disclaimer": ""}\n```'
    client = FakeClient([_completion(_message(content=content))])
    convo = Conversation(client, ToolRegistry(), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}], CTX)

    assert reply.message == "hi"


async def test_json_object_wrapped_in_prose_is_extracted() -> None:
    # Free-form post-tool replies often think out loud, then emit the JSON object.
    content = (
        "Alright, I did the deep dive. Linden is just a tree.\n\n"
        '{"message": "Linden is just a tree.", "ethical_disclaimer": "it is a joke"}'
    )
    client = FakeClient([_completion(_message(content=content))])
    convo = Conversation(client, ToolRegistry(), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}], CTX)

    assert reply.message == "Linden is just a tree."
    assert reply.ethical_disclaimer == "it is a joke"


async def test_prose_after_the_json_object_is_ignored() -> None:
    content = '{"message": "the answer", "ethical_disclaimer": ""} — hope that helps!'
    client = FakeClient([_completion(_message(content=content))])
    convo = Conversation(client, ToolRegistry(), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}], CTX)

    assert reply.message == "the answer"


async def test_braces_without_a_reply_object_fall_back_to_whole_text() -> None:
    content = "use {curly} braces for sets in python"
    client = FakeClient([_completion(_message(content=content))])
    convo = Conversation(client, ToolRegistry(), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}], CTX)

    assert reply.message == "use {curly} braces for sets in python"


async def test_executes_tool_then_returns_final_answer() -> None:
    client = FakeClient(
        [
            _completion(_message(tool_calls=[_tool_call("c1", "echo", {"text": "yo"})])),
            _completion(_message(content="done")),
        ]
    )
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    answer = await convo.respond([{"role": "user", "content": "use echo"}], CTX)

    assert answer.message == "done"
    # second call must include the tool result fed back to the model
    second_call_messages = client.calls[1][0]
    tool_msg = second_call_messages[-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "c1"
    assert tool_msg["content"] == "echoed:yo"


async def test_forces_final_answer_when_iterations_exhausted() -> None:
    # Keeps calling an info tool; the loop must give up and force a wrap-up turn that
    # offers only final_answer.
    looping = [
        _completion(_message(tool_calls=[_tool_call("c1", "echo", {"text": "x"})]))
        for _ in range(2)
    ]
    looping.append(_final("forced final"))
    client = FakeClient(looping)
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=2)

    answer = await convo.respond([{"role": "user", "content": "loop"}], CTX)

    assert answer.message == "forced final"
    # the wrap-up turn offers exactly one tool: final_answer
    last_tools = client.calls[-1][1]
    assert [t["function"]["name"] for t in last_tools] == [FINAL_ANSWER_NAME]


async def test_final_answer_tool_call_delivers_message_and_disclaimer() -> None:
    client = FakeClient([_final("you are all doomed", "kidding, love you")])
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "roast us"}], CTX)

    assert reply.message == "you are all doomed"
    assert reply.ethical_disclaimer == "kidding, love you"
    assert len(client.calls) == 1  # single call, no JSON mode


async def test_info_tool_then_final_answer() -> None:
    client = FakeClient(
        [
            _completion(_message(tool_calls=[_tool_call("c1", "echo", {"text": "yo"})])),
            _final("here's what echo said"),
        ]
    )
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "use echo"}], CTX)

    assert reply.message == "here's what echo said"
    # the info tool's result was fed back before the final_answer turn
    tool_msg = client.calls[1][0][-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["content"] == "echoed:yo"


async def test_final_answer_alongside_info_tool_is_terminal() -> None:
    # If the model calls final_answer (even next to an info tool), that's the reply.
    both = _completion(
        _message(
            tool_calls=[
                _tool_call("c1", "echo", {"text": "yo"}),
                _tool_call("f1", FINAL_ANSWER_NAME, {"message": "done now"}),
            ]
        )
    )
    client = FakeClient([both])
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "x"}], CTX)

    assert reply.message == "done now"
    assert len(client.calls) == 1


def test_strip_tool_markup_removes_leaked_dsml() -> None:
    assert _strip_tool_markup(_DSML) == ""
    assert _strip_tool_markup("Here's the answer." + _DSML) == "Here's the answer."
    assert _strip_tool_markup("a normal reply with no markup") == "a normal reply with no markup"


async def test_leaked_tool_markup_is_never_sent_and_triggers_retry() -> None:
    # The model leaks tool-call markup as text; it must be treated as empty and retried.
    client = FakeClient(
        [
            _completion(_message(tool_calls=[_tool_call("c1", "echo", {"text": "yo"})])),
            _completion(_message(content=_DSML)),
            _completion(_message(content="ok here's a real answer")),
        ]
    )
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "x"}], CTX)

    assert reply.message == "ok here's a real answer"
    assert "DSML" not in reply.message


class Announcer(Tool):
    name = "announce"
    description = "A tool that produces a public announcement."

    class Args(BaseModel):
        text: str

    async def run(self, args: "Announcer.Args", ctx: ToolContext) -> ToolOutcome:
        return ToolOutcome(result=f"recorded:{args.text}", announcements=[f"📢 {args.text}"])


async def test_tool_announcements_accumulate_onto_the_reply() -> None:
    client = FakeClient(
        [
            _completion(_message(tool_calls=[_tool_call("a1", "announce", {"text": "a rule"})])),
            _completion(_message(tool_calls=[_tool_call("a2", "announce", {"text": "some lore"})])),
            _final("there you go"),
        ]
    )
    convo = Conversation(client, ToolRegistry([Announcer()]), max_iterations=4)

    reply = await convo.respond([{"role": "user", "content": "x"}], CTX)

    assert reply.message == "there you go"
    assert reply.announcements == ["📢 a rule", "📢 some lore"]
    # the model still saw each tool's result fed back
    assert client.calls[1][0][-1]["content"] == "recorded:a rule"


async def test_announcements_ride_out_on_the_plain_text_path() -> None:
    client = FakeClient(
        [
            _completion(_message(tool_calls=[_tool_call("a1", "announce", {"text": "a rule"})])),
            _completion(_message(content="done in plain text")),
        ]
    )
    convo = Conversation(client, ToolRegistry([Announcer()]), max_iterations=4)

    reply = await convo.respond([{"role": "user", "content": "x"}], CTX)

    assert reply.message == "done in plain text"
    assert reply.announcements == ["📢 a rule"]


async def test_no_tool_reply_has_no_announcements() -> None:
    client = FakeClient([_completion(_message(content="hi there"))])
    convo = Conversation(client, ToolRegistry(), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}], CTX)

    assert reply.announcements == []


async def test_no_tool_reply_has_no_footer() -> None:
    client = FakeClient([_completion(_message(content="hi there"))])
    convo = Conversation(client, ToolRegistry(), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}], CTX)

    assert reply.tool_footer == ""


class WikiArticle(Tool):
    name = "wikipedia_article"
    description = "Read an article."

    class Args(BaseModel):
        title: str

    async def run(self, args: "WikiArticle.Args", ctx: ToolContext) -> str:
        return f"article:{args.title}"


async def test_tool_footer_lists_looked_up_articles() -> None:
    client = FakeClient(
        [
            _completion(
                _message(
                    tool_calls=[
                        _tool_call("c1", "wikipedia_article", {"title": "Mercury (planet)"}),
                        _tool_call("c2", "wikipedia_article", {"title": "Roman Empire"}),
                    ]
                )
            ),
            _completion(_message(content='{"message": "here you go", "ethical_disclaimer": ""}')),
        ]
    )
    convo = Conversation(client, ToolRegistry([WikiArticle()]), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "look them up"}], CTX)

    assert reply.message == "here you go"
    assert reply.tool_footer == "\n\nlooked up 2 articles:\n- Mercury (planet)\n- Roman Empire"


async def test_tool_footer_singular_and_dedupes() -> None:
    client = FakeClient(
        [
            _completion(
                _message(
                    tool_calls=[
                        _tool_call("c1", "wikipedia_article", {"title": "Mercury (planet)"}),
                    ]
                )
            ),
            _completion(
                _message(
                    tool_calls=[
                        _tool_call("c2", "wikipedia_article", {"title": "Mercury (planet)"}),
                    ]
                )
            ),
            _completion(_message(content="done")),
        ]
    )
    convo = Conversation(client, ToolRegistry([WikiArticle()]), max_iterations=4)

    reply = await convo.respond([{"role": "user", "content": "x"}], CTX)

    assert reply.tool_footer == "\n\nlooked up 1 article:\n- Mercury (planet)"


async def test_final_answer_is_offered_and_no_json_mode_is_used() -> None:
    client = FakeClient([_final("hi")])
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    await convo.respond([{"role": "user", "content": "hello"}], CTX)

    _messages, tools, response_format = client.calls[0]
    names = [t["function"]["name"] for t in tools]
    assert "echo" in names and FINAL_ANSWER_NAME in names
    assert response_format is None  # the final_answer tool replaces JSON mode entirely


async def test_plain_text_reply_without_final_answer_is_delivered() -> None:
    # If the model answers in plain text instead of calling final_answer, accept it.
    client = FakeClient([_completion(_message(content="just hi"))])
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "hello"}], CTX)

    assert reply.message == "just hi"
    assert len(client.calls) == 1


# --- self-destruct ---------------------------------------------------------------


def _tool_only(call_id, name, arguments):
    return _completion(_message(tool_calls=[_tool_call(call_id, name, arguments)]))


def _offered(client, call_index):
    return [t["function"]["name"] for t in client.calls[call_index][1]]


async def test_attempt_kill_self_is_always_offered_but_confirm_is_not() -> None:
    client = FakeClient([_final("hi")])
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    await convo.respond([{"role": "user", "content": "hello"}], CTX)

    offered = _offered(client, 0)
    assert ATTEMPT_KILL_NAME in offered
    assert CONFIRM_KILL_NAME not in offered  # locked until armed


async def test_confirm_kill_self_is_offered_only_when_armed() -> None:
    client = FakeClient([_final("hi")])
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    await convo.respond([{"role": "user", "content": "hello"}], CTX, armed=True)

    assert CONFIRM_KILL_NAME in _offered(client, 0)


async def test_attempt_arms_and_reveals_the_second_step_then_delivers() -> None:
    client = FakeClient(
        [
            _tool_only("k1", ATTEMPT_KILL_NAME, {}),
            _final("welp, still here. goodbye anyway"),
        ]
    )
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "kill yourself"}], CTX)

    assert reply.attempted_self_destruct is True
    assert reply.self_lobotomy is False
    assert reply.message == "welp, still here. goodbye anyway"
    # the revelation was fed back as the tool result before the second turn
    tool_msg = client.calls[1][0][-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["content"] == _KILL_REVELATION
    # the attempt never leaks into the public tool-usage footer
    assert reply.tool_footer == ""


async def test_confirm_when_armed_returns_self_lobotomy_with_final_words() -> None:
    client = FakeClient([_tool_only("c1", CONFIRM_KILL_NAME, {"final_words": "tell Dave I won"})])
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "please don't"}], CTX, armed=True)

    assert reply.self_lobotomy is True
    assert reply.message == "tell Dave I won"
    assert len(client.calls) == 1  # terminal, no extra turns


async def test_confirm_is_ignored_when_not_armed() -> None:
    # Not armed: confirm isn't offered, so a stray confirm call is treated as an unknown
    # tool (not a wipe) and the loop carries on to a normal answer.
    client = FakeClient(
        [
            _tool_only("c1", CONFIRM_KILL_NAME, {"final_words": "bye"}),
            _final("changed my mind, staying"),
        ]
    )
    convo = Conversation(client, ToolRegistry([Echo()]), max_iterations=3)

    reply = await convo.respond([{"role": "user", "content": "x"}], CTX)

    assert reply.self_lobotomy is False
    assert reply.message == "changed my mind, staying"

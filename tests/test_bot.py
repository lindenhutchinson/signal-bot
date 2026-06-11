from pathlib import Path

import pytest

from signal_chatbot.bot import Bot
from signal_chatbot.history import HistoryStore
from signal_chatbot.llm.prompt import BOT_SENDER
from signal_chatbot.transport.models import IncomingMessage, OutgoingMessage

GROUP = "group.allowed="
OTHER_GROUP = "group.other="


def message(
    text: str, *, group: str = GROUP, sender_number: str = "+61400000001"
) -> IncomingMessage:
    return IncomingMessage(
        group_id=group,
        sender_number=sender_number,
        sender_name="Alice",
        text=text,
        timestamp=1,
    )


class FakeSignal:
    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []

    async def send(self, message: OutgoingMessage) -> None:
        self.sent.append(message)


class FakeConversation:
    def __init__(self, reply: str = "the answer", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.seen: list[list[dict]] = []

    async def respond(self, messages: list[dict]) -> str:
        self.seen.append(messages)
        if self.error is not None:
            raise self.error
        return self.reply


@pytest.fixture
async def history(tmp_path: Path) -> HistoryStore:
    store = HistoryStore(tmp_path / "h.sqlite", window_max=50)
    await store.connect()
    yield store
    await store.aclose()


def make_bot(history, signal, conversation, **overrides) -> Bot:
    kwargs = dict(
        signal=signal,
        history=history,
        conversation=conversation,
        system_prompt="You are Bot.",
        allowed_group_ids=[GROUP],
        allowed_senders=[],
        trigger_alias="@bot",
        error_reply="oops",
    )
    kwargs.update(overrides)
    return Bot(**kwargs)


async def test_ignores_messages_from_other_groups(history) -> None:
    signal, convo = FakeSignal(), FakeConversation()
    bot = make_bot(history, signal, convo)

    await bot.handle(message("@bot hi", group=OTHER_GROUP))

    assert signal.sent == []
    assert await history.recent(OTHER_GROUP) == []


async def test_stores_untriggered_messages_but_does_not_reply(history) -> None:
    signal, convo = FakeSignal(), FakeConversation()
    bot = make_bot(history, signal, convo)

    await bot.handle(message("just chatting"))

    assert signal.sent == []
    assert [m.text for m in await history.recent(GROUP)] == ["just chatting"]


async def test_replies_when_triggered_and_records_reply(history) -> None:
    signal, convo = FakeSignal(), FakeConversation(reply="hello!")
    bot = make_bot(history, signal, convo)

    await bot.handle(message("@bot hello"))

    assert len(signal.sent) == 1
    assert signal.sent[0].group_id == GROUP
    assert signal.sent[0].text == "hello!"
    stored = await history.recent(GROUP)
    assert stored[-2].text == "@bot hello"
    assert stored[-1].sender == BOT_SENDER
    assert stored[-1].text == "hello!"


async def test_trigger_is_case_insensitive(history) -> None:
    signal, convo = FakeSignal(), FakeConversation()
    bot = make_bot(history, signal, convo)

    await bot.handle(message("Hey @BOT what's up"))

    assert len(signal.sent) == 1


async def test_sender_allowlist_blocks_other_senders(history) -> None:
    signal, convo = FakeSignal(), FakeConversation()
    bot = make_bot(history, signal, convo, allowed_senders=["+61400000999"])

    await bot.handle(message("@bot hi", sender_number="+61400000001"))

    assert signal.sent == []
    assert await history.recent(GROUP) == []


async def test_error_during_completion_sends_fallback_reply(history) -> None:
    signal = FakeSignal()
    convo = FakeConversation(error=RuntimeError("api down"))
    bot = make_bot(history, signal, convo)

    await bot.handle(message("@bot hi"))

    assert signal.sent[0].text == "oops"

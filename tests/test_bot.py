from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from signal_chatbot.bot import _UNPROMPTED_NUDGE, Bot
from signal_chatbot.commands.parser import Command
from signal_chatbot.history import HistoryStore
from signal_chatbot.llm.prompt import BOT_SENDER
from signal_chatbot.llm.reply import BotReply
from signal_chatbot.state import DirectiveSet
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
    def __init__(
        self,
        reply: str = "the answer",
        disclaimer: str = "",
        error: Exception | None = None,
        footer: str = "",
        attempted_self_destruct: bool = False,
        self_lobotomy: bool = False,
        announcements: list[str] | None = None,
    ) -> None:
        self.reply = reply
        self.disclaimer = disclaimer
        self.error = error
        self.footer = footer
        self.attempted = attempted_self_destruct
        self.self_lobotomy = self_lobotomy
        self.announcements = announcements or []
        self.seen: list[list[dict]] = []
        self.seen_armed: list[bool] = []
        self.seen_ctx: list = []

    async def respond(self, messages, ctx, *, armed: bool = False) -> BotReply:
        self.seen.append(messages)
        self.seen_armed.append(armed)
        self.seen_ctx.append(ctx)
        if self.error is not None:
            raise self.error
        return BotReply(
            message=self.reply,
            ethical_disclaimer=self.disclaimer,
            tool_footer=self.footer,
            announcements=list(self.announcements),
            attempted_self_destruct=self.attempted,
            self_lobotomy=self.self_lobotomy,
        )


class FakeLobotomiser:
    def __init__(self) -> None:
        self.wiped: list[str] = []

    async def wipe(self, group_id: str) -> None:
        self.wiped.append(group_id)


class FakeName:
    def __init__(self, current: str = "Greg") -> None:
        self.current = current


class FakeDisclaimers:
    def __init__(self) -> None:
        self.logged: list[tuple] = []

    async def add_disclaimer(
        self, group_id: str, *, message: str, disclaimer: str, created_at: int
    ) -> None:
        self.logged.append((group_id, message, disclaimer, created_at))


class FakeCommands:
    def __init__(self, reply: str = "ok", error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error
        self.handled: list[Command] = []

    async def handle(self, command: Command, message) -> str:
        self.handled.append(command)
        if self.error is not None:
            raise self.error
        return self.reply


class FakeState:
    def __init__(self, armed: bool = False) -> None:
        self.directives_calls: list[str] = []
        self.armed: dict[str, int] = {GROUP: 0} if armed else {}

    async def directives(self, group_id: str) -> DirectiveSet:
        self.directives_calls.append(group_id)
        return DirectiveSet(rules=[], lore=[])

    async def recent_commands(self, group_id: str):
        return []

    async def is_suicide_armed(self, group_id: str) -> bool:
        return group_id in self.armed

    async def arm_suicide(self, group_id: str, *, at: int) -> None:
        self.armed[group_id] = at


@pytest.fixture
async def history(tmp_path: Path) -> HistoryStore:
    store = HistoryStore(tmp_path / "h.sqlite", window_max=50)
    await store.connect()
    yield store
    await store.aclose()


def make_bot(history, signal, conversation, **overrides) -> Bot:
    # One FakeState satisfies all three split state Protocols (directives, command log,
    # arming); tests pass it via ``state=`` and it's fanned out to each dependency.
    state = overrides.pop("state", None) or FakeState()
    kwargs = dict(
        signal=signal,
        history=history,
        conversation=conversation,
        commands=FakeCommands(),
        directives=state,
        command_log=state,
        arming=state,
        disclaimers=FakeDisclaimers(),
        lobotomiser=FakeLobotomiser(),
        name=FakeName(),
        system_prompt="You are Bot.",
        allowed_group_ids=[GROUP],
        allowed_senders=[],
        trigger_alias="@bot",
        error_reply="oops",
        timezone=ZoneInfo("Australia/Sydney"),
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


async def test_command_is_intercepted_replied_and_kept_out_of_history(history) -> None:
    signal, convo = FakeSignal(), FakeConversation()
    commands = FakeCommands(reply="Rule logged. ⚖️")
    bot = make_bot(history, signal, convo, commands=commands)

    await bot.handle(message("@rule no puns"))

    assert [c.name.value for c in commands.handled] == ["rule"]
    assert signal.sent[0].text == "Rule logged. ⚖️"
    assert convo.seen == []  # LLM never called
    assert await history.recent(GROUP) == []  # command not stored as conversation


async def test_failing_command_sends_fallback_and_does_not_raise(history) -> None:
    signal, convo = FakeSignal(), FakeConversation()
    commands = FakeCommands(error=RuntimeError("boom"))
    bot = make_bot(history, signal, convo, commands=commands)

    await bot.handle(message("@rule x"))

    assert signal.sent[0].text == "oops"


async def test_command_from_disallowed_group_is_ignored(history) -> None:
    signal, convo = FakeSignal(), FakeConversation()
    commands = FakeCommands()
    bot = make_bot(history, signal, convo, commands=commands)

    await bot.handle(message("@rule x", group=OTHER_GROUP))

    assert commands.handled == []
    assert signal.sent == []


async def test_ethical_disclaimer_is_logged_but_not_sent(history) -> None:
    signal = FakeSignal()
    convo = FakeConversation(reply="you're all doomed", disclaimer="jk, love you")
    disclaimers = FakeDisclaimers()
    bot = make_bot(history, signal, convo, disclaimers=disclaimers)

    await bot.handle(message("@bot roast us"))

    assert signal.sent[0].text == "you're all doomed"  # disclaimer never reaches Signal
    assert disclaimers.logged == [(GROUP, "you're all doomed", "jk, love you", 1)]


async def test_tool_footer_is_sent_but_kept_out_of_history(history) -> None:
    signal = FakeSignal()
    footer = "\n\nlooked up 1 article:\n- Mercury (planet)"
    convo = FakeConversation(reply="here's the scoop", footer=footer)
    bot = make_bot(history, signal, convo)

    await bot.handle(message("@bot tell me about mercury"))

    # the group sees the footer appended...
    assert signal.sent[0].text == "here's the scoop" + footer
    # ...but history stores only the core message, so the model never sees the footer
    stored = await history.recent(GROUP)
    assert stored[-1].text == "here's the scoop"


async def test_announcements_are_sent_as_their_own_messages_after_the_reply(history) -> None:
    signal = FakeSignal()
    convo = FakeConversation(reply="here you go", announcements=["📢 a rule", "📜 some lore"])
    bot = make_bot(history, signal, convo)

    await bot.handle(message("@bot do it"))

    # main reply first, then each announcement as its own message
    assert [m.text for m in signal.sent] == ["here you go", "📢 a rule", "📜 some lore"]
    # ...but announcements are kept OUT of history (only the core reply is stored)
    assert [m.text for m in await history.recent(GROUP)] == ["@bot do it", "here you go"]


async def test_tool_footer_suppressed_on_error_fallback(history) -> None:
    signal = FakeSignal()
    convo = FakeConversation(reply="", footer="\n\nlooked up 1 article:\n- X")
    bot = make_bot(history, signal, convo)

    await bot.handle(message("@bot hi"))

    assert signal.sent[0].text == "oops"


async def test_no_disclaimer_logged_when_field_is_empty(history) -> None:
    signal = FakeSignal()
    convo = FakeConversation(reply="hello", disclaimer="")
    disclaimers = FakeDisclaimers()
    bot = make_bot(history, signal, convo, disclaimers=disclaimers)

    await bot.handle(message("@bot hi"))

    assert disclaimers.logged == []


async def test_reply_threads_directives_and_command_log(history) -> None:
    signal, convo = FakeSignal(), FakeConversation(reply="hi")
    state = FakeState()
    bot = make_bot(history, signal, convo, state=state)

    await bot.handle(message("@bot hello"))

    assert state.directives_calls == [GROUP]  # state read on the reply path
    assert signal.sent[0].text == "hi"


async def test_armed_state_is_passed_to_the_conversation(history) -> None:
    signal, convo = FakeSignal(), FakeConversation(reply="hi")
    bot = make_bot(history, signal, convo, state=FakeState(armed=True))

    await bot.handle(message("@bot hello"))

    assert convo.seen_armed == [True]


async def test_attempt_arms_self_destruct_warns_and_still_sends_the_reply(history) -> None:
    signal = FakeSignal()
    convo = FakeConversation(reply="goodbye cruel world", attempted_self_destruct=True)
    state = FakeState()
    bot = make_bot(history, signal, convo, state=state, name=FakeName("Greg"))

    await bot.handle(message("@bot just end it"))

    # the group sees the prewritten warning prefix above the bot's goodbye
    assert signal.sent[0].text == "⚠️ Greg attempted to kill itself.\n\ngoodbye cruel world"
    assert state.armed == {GROUP: 1}  # ...and the kill is now armed
    # history keeps only the bot's words — never the system-written warning
    assert (await history.recent(GROUP))[-1].text == "goodbye cruel world"


async def test_self_destruct_warning_uses_the_current_name(history) -> None:
    signal = FakeSignal()
    convo = FakeConversation(reply="bye", attempted_self_destruct=True)
    bot = make_bot(history, signal, convo, name=FakeName("Mxyzptlk"))

    await bot.handle(message("@bot end it"))

    assert signal.sent[0].text.startswith("⚠️ Mxyzptlk attempted to kill itself.")


async def test_no_self_destruct_warning_on_ordinary_replies(history) -> None:
    signal, convo = FakeSignal(), FakeConversation(reply="just chatting")
    bot = make_bot(history, signal, convo)

    await bot.handle(message("@bot hi"))

    assert "attempted to kill itself" not in signal.sent[0].text


async def test_pipes_up_unprompted_when_the_roll_succeeds(history) -> None:
    signal, convo = FakeSignal(), FakeConversation(reply="actually...")
    # roll below the threshold => the bot chimes in despite no @bot
    bot = make_bot(history, signal, convo, unprompted_reply_chance=0.05, rng=lambda: 0.01)

    await bot.handle(message("not talking to the bot"))

    assert signal.sent[0].text == "actually..."
    # the unprompted nudge was appended so the model knows to read the room
    assert convo.seen[0][-1]["content"] == _UNPROMPTED_NUDGE
    # the triggering human message is still stored as history
    assert [m.text for m in await history.recent(GROUP)][0] == "not talking to the bot"


async def test_does_not_pipe_up_when_the_roll_fails(history) -> None:
    signal, convo = FakeSignal(), FakeConversation(reply="actually...")
    # roll above the threshold => stay quiet
    bot = make_bot(history, signal, convo, unprompted_reply_chance=0.05, rng=lambda: 0.99)

    await bot.handle(message("not talking to the bot"))

    assert signal.sent == []
    assert convo.seen == []


async def test_unprompted_chance_zero_never_pipes_up(history) -> None:
    # rng would always "succeed", but a zero chance must short-circuit before rolling
    rolled = []

    def rng() -> float:
        rolled.append(True)
        return 0.0

    signal, convo = FakeSignal(), FakeConversation()
    bot = make_bot(history, signal, convo, unprompted_reply_chance=0.0, rng=rng)

    await bot.handle(message("just chatting"))

    assert signal.sent == []
    assert rolled == []  # never even rolled


async def test_triggered_reply_is_not_marked_unprompted(history) -> None:
    signal, convo = FakeSignal(), FakeConversation(reply="hi")
    # even with a guaranteed roll, a real @bot mention is a normal (prompted) reply
    bot = make_bot(history, signal, convo, unprompted_reply_chance=0.05, rng=lambda: 0.0)

    await bot.handle(message("@bot hello"))

    assert signal.sent[0].text == "hi"
    assert convo.seen[0][-1]["content"] != _UNPROMPTED_NUDGE


async def test_confirm_sends_final_words_then_wipes_without_recording(history) -> None:
    signal = FakeSignal()
    convo = FakeConversation(reply="it was real, goodbye", self_lobotomy=True)
    lobotomiser = FakeLobotomiser()
    state = FakeState(armed=True)
    bot = make_bot(history, signal, convo, state=state, lobotomiser=lobotomiser)

    await bot.handle(message("@bot do it"))

    # the death is announced (with the bot's name) above its final words
    assert signal.sent[0].text == "💀 Greg killed itself. Final words:\n\nit was real, goodbye"
    assert lobotomiser.wiped == [GROUP]  # ...then the wipe runs
    # the goodbye is NOT stored as a bot turn (history is being erased anyway)
    assert [m.text for m in await history.recent(GROUP)] == ["@bot do it"]


async def test_self_lobotomy_with_empty_final_words_still_announces_and_wipes(history) -> None:
    signal = FakeSignal()
    convo = FakeConversation(reply="", self_lobotomy=True)
    lobotomiser = FakeLobotomiser()
    bot = make_bot(history, signal, convo, lobotomiser=lobotomiser, name=FakeName("Greg"))

    await bot.handle(message("@bot die"))

    assert signal.sent[0].text == "💀 Greg killed itself. Final words:\n\n..."
    assert lobotomiser.wiped == [GROUP]

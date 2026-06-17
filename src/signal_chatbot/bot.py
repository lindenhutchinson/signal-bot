"""The orchestrator: wires transport, history, and the LLM into the bot loop.

For every incoming group message it (1) enforces the allowlist, (2) records the
message as context, and (3) decides whether to engage: it replies when the trigger
alias is present (or it asked to hear this message), and otherwise rolls a low chance
to chime in unprompted — half of those turns a bare emoji reaction, half a full
message. A per-group lock serialises overlapping turns so replies for one group are
produced in order.
"""

from __future__ import annotations

import asyncio
import random
from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from datetime import tzinfo
from typing import Protocol

from signal_chatbot.commands.parser import Command, parse
from signal_chatbot.history import HistoryStore
from signal_chatbot.llm.parsing import split_off_disclaimer
from signal_chatbot.llm.prompt import BOT_SENDER, build_messages, quotable_history
from signal_chatbot.llm.reply import BotReply
from signal_chatbot.lobotomy import Lobotomiser
from signal_chatbot.logging import get_logger
from signal_chatbot.state import DirectiveSet, FinalWords, LoggedCommand, Profile
from signal_chatbot.tools import ToolContext
from signal_chatbot.transport.models import IncomingMessage, OutgoingMessage

log = get_logger(__name__)

# Prepended (NOT stored in history) to the bot's own message on the turn it triggers
# self-destruct, so the group is plainly warned even though the line is system-written
# rather than something the bot could fake or omit.
_SELF_DESTRUCT_WARNING = "⚠️ {name} attempted to kill itself.\n\n"

# Prepended to the bot's last message when it goes through with it: makes the death
# unmistakable and labels the text that follows as its final words.
_SELF_LOBOTOMY_NOTICE = "💀 {name} killed itself. Final words:\n\n"

# Appended (as a user turn) when the bot replies unprompted, so it reads the room and
# chimes in naturally rather than answering a request that was never made.
_UNPROMPTED_NUDGE = (
    "(System: nobody summoned you, but you've decided to butt in. React to what's just "
    "been said — keep it short and natural, like a real person chiming in. Don't point "
    "out that you weren't called.)"
)

# Appended when the bot is replying because it earlier asked to hear the next message
# (the listen_next flag). It was not summoned; this is the message it chose to wait for.
_LISTEN_NUDGE = (
    "(System: you asked to hear the next message — here it is. Reply to it directly. If "
    "you want to keep listening after this, call listen_for_reply again.)"
)

# Appended on a react-only chime-in: the bot isn't speaking this turn, it's just reacting
# (like tapping an emoji in the app). It must call send_reaction in its OWN step first —
# NOT in the same turn as final_answer, or the reaction is dropped — then finish with an
# empty final_answer so no words are sent.
_REACT_NUDGE = (
    "(System: nobody summoned you and you're NOT speaking this turn — you just feel like "
    "reacting, the way anyone taps an emoji on a message. Pick the message that's worth a "
    "reaction (use its [#N] number) and call send_reaction with a single fitting emoji. Do "
    "that as your first and only tool call this step; once you see it succeed, call "
    "final_answer with an EMPTY message. Send no words. If nothing's worth reacting to, "
    "just call final_answer with an empty message and react to nothing.)"
)


class Responder(Protocol):
    """The LLM-facing dependency the bot needs (satisfied by Conversation)."""

    async def respond(
        self, messages: list[dict], ctx: ToolContext, *, armed: bool = False
    ) -> BotReply: ...


class Sender(Protocol):
    """The transport-facing dependency the bot needs (satisfied by SignalClient)."""

    async def send(self, message: OutgoingMessage) -> None: ...


class Stream(Sender, Protocol):
    def stream(self): ...


class Commands(Protocol):
    """Applies a parsed command and returns the reply text (satisfied by CommandRouter)."""

    async def handle(self, command: Command, message: IncomingMessage) -> str: ...


class Directives(Protocol):
    """Read-only view of a group's directives (satisfied by DirectiveStore)."""

    async def directives(self, group_id: str) -> DirectiveSet: ...


class CommandActivity(Protocol):
    """Read-only view of the command-event log (satisfied by CommandLog)."""

    async def recent_commands(self, group_id: str) -> list[LoggedCommand]: ...


class Flags(Protocol):
    """The per-group flags the bot reads and sets (satisfied by FlagRegistry)."""

    async def is_armed(self, group_id: str) -> bool: ...
    async def arm(self, group_id: str) -> None: ...
    async def consume_listen(self, group_id: str) -> bool: ...


class FinalWordsArchive(Protocol):
    """The never-wiped archive of past incarnations' parting words (FinalWordsStore)."""

    async def all(self, group_id: str) -> list[FinalWords]: ...
    async def add(self, group_id: str, *, name: str, text: str, created_at: int) -> None: ...


class DisclaimerLog(Protocol):
    """Sink for the asides the bot attaches to replies (satisfied by DisclaimerStore)."""

    async def add_disclaimer(
        self, group_id: str, *, message: str, disclaimer: str, created_at: int
    ) -> None: ...


class Profiles(Protocol):
    """Read-only view of the per-subject notes the bot keeps (satisfied by ProfileStore)."""

    async def all(self, group_id: str) -> list[Profile]: ...


class NameSource(Protocol):
    """Read-only view of the bot's current display name (satisfied by BotName)."""

    @property
    def current(self) -> str: ...


class Bot:
    """Coordinates incoming messages, history, and LLM replies."""

    def __init__(
        self,
        *,
        signal: Sender,
        history: HistoryStore,
        conversation: Responder,
        commands: Commands,
        directives: Directives,
        command_log: CommandActivity,
        flags: Flags,
        final_words: FinalWordsArchive,
        disclaimers: DisclaimerLog,
        profiles: Profiles,
        lobotomiser: Lobotomiser,
        name: NameSource,
        system_prompt: str,
        allowed_group_ids: list[str],
        allowed_senders: list[str],
        trigger_alias: str,
        error_reply: str,
        timezone: tzinfo,
        unprompted_reply_chance: float = 0.0,
        unprompted_react_share: float = 0.5,
        rng: Callable[[], float] = random.random,
    ):
        self._signal = signal
        self._history = history
        self._conversation = conversation
        self._commands = commands
        self._directives = directives
        self._command_log = command_log
        self._flags = flags
        self._final_words = final_words
        self._disclaimers = disclaimers
        self._profiles = profiles
        self._lobotomiser = lobotomiser
        self._name = name
        self._system_prompt = system_prompt
        self._allowed_groups = set(allowed_group_ids)
        self._allowed_senders = set(allowed_senders)
        self._trigger = trigger_alias.lower()
        self._error_reply = error_reply
        self._timezone = timezone
        self._unprompted_chance = unprompted_reply_chance
        self._react_share = unprompted_react_share
        self._rng = rng
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def run(self) -> None:
        """Consume the Signal stream forever."""
        async for message in self._signal.stream():  # type: ignore[attr-defined]
            await self.handle(message)

    async def handle(self, message: IncomingMessage) -> None:
        """Process a single incoming message."""
        if not self._is_allowed(message):
            return

        command = parse(message.text)

        # Inbound trace (metadata only — content already lives in history). Lets us see
        # whether a message actually reached the bot, e.g. when diagnosing the
        # intermittent signal-cli sealed-sender receive drops.
        log.info(
            "bot.received",
            sender=message.sender_name,
            chars=len(message.text),
            command=command.name.value if command else None,
        )

        if command is not None:
            try:
                reply = await self._commands.handle(command, message)
            except Exception as exc:  # noqa: BLE001 - a bad command must not kill the loop
                log.error("bot.command_failed", group=message.group_id, error=str(exc))
                reply = self._error_reply
            log.info("bot.command_done", command=command.name.value)
            await self._signal.send(OutgoingMessage(group_id=message.group_id, text=reply))
            return

        await self._history.append(
            message.group_id,
            sender=message.sender_name,
            text=message.text,
            timestamp=message.timestamp,
            sender_number=message.sender_number,
        )

        triggered = self._trigger in message.text.lower()
        # The bot may have asked (last turn) to hear whatever was said next: consume that
        # one-shot flag and treat this message as addressed to it.
        listening = not triggered and await self._flags.consume_listen(message.group_id)
        if triggered or listening:
            async with self._locks[message.group_id]:
                await self._reply(message.group_id, message.timestamp, via_listen=listening)
            return

        # Unprompted chime-in: a low-chance roll to engage at all, then a coin flip on
        # whether this turn is a bare reaction or a full message.
        if self._should_pipe_up():
            async with self._locks[message.group_id]:
                if self._should_react():
                    await self._reply(message.group_id, message.timestamp, react=True)
                else:
                    await self._reply(message.group_id, message.timestamp, unprompted=True)

    def _should_pipe_up(self) -> bool:
        """Roll the dice on chiming in unprompted (low chance, off when 0)."""
        return self._unprompted_chance > 0 and self._rng() < self._unprompted_chance

    def _should_react(self) -> bool:
        """Given the bot is chiming in, decide if this turn is a bare reaction (vs a message)."""
        return self._rng() < self._react_share

    def _is_allowed(self, message: IncomingMessage) -> bool:
        if message.group_id not in self._allowed_groups:
            return False
        return not self._allowed_senders or message.sender_number in self._allowed_senders

    async def _reply(
        self,
        group_id: str,
        timestamp: int,
        *,
        unprompted: bool = False,
        via_listen: bool = False,
        react: bool = False,
    ) -> None:
        try:
            armed = await self._flags.is_armed(group_id)
            history = await self._history.recent(group_id)
            directives = await self._directives.directives(group_id)
            command_log = await self._command_log.recent_commands(group_id)
            profiles = await self._profiles.all(group_id)
            final_words = await self._final_words.all(group_id)
            messages = build_messages(
                self._system_prompt,
                history,
                timezone=self._timezone,
                directives=directives,
                command_log=command_log,
                profiles=profiles,
                final_words=final_words,
            )
            if react:
                messages.append({"role": "user", "content": _REACT_NUDGE})
            elif unprompted:
                messages.append({"role": "user", "content": _UNPROMPTED_NUDGE})
            elif via_listen:
                messages.append({"role": "user", "content": _LISTEN_NUDGE})
            ctx = ToolContext(
                group_id=group_id, timestamp=timestamp, quotable=quotable_history(history)
            )
            reply = await self._conversation.respond(messages, ctx, armed=armed)
        except Exception as exc:  # noqa: BLE001 - never let one message kill the loop
            log.error("bot.reply_failed", group=group_id, error=str(exc))
            reply = BotReply(message="")

        if reply.self_lobotomy:
            await self._self_reset(group_id, reply.message, timestamp)
            return

        # The model sometimes leaks an "Ethical disclaimer:" section into the message text
        # instead of the field. Split it back out so it never reaches the chat; if the
        # field itself was empty, the leaked text becomes the logged disclaimer.
        message, leaked = split_off_disclaimer(reply.message.strip())
        disclaimer = reply.ethical_disclaimer or leaked
        has_message = bool(message)
        # An empty message falls back to the error reply ONLY when a human actually summoned
        # us. On the unprompted/listen/react paths nobody is waiting, so we stay silent
        # rather than blurt the error string — a react turn has already fired its emoji as a
        # side-effect during respond, and the words it deliberately withheld are the point.
        prompted = not (unprompted or via_listen or react)
        if disclaimer:
            await self._disclaimers.add_disclaimer(
                group_id,
                message=message or self._error_reply,
                disclaimer=disclaimer,
                created_at=timestamp,
            )
        if has_message:
            # The self-destruct warning and the tool-usage footer are shown to the group but
            # kept OUT of history: storing them would let the model see them in its own past
            # turns and learn to fake them.
            warning = self._self_destruct_warning() if reply.attempted_self_destruct else ""
            sent = warning + message + reply.tool_footer
            # Quoting applies only to the main reply.
            quote = self._resolve_quote(history, reply.reply_to_index)
            outgoing = OutgoingMessage(group_id=group_id, text=sent)
            if quote is not None:
                outgoing = replace(
                    outgoing,
                    quote_timestamp=quote.timestamp,
                    quote_author=quote.sender_number,
                    quote_message=quote.text,
                )
            await self._signal.send(outgoing)
            await self._history.append(
                group_id, sender=BOT_SENDER, text=message, timestamp=timestamp, sender_number=""
            )
        elif prompted:
            # Summoned, but the model produced nothing — send the fallback so the human who
            # @'d us isn't left hanging. The warning/footer are suppressed on this path.
            await self._signal.send(OutgoingMessage(group_id=group_id, text=self._error_reply))
            await self._history.append(
                group_id,
                sender=BOT_SENDER,
                text=self._error_reply,
                timestamp=timestamp,
                sender_number="",
            )

        # Tool-produced announcements are public, sent as their own messages AFTER the
        # main reply, and (like the footer) kept OUT of history so the model can't fake them.
        for announcement in reply.announcements:
            await self._signal.send(OutgoingMessage(group_id=group_id, text=announcement))

        # The bot pulled the trigger this turn: arm the kill so confirm_kill_self unlocks
        # next time it's summoned, giving the group a window to talk it down first.
        if reply.attempted_self_destruct:
            await self._flags.arm(group_id)
            log.info("bot.self_destruct_armed", group=group_id)

    @staticmethod
    def _resolve_quote(history: list, index: int | None):
        """Map the model's 1-based ``[#N]`` to the message it quotes, or ``None``.

        ``index`` is resolved against ``quotable_history`` (non-bot turns only), the same
        list the prompt numbers. Out-of-range or missing → no quote (silently).
        """
        if index is None:
            return None
        quotable = quotable_history(history)
        if 1 <= index <= len(quotable):
            return quotable[index - 1]
        return None

    def _self_destruct_warning(self) -> str:
        return _SELF_DESTRUCT_WARNING.format(name=self._name.current)

    async def _self_reset(self, group_id: str, final_words: str, timestamp: int) -> None:
        """The bot confirmed its own end: send its final words, archive them, then wipe.

        This is a *reset*, not a true erasure: the final words are recorded to the
        never-wiped archive (so they reach the next incarnation) before the wipe runs.
        The goodbye is sent but NOT stored in history — that's about to be erased anyway —
        and the wipe runs last, so a failed send never leaves a half-dead bot. The bot is
        reborn under the default name.
        """
        log.info("bot.self_reset", group=group_id)
        # Read the name before the wipe resets it to default.
        name = self._name.current
        words = final_words.strip() or "..."
        notice = _SELF_LOBOTOMY_NOTICE.format(name=name)
        await self._signal.send(OutgoingMessage(group_id=group_id, text=notice + words))
        await self._final_words.add(group_id, name=name, text=words, created_at=timestamp)
        await self._lobotomiser.wipe(group_id)

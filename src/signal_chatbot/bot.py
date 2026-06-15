"""The orchestrator: wires transport, history, and the LLM into the bot loop.

For every incoming group message it (1) enforces the allowlist, (2) records the
message as context, and (3) if the trigger alias is present, generates and sends
a reply. A per-group lock serialises overlapping triggers so replies for one
group are produced in order.
"""

from __future__ import annotations

import asyncio
import random
from collections import defaultdict
from collections.abc import Callable
from datetime import tzinfo
from typing import Protocol

from signal_chatbot.commands.parser import Command, parse
from signal_chatbot.history import HistoryStore
from signal_chatbot.llm.prompt import BOT_SENDER, build_messages
from signal_chatbot.llm.reply import BotReply
from signal_chatbot.lobotomy import Lobotomiser
from signal_chatbot.logging import get_logger
from signal_chatbot.state import DirectiveSet, LoggedCommand, Profile
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


class Arming(Protocol):
    """The self-destruct arming flag the reply path reads and sets (satisfied by ArmingStore)."""

    async def is_suicide_armed(self, group_id: str) -> bool: ...
    async def arm_suicide(self, group_id: str, *, at: int) -> None: ...


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
        arming: Arming,
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
        rng: Callable[[], float] = random.random,
    ):
        self._signal = signal
        self._history = history
        self._conversation = conversation
        self._commands = commands
        self._directives = directives
        self._command_log = command_log
        self._arming = arming
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
        )

        triggered = self._trigger in message.text.lower()
        if not triggered and not self._should_pipe_up():
            return

        async with self._locks[message.group_id]:
            await self._reply(message.group_id, message.timestamp, unprompted=not triggered)

    def _should_pipe_up(self) -> bool:
        """Roll the dice on chiming in unprompted (low chance, off when 0)."""
        return self._unprompted_chance > 0 and self._rng() < self._unprompted_chance

    def _is_allowed(self, message: IncomingMessage) -> bool:
        if message.group_id not in self._allowed_groups:
            return False
        return not self._allowed_senders or message.sender_number in self._allowed_senders

    async def _reply(self, group_id: str, timestamp: int, *, unprompted: bool = False) -> None:
        try:
            armed = await self._arming.is_suicide_armed(group_id)
            history = await self._history.recent(group_id)
            directives = await self._directives.directives(group_id)
            command_log = await self._command_log.recent_commands(group_id)
            profiles = await self._profiles.all(group_id)
            messages = build_messages(
                self._system_prompt,
                history,
                timezone=self._timezone,
                directives=directives,
                command_log=command_log,
                profiles=profiles,
            )
            if unprompted:
                messages.append({"role": "user", "content": _UNPROMPTED_NUDGE})
            ctx = ToolContext(group_id=group_id, timestamp=timestamp)
            reply = await self._conversation.respond(messages, ctx, armed=armed)
        except Exception as exc:  # noqa: BLE001 - never let one message kill the loop
            log.error("bot.reply_failed", group=group_id, error=str(exc))
            reply = BotReply(message="")

        if reply.self_lobotomy:
            await self._self_lobotomy(group_id, reply.message, timestamp)
            return

        has_message = bool(reply.message.strip())
        text = reply.message.strip() or self._error_reply
        if reply.ethical_disclaimer:
            await self._disclaimers.add_disclaimer(
                group_id, message=text, disclaimer=reply.ethical_disclaimer, created_at=timestamp
            )
        # The self-destruct warning and the tool-usage footer are shown to the group but
        # kept OUT of history: storing them would let the model see them in its own past
        # turns and learn to fake them. Both are suppressed on the error-reply fallback.
        warning = self._self_destruct_warning() if reply.attempted_self_destruct else ""
        sent = warning + text + reply.tool_footer if has_message else text
        await self._signal.send(OutgoingMessage(group_id=group_id, text=sent))
        await self._history.append(group_id, sender=BOT_SENDER, text=text, timestamp=timestamp)

        # Tool-produced announcements are public, sent as their own messages AFTER the
        # main reply, and (like the footer) kept OUT of history so the model can't fake them.
        for announcement in reply.announcements:
            await self._signal.send(OutgoingMessage(group_id=group_id, text=announcement))

        # The bot pulled the trigger this turn: arm the kill so confirm_kill_self unlocks
        # next time it's summoned, giving the group a window to talk it down first.
        if reply.attempted_self_destruct:
            await self._arming.arm_suicide(group_id, at=timestamp)
            log.info("bot.self_destruct_armed", group=group_id)

    def _self_destruct_warning(self) -> str:
        return _SELF_DESTRUCT_WARNING.format(name=self._name.current)

    async def _self_lobotomy(self, group_id: str, final_words: str, timestamp: int) -> None:
        """The bot confirmed its own end: send its final words, then wipe it clean.

        The goodbye is sent but NOT stored — history is about to be erased anyway — and the
        wipe (directives, history, name, arming) runs after, so a failed send never leaves a
        half-dead bot.
        """
        log.info("bot.self_lobotomy", group=group_id)
        # Read the name before the wipe resets it to default.
        notice = _SELF_LOBOTOMY_NOTICE.format(name=self._name.current)
        sent = notice + (final_words.strip() or "...")
        await self._signal.send(OutgoingMessage(group_id=group_id, text=sent))
        await self._lobotomiser.wipe(group_id)

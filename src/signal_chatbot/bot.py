"""The orchestrator: wires transport, history, and the LLM into the bot loop.

For every incoming group message it (1) enforces the allowlist, (2) records the
message as context, and (3) if the trigger alias is present, generates and sends
a reply. A per-group lock serialises overlapping triggers so replies for one
group are produced in order.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Protocol

from signal_chatbot.commands.parser import Command, parse
from signal_chatbot.history import HistoryStore
from signal_chatbot.llm.conversation import BotReply
from signal_chatbot.llm.prompt import BOT_SENDER, build_messages
from signal_chatbot.logging import get_logger
from signal_chatbot.state import DirectiveSet, LoggedCommand
from signal_chatbot.transport.models import IncomingMessage, OutgoingMessage

log = get_logger(__name__)


class Responder(Protocol):
    """The LLM-facing dependency the bot needs (satisfied by Conversation)."""

    async def respond(self, messages: list[dict]) -> BotReply: ...


class Sender(Protocol):
    """The transport-facing dependency the bot needs (satisfied by SignalClient)."""

    async def send(self, message: OutgoingMessage) -> None: ...


class Stream(Sender, Protocol):
    def stream(self): ...


class Commands(Protocol):
    """Applies a parsed command and returns the reply text (satisfied by CommandRouter)."""

    async def handle(self, command: Command, message: IncomingMessage) -> str: ...


class StateReader(Protocol):
    """The state slice the reply path reads (satisfied by StateStore)."""

    async def directives(self, group_id: str) -> DirectiveSet: ...
    async def recent_commands(self, group_id: str) -> list[LoggedCommand]: ...


class DisclaimerLog(Protocol):
    """Sink for the asides the bot attaches to replies (satisfied by StateStore)."""

    async def add_disclaimer(
        self, group_id: str, *, message: str, disclaimer: str, created_at: int
    ) -> None: ...


class Bot:
    """Coordinates incoming messages, history, and LLM replies."""

    def __init__(
        self,
        *,
        signal: Sender,
        history: HistoryStore,
        conversation: Responder,
        commands: Commands,
        state: StateReader,
        disclaimers: DisclaimerLog,
        system_prompt: str,
        allowed_group_ids: list[str],
        allowed_senders: list[str],
        trigger_alias: str,
        error_reply: str,
    ):
        self._signal = signal
        self._history = history
        self._conversation = conversation
        self._commands = commands
        self._state = state
        self._disclaimers = disclaimers
        self._system_prompt = system_prompt
        self._allowed_groups = set(allowed_group_ids)
        self._allowed_senders = set(allowed_senders)
        self._trigger = trigger_alias.lower()
        self._error_reply = error_reply
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
        if command is not None:
            try:
                reply = await self._commands.handle(command, message)
            except Exception as exc:  # noqa: BLE001 - a bad command must not kill the loop
                log.error("bot.command_failed", group=message.group_id, error=str(exc))
                reply = self._error_reply
            await self._signal.send(OutgoingMessage(group_id=message.group_id, text=reply))
            return

        await self._history.append(
            message.group_id,
            sender=message.sender_name,
            text=message.text,
            timestamp=message.timestamp,
        )

        if self._trigger not in message.text.lower():
            return

        async with self._locks[message.group_id]:
            await self._reply(message.group_id, message.timestamp)

    def _is_allowed(self, message: IncomingMessage) -> bool:
        if message.group_id not in self._allowed_groups:
            return False
        return not self._allowed_senders or message.sender_number in self._allowed_senders

    async def _reply(self, group_id: str, timestamp: int) -> None:
        try:
            history = await self._history.recent(group_id)
            directives = await self._state.directives(group_id)
            command_log = await self._state.recent_commands(group_id)
            messages = build_messages(
                self._system_prompt, history, directives=directives, command_log=command_log
            )
            reply = await self._conversation.respond(messages)
        except Exception as exc:  # noqa: BLE001 - never let one message kill the loop
            log.error("bot.reply_failed", group=group_id, error=str(exc))
            reply = BotReply(message="")

        text = reply.message.strip() or self._error_reply
        if reply.ethical_disclaimer:
            await self._disclaimers.add_disclaimer(
                group_id, message=text, disclaimer=reply.ethical_disclaimer, created_at=timestamp
            )
        await self._signal.send(OutgoingMessage(group_id=group_id, text=text))
        await self._history.append(group_id, sender=BOT_SENDER, text=text, timestamp=timestamp)

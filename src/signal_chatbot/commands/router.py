"""Dispatch a parsed :class:`Command` to its effect and return the reply text.

State-changing commands are recorded in the command log (arguments excluded);
list/help queries are not. ``@reset`` is the only command that calls the LLM, via
the injected :class:`FarewellWriter`.
"""

from __future__ import annotations

from signal_chatbot.commands import replies
from signal_chatbot.commands.farewell import FarewellWriter
from signal_chatbot.commands.parser import Command, CommandName
from signal_chatbot.history import HistoryStore
from signal_chatbot.logging import get_logger
from signal_chatbot.state import StateStore
from signal_chatbot.transport import ProfileNameSetter
from signal_chatbot.transport.models import IncomingMessage

log = get_logger(__name__)


class CommandRouter:
    """Holds the command dependencies and applies each command's effect."""

    def __init__(
        self,
        *,
        state: StateStore,
        history: HistoryStore,
        farewell: FarewellWriter,
        name_setter: ProfileNameSetter,
    ):
        self._state = state
        self._history = history
        self._farewell = farewell
        self._name_setter = name_setter

    async def handle(self, command: Command, message: IncomingMessage) -> str:
        """Apply ``command`` for ``message`` and return the text to reply with."""
        match command.name:
            case CommandName.PATCH:
                return await self._add(
                    command, message, kind="patch", ok=replies.PATCHED, usage=replies.USAGE_PATCH
                )
            case CommandName.RULE:
                return await self._add(
                    command, message, kind="rule", ok=replies.RULE_LOGGED, usage=replies.USAGE_RULE
                )
            case CommandName.LORE:
                return await self._add(
                    command, message, kind="lore", ok=replies.LORE_ADDED, usage=replies.USAGE_LORE
                )
            case CommandName.PATCHLIST:
                return replies.format_list(
                    "Patches", (await self._state.directives(message.group_id)).patches
                )
            case CommandName.RULELIST:
                return replies.format_list(
                    "Rules", (await self._state.directives(message.group_id)).rules
                )
            case CommandName.LORELIST:
                return replies.format_list(
                    "Lore", (await self._state.directives(message.group_id)).lore
                )
            case CommandName.NAME:
                return await self._name(message, command.arg.strip())
            case CommandName.CLEAR:
                return await self._clear(message)
            case CommandName.RESET:
                return await self._reset(message)
            case CommandName.HELP:
                return replies.HELP_TEXT

    async def _add(
        self, command: Command, message: IncomingMessage, *, kind: str, ok: str, usage: str
    ) -> str:
        text = command.arg.strip()
        if not text:
            return usage
        await self._state.add_directive(
            message.group_id,
            kind=kind,
            author_name=message.sender_name,
            author_number=message.sender_number,
            text=text,
            created_at=message.timestamp,
        )
        await self._log(message, command.name)
        return ok

    async def _name(self, message: IncomingMessage, new_name: str) -> str:
        if not new_name:
            return replies.USAGE_NAME
        await self._name_setter.set_profile_name(new_name)
        await self._log(message, CommandName.NAME)
        return replies.format_name_set(new_name)

    async def _clear(self, message: IncomingMessage) -> str:
        await self._history.clear(message.group_id)
        await self._log(message, CommandName.CLEAR)
        return replies.HISTORY_CLEARED

    async def _reset(self, message: IncomingMessage) -> str:
        directives = await self._state.directives(message.group_id)
        history = await self._history.recent(message.group_id)
        farewell = await self._farewell.write(directives=directives, history=history)
        await self._state.clear_directives(message.group_id)
        await self._history.set_floor(message.group_id)
        await self._log(message, CommandName.RESET)
        if farewell is None:
            return replies.RESET_CLEAN
        await self._rename_best_effort(farewell.name)
        await self._state.add_directive(
            message.group_id,
            kind="lore",
            author_name=farewell.name,
            author_number="bot",
            text=farewell.final_message,
            created_at=message.timestamp,
        )
        return replies.format_farewell(farewell.name, farewell.final_message)

    async def _rename_best_effort(self, name: str) -> None:
        """Rename the bot to its new self; never let a failed rename abort the reset."""
        try:
            await self._name_setter.set_profile_name(name)
        except Exception as exc:  # noqa: BLE001 - rename is best-effort
            log.warning("command.reset_rename_failed", name=name, error=str(exc))

    async def _log(self, message: IncomingMessage, name: CommandName) -> None:
        await self._state.log_command(
            message.group_id,
            author_name=message.sender_name,
            command=f"@{name.value}",
            created_at=message.timestamp,
        )

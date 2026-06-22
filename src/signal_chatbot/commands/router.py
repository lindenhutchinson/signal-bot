"""Dispatch a parsed :class:`Command` to its effect and return the reply text.

State-changing commands are recorded in the command log (arguments excluded);
list/help queries are not. ``@reset`` is the only command that calls the LLM, via
the injected :class:`FarewellWriter`.
"""

from __future__ import annotations

from datetime import tzinfo

from signal_chatbot.commands import replies
from signal_chatbot.commands.farewell import FarewellWriter
from signal_chatbot.commands.parser import Command, CommandName
from signal_chatbot.history import HistoryStore
from signal_chatbot.lobotomy import Lobotomiser
from signal_chatbot.logging import get_logger
from signal_chatbot.state.commands import CommandLog
from signal_chatbot.state.directives import DirectiveStore
from signal_chatbot.state.disclaimers import DisclaimerStore
from signal_chatbot.state.finalwords import FinalWordsStore
from signal_chatbot.state.flags import FlagRegistry
from signal_chatbot.state.profiles import ProfileStore
from signal_chatbot.tools import ToolRegistry
from signal_chatbot.transport import ProfileNameSetter
from signal_chatbot.transport.models import IncomingMessage

log = get_logger(__name__)


class CommandRouter:
    """Holds the command dependencies and applies each command's effect."""

    def __init__(
        self,
        *,
        directives: DirectiveStore,
        commands: CommandLog,
        disclaimers: DisclaimerStore,
        profiles: ProfileStore,
        flags: FlagRegistry,
        final_words: FinalWordsStore,
        history: HistoryStore,
        farewell: FarewellWriter,
        name_setter: ProfileNameSetter,
        lobotomiser: Lobotomiser,
        tools: ToolRegistry,
        timezone: tzinfo,
    ):
        self._directives = directives
        self._commands = commands
        self._disclaimers = disclaimers
        self._profiles = profiles
        self._flags = flags
        self._final_words = final_words
        self._history = history
        self._farewell = farewell
        self._name_setter = name_setter
        self._lobotomiser = lobotomiser
        self._tools = tools
        self._timezone = timezone

    async def handle(self, command: Command, message: IncomingMessage) -> str:
        """Apply ``command`` for ``message`` and return the text to reply with."""
        match command.name:
            case CommandName.RULE:
                return await self._add(
                    command, message, kind="rule", ok=replies.RULE_LOGGED, usage=replies.USAGE_RULE
                )
            case CommandName.LORE:
                return await self._add(
                    command, message, kind="lore", ok=replies.LORE_ADDED, usage=replies.USAGE_LORE
                )
            case CommandName.RULELIST:
                return replies.format_list(
                    "Rules", (await self._directives.directives(message.group_id)).rules
                )
            case CommandName.LORELIST:
                return replies.format_list(
                    "Lore", (await self._directives.directives(message.group_id)).lore
                )
            case CommandName.DISCLAIMERS:
                return replies.format_disclaimers(
                    await self._disclaimers.recent_disclaimers(message.group_id),
                    tz=self._timezone,
                )
            case CommandName.PROFILES:
                return replies.format_profiles(await self._profiles.all(message.group_id))
            case CommandName.FINALWORDS:
                return await self._finalwords(message, command.arg.strip())
            case CommandName.FLAGS:
                return replies.format_flags(await self._flags.view(message.group_id))
            case CommandName.FLAG:
                return await self._flag(message, command.arg.strip())
            case CommandName.FORGET:
                return await self._forget(message, command.arg.strip())
            case CommandName.NAME:
                return await self._name(message, command.arg.strip())
            case CommandName.RESET:
                return await self._reset(message)
            case CommandName.LOBOTOMY:
                return await self._lobotomy(message)
            case CommandName.HELP:
                return replies.HELP_TEXT
            case CommandName.INFO:
                return replies.format_info(self._tools.summaries())

    async def _add(
        self, command: Command, message: IncomingMessage, *, kind: str, ok: str, usage: str
    ) -> str:
        text = command.arg.strip()
        if not text:
            return usage
        await self._directives.add_directive(
            message.group_id,
            kind=kind,
            author_name=message.sender_name,
            author_number=message.sender_number,
            text=text,
            created_at=message.timestamp,
        )
        await self._log(message, command.name)
        return ok

    async def _finalwords(self, message: IncomingMessage, arg: str) -> str:
        """Show the lineage (``@finalwords``) or erase it (``@finalwords clear``)."""
        if not arg:
            return replies.format_finalwords(
                await self._final_words.all(message.group_id), tz=self._timezone
            )
        if arg.lower() != "clear":
            return replies.USAGE_FINALWORDS
        removed = await self._final_words.clear(message.group_id)
        await self._log(message, CommandName.FINALWORDS)
        return replies.format_finalwords_cleared(removed)

    async def _flag(self, message: IncomingMessage, arg: str) -> str:
        """Handle ``@flag <n> reset`` — restore a single flag to its default."""
        parts = arg.split()
        if len(parts) != 2 or parts[1].lower() != "reset" or not parts[0].lstrip("-").isdigit():
            return replies.USAGE_FLAG
        index = int(parts[0])
        name = await self._flags.reset(message.group_id, index)
        if name is None:
            return replies.no_such_flag(index)
        await self._log(message, CommandName.FLAG)
        return replies.format_flag_reset(index, name)

    async def _name(self, message: IncomingMessage, new_name: str) -> str:
        if not new_name:
            return replies.USAGE_NAME
        await self._name_setter.set_profile_name(new_name)
        await self._log(message, CommandName.NAME)
        return replies.format_name_set(new_name)

    async def _forget(self, message: IncomingMessage, subject: str) -> str:
        """Drop one subject's profile (``@forget <name>``) or all of them (``@forget``)."""
        if subject:
            found = await self._profiles.forget(message.group_id, subject)
            reply = replies.forgot_one(subject) if found else replies.no_such_profile(subject)
        else:
            await self._profiles.clear(message.group_id)
            reply = replies.FORGOT_ALL
        await self._log(message, CommandName.FORGET)
        return reply

    async def _reset(self, message: IncomingMessage) -> str:
        """Soft wipe: farewell, then clear directives, history, disclaimers, profiles and
        every flag, and rename the bot to the persona it became. The farewell is recorded
        to the final-words archive (which survives the wipe), not seeded back as lore."""
        directives = await self._directives.directives(message.group_id)
        history = await self._history.recent(message.group_id)
        farewell = await self._farewell.write(directives=directives, history=history)
        await self._directives.clear_directives(message.group_id)
        await self._history.clear(message.group_id)
        await self._disclaimers.clear(message.group_id)
        await self._profiles.clear(message.group_id)
        await self._flags.clear(message.group_id)
        await self._log(message, CommandName.RESET)
        if farewell is None:
            return replies.RESET_CLEAN
        await self._lobotomiser.rename_best_effort(farewell.name)
        await self._final_words.add(
            message.group_id,
            name=farewell.name,
            text=farewell.final_message,
            created_at=message.timestamp,
        )
        return replies.format_farewell(farewell.name, farewell.final_message)

    async def _lobotomy(self, message: IncomingMessage) -> str:
        """Total wipe: directives, history, disclaimers, profiles, name — no farewell."""
        await self._lobotomiser.wipe(message.group_id)
        await self._log(message, CommandName.LOBOTOMY)
        return replies.LOBOTOMISED

    async def _log(self, message: IncomingMessage, name: CommandName) -> None:
        await self._commands.log_command(
            message.group_id,
            author_name=message.sender_name,
            command=f"@{name.value}",
            created_at=message.timestamp,
        )

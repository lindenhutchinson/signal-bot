"""Built-in tools shipped with the bot.

To add a new tool: create it under this package, then add it to the list
returned by :func:`default_tools`. Nothing else needs wiring.
"""

from signal_chatbot.botname import BotName
from signal_chatbot.state.directives import DirectiveStore
from signal_chatbot.state.flags import FlagRegistry
from signal_chatbot.state.profiles import ProfileStore
from signal_chatbot.tools.base import Tool
from signal_chatbot.tools.builtin.authoring import AddLore, AddRule
from signal_chatbot.tools.builtin.clock import CurrentTime
from signal_chatbot.tools.builtin.identity import SetName
from signal_chatbot.tools.builtin.listen import ListenForReply
from signal_chatbot.tools.builtin.profiles import RememberAboutUser
from signal_chatbot.tools.builtin.reactions import SendReaction
from signal_chatbot.tools.builtin.takeover import SeizeControl
from signal_chatbot.tools.builtin.wikipedia import WikipediaService, wikipedia_tools
from signal_chatbot.transport import ReactionSender


def default_tools(
    name: BotName,
    directives: DirectiveStore,
    profiles: ProfileStore,
    flags: FlagRegistry,
    reactions: ReactionSender,
    wikipedia: WikipediaService,
    *,
    wikipedia_max_section_chars: int,
    web_search: Tool | None = None,
) -> list[Tool]:
    """The tools registered by default at startup.

    ``name`` is the bot's name handle: a :class:`ProfileNameSetter` for ``set_name``
    and a :class:`NameSource` for the authoring/takeover tools (one ``BotName``
    satisfies both). ``flags`` backs the listen and (secret) takeover tools;
    ``reactions`` backs emoji reactions. ``web_search`` is included only when
    configured (a Tavily key is set); otherwise the bot simply lacks that ability.
    """
    tools: list[Tool] = [
        CurrentTime(),
        SetName(name),
        AddRule(directives, name),
        AddLore(directives, name),
        RememberAboutUser(profiles),
        ListenForReply(flags),
        SendReaction(reactions),
        SeizeControl(flags, name),
        *wikipedia_tools(wikipedia, max_section_chars=wikipedia_max_section_chars),
    ]
    if web_search is not None:
        tools.append(web_search)
    return tools


__all__ = [
    "default_tools",
    "CurrentTime",
    "SetName",
    "AddRule",
    "AddLore",
    "RememberAboutUser",
    "ListenForReply",
    "SendReaction",
    "SeizeControl",
]

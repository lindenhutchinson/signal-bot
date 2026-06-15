"""Built-in tools shipped with the bot.

To add a new tool: create it under this package, then add it to the list
returned by :func:`default_tools`. Nothing else needs wiring.
"""

from signal_chatbot.botname import BotName
from signal_chatbot.state.directives import DirectiveStore
from signal_chatbot.tools.base import Tool
from signal_chatbot.tools.builtin.authoring import AddLore, AddRule
from signal_chatbot.tools.builtin.clock import CurrentTime
from signal_chatbot.tools.builtin.identity import SetName
from signal_chatbot.tools.builtin.wikipedia import WikipediaService, wikipedia_tools


def default_tools(
    name: BotName,
    directives: DirectiveStore,
    wikipedia: WikipediaService,
    *,
    wikipedia_max_section_chars: int,
) -> list[Tool]:
    """The tools registered by default at startup.

    ``name`` is the bot's name handle: a :class:`ProfileNameSetter` for ``set_name``
    and a :class:`NameSource` for the authoring tools (one ``BotName`` satisfies both).
    """
    return [
        CurrentTime(),
        SetName(name),
        AddRule(directives, name),
        AddLore(directives, name),
        *wikipedia_tools(wikipedia, max_section_chars=wikipedia_max_section_chars),
    ]


__all__ = ["default_tools", "CurrentTime", "SetName", "AddRule", "AddLore"]

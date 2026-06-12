"""Built-in tools shipped with the bot.

To add a new tool: create it under this package, then add it to the list
returned by :func:`default_tools`. Nothing else needs wiring.
"""

from signal_chatbot.tools.base import Tool
from signal_chatbot.tools.builtin.clock import CurrentTime
from signal_chatbot.tools.builtin.identity import SetName
from signal_chatbot.tools.builtin.wikipedia import WikipediaService, wikipedia_tools
from signal_chatbot.transport import ProfileNameSetter


def default_tools(
    name_setter: ProfileNameSetter,
    wikipedia: WikipediaService,
    *,
    wikipedia_max_section_chars: int,
) -> list[Tool]:
    """The tools registered by default at startup."""
    return [
        CurrentTime(),
        SetName(name_setter),
        *wikipedia_tools(wikipedia, max_section_chars=wikipedia_max_section_chars),
    ]


__all__ = ["default_tools", "CurrentTime", "SetName"]

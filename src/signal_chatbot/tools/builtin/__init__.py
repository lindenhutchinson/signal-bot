"""Built-in tools shipped with the bot.

To add a new tool: create it under this package, then add it to the list
returned by :func:`default_tools`. Nothing else needs wiring.
"""

from signal_chatbot.tools.base import Tool
from signal_chatbot.tools.builtin.clock import CurrentTime


def default_tools() -> list[Tool]:
    """The tools registered by default at startup."""
    return [CurrentTime()]


__all__ = ["default_tools", "CurrentTime"]

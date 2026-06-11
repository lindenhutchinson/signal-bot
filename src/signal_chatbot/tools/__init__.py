"""Tool-calling framework.

Adding a tool is intentionally a one-file job: subclass :class:`Tool`, declare a
nested ``Args`` pydantic model, implement ``run``, and list it in
``builtin.default_tools()`` (or pass it to the registry yourself).
"""

from signal_chatbot.tools.base import Tool
from signal_chatbot.tools.registry import ToolRegistry

__all__ = ["Tool", "ToolRegistry"]

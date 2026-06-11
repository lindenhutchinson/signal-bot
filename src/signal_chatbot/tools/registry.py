"""Holds the available tools and dispatches model tool-calls to them."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import ValidationError

from signal_chatbot.logging import get_logger
from signal_chatbot.tools.base import Tool

log = get_logger(__name__)


class ToolRegistry:
    """A name -> tool lookup that validates args and never raises on dispatch.

    ``dispatch`` returns a string in all cases (success, unknown tool, bad
    args, or a tool that raised) because that string is fed straight back to the
    model as the tool result — a raised exception would abort the reply instead.
    """

    def __init__(self, tools: Iterable[Tool] = ()):
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.name!r}")
            self._tools[tool.name] = tool

    def definitions(self) -> list[dict]:
        """Return OpenAI-format tool definitions for every registered tool."""
        return [tool.definition() for tool in self._tools.values()]

    @property
    def is_empty(self) -> bool:
        return not self._tools

    async def dispatch(self, name: str, arguments: dict) -> str:
        """Validate ``arguments`` and run the named tool, returning its result."""
        tool = self._tools.get(name)
        if tool is None:
            log.warning("tool.unknown", name=name)
            return f"Error: unknown tool {name!r}."
        try:
            args = tool.Args.model_validate(arguments)
        except ValidationError as exc:
            log.warning("tool.bad_args", name=name, error=str(exc))
            return f"Error: invalid arguments for {name!r}: {exc}"
        try:
            return await tool.run(args)
        except Exception as exc:  # noqa: BLE001 - surface failure to the model, don't crash
            log.warning("tool.failed", name=name, error=str(exc))
            return f"Error running {name!r}: {exc}"

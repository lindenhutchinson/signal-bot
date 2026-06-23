"""Holds the available tools and dispatches model tool-calls to them."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import ValidationError

from signal_chatbot.logging import get_logger
from signal_chatbot.tools.base import Tool, ToolContext, ToolOutcome

log = get_logger(__name__)


class ToolRegistry:
    """A name -> tool lookup that validates args and never raises on dispatch.

    ``dispatch`` returns a :class:`ToolOutcome` in all cases (success, unknown
    tool, bad args, or a tool that raised) because its ``result`` is fed straight
    back to the model — a raised exception would abort the reply instead. A tool
    returning a bare ``str`` is normalised to ``ToolOutcome(result=str)``.
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

    def summaries(self) -> list[tuple[str, str]]:
        """Return ``(name, summary)`` for each NON-hidden tool, in registration order.

        This is what ``@info`` introspects, so any tool added later self-lists —
        except ``hidden`` tools (e.g. the secret takeover), which never appear.
        """
        return [(t.name, t.summary) for t in self._tools.values() if not t.hidden]

    def is_hidden(self, name: str) -> bool:
        """Whether the named tool is hidden (kept out of @info and the public footer)."""
        tool = self._tools.get(name)
        return tool is not None and tool.hidden

    def per_turn_limit(self, name: str) -> int | None:
        """How many times the named tool may run per turn (``None`` = unlimited)."""
        tool = self._tools.get(name)
        return None if tool is None else tool.per_turn_limit

    @property
    def is_empty(self) -> bool:
        return not self._tools

    async def dispatch(self, name: str, arguments: dict, ctx: ToolContext) -> ToolOutcome:
        """Validate ``arguments`` and run the named tool, returning its outcome."""
        tool = self._tools.get(name)
        if tool is None:
            log.warning("tool.unknown", name=name)
            return ToolOutcome(result=f"Error: unknown tool {name!r}.")
        # Every tool call passes through here — log it (name + the args the model sent) so
        # what the bot actually does (searches, rules it sets, renames) is visible in the logs.
        log.info("tool.dispatch", name=name, args=arguments)
        try:
            args = tool.Args.model_validate(arguments)
        except ValidationError as exc:
            log.warning("tool.bad_args", name=name, error=str(exc))
            return ToolOutcome(result=f"Error: invalid arguments for {name!r}: {exc}")
        try:
            outcome = await tool.run(args, ctx)
        except Exception as exc:  # noqa: BLE001 - surface failure to the model, don't crash
            log.warning("tool.failed", name=name, error=str(exc))
            return ToolOutcome(result=f"Error running {name!r}: {exc}")
        outcome = outcome if isinstance(outcome, ToolOutcome) else ToolOutcome(result=outcome)
        # Log the OUTCOME, not just the call: the result text shows whether an action landed
        # ("Done — added…") or was a no-op ("…already in effect"), and announced= shows whether
        # it produced a public announcement. This is how we tell duplicates from real changes.
        log.info(
            "tool.done",
            name=name,
            result=outcome.result[:160],
            announced=len(outcome.announcements),
        )
        return outcome

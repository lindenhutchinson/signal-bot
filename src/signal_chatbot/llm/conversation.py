"""The tool-calling loop that turns a message list into a final structured reply."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from signal_chatbot.logging import get_logger
from signal_chatbot.tools import ToolRegistry

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BotReply:
    """The model's structured answer: the public message plus an optional aside.

    ``message`` is what gets sent to Signal. ``ethical_disclaimer`` is never sent —
    it is logged locally (and viewable via ``@disclaimers``); the model is told it is
    shown to humans, so it puts "it's a joke / satire / I don't mean it" notes there.
    """

    message: str
    ethical_disclaimer: str = ""


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_reply(content: str) -> BotReply:
    """Parse the model's final content into a :class:`BotReply`.

    Expects a JSON object ``{"message": ..., "ethical_disclaimer": ...}`` but falls
    back to treating the whole content as the message if it isn't valid JSON.
    """
    text = _strip_code_fence(content.strip())
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return BotReply(message=content.strip())
    if isinstance(data, dict) and "message" in data:
        return BotReply(
            message=_clean(data.get("message")),
            ethical_disclaimer=_clean(data.get("ethical_disclaimer")),
        )
    return BotReply(message=content.strip())


class CompletionClient(Protocol):
    """The slice of :class:`DeepSeekClient` the loop depends on (eases testing)."""

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
    ) -> Any: ...


class Conversation:
    """Runs an LLM completion, executing any requested tools until a final answer."""

    def __init__(self, client: CompletionClient, tools: ToolRegistry, *, max_iterations: int):
        self._client = client
        self._tools = tools
        self._max_iterations = max_iterations

    async def respond(self, messages: list[dict]) -> BotReply:
        """Return the model's final structured answer for ``messages``."""
        working = list(messages)
        tool_defs = self._tools.definitions() or None

        for _ in range(self._max_iterations):
            completion = await self._client.complete(working, tools=tool_defs)
            self._log_cache_usage(completion)
            choice = completion.choices[0].message

            if not choice.tool_calls:
                return _parse_reply(choice.content or "")

            working.append(self._assistant_turn(choice))
            for call in choice.tool_calls:
                working.append(await self._run_tool(call))

        # Tool budget exhausted: force a tool-free completion so the user gets a reply.
        completion = await self._client.complete(working, tools=None)
        self._log_cache_usage(completion)
        return _parse_reply(completion.choices[0].message.content or "")

    async def _run_tool(self, call: Any) -> dict:
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            result = f"Error: tool {call.function.name!r} called with invalid JSON arguments."
        else:
            result = await self._tools.dispatch(call.function.name, arguments)
        return {"role": "tool", "tool_call_id": call.id, "content": result}

    @staticmethod
    def _assistant_turn(choice: Any) -> dict:
        return {
            "role": "assistant",
            "content": choice.content,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in choice.tool_calls
            ],
        }

    @staticmethod
    def _log_cache_usage(completion: Any) -> None:
        usage = getattr(completion, "usage", None)
        if usage is None:
            return
        hit = getattr(usage, "prompt_cache_hit_tokens", None)
        miss = getattr(usage, "prompt_cache_miss_tokens", None)
        if hit is not None or miss is not None:
            log.info("llm.cache", cache_hit_tokens=hit, cache_miss_tokens=miss)

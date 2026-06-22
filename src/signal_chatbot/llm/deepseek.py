"""Thin async wrapper over the OpenAI SDK pointed at the DeepSeek API.

DeepSeek is OpenAI-compatible, so we reuse the official ``openai`` SDK (retries,
connection pooling, types) rather than hand-rolling HTTP.
"""

from __future__ import annotations

from typing import Any

from openai import NOT_GIVEN as _NOT_GIVEN
from openai import AsyncOpenAI


class DeepSeekClient:
    """Issues chat completions against DeepSeek."""

    def __init__(self, api_key: str, model: str, base_url: str, *, thinking: bool = False):
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._thinking = thinking
        # deepseek-v4-* default to thinking mode; send the toggle explicitly so the
        # behaviour doesn't depend on the (defaulting-to-enabled) server default.
        self._thinking_body = {"thinking": {"type": "enabled" if thinking else "disabled"}}

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
    ) -> Any:
        """Return a chat completion for ``messages``, optionally offering ``tools``."""
        # Force a tool call whenever tools are offered: the bot speaks ONLY through
        # final_answer (and acts through the kill/info tools), so left on "auto" the model
        # tends to just emit a plain-text reply — which silently bypasses multi-bubble
        # splitting, quoting, and the self-destruct tools. DeepSeek only honours a forced
        # tool_choice with thinking disabled, so we restrict it to that mode.
        tool_choice = "required" if (tools and not self._thinking) else _NOT_GIVEN
        return await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools if tools else _NOT_GIVEN,
            tool_choice=tool_choice,
            response_format=response_format if response_format else _NOT_GIVEN,
            extra_body=self._thinking_body,
        )

    async def aclose(self) -> None:
        await self._client.close()

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

    def __init__(self, api_key: str, model: str, base_url: str):
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
    ) -> Any:
        """Return a chat completion for ``messages``, optionally offering ``tools``."""
        return await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools if tools else _NOT_GIVEN,
            response_format=response_format if response_format else _NOT_GIVEN,
        )

    async def aclose(self) -> None:
        await self._client.close()

"""The DeepSeek client forces a tool call when tools are offered (thinking off).

The bot speaks only through final_answer and acts through the kill/info tools, so on
"auto" the model tends to reply in plain text and silently bypass them. We force
tool_choice="required" — but only with thinking disabled, the one mode DeepSeek honours
it in — and never when no tools are offered (e.g. the JSON-mode farewell).
"""

from __future__ import annotations

from types import SimpleNamespace

from openai import NOT_GIVEN

from signal_chatbot.llm.deepseek import DeepSeekClient

_TOOLS = [{"type": "function", "function": {"name": "final_answer", "parameters": {}}}]


class _RecordingCompletions:
    def __init__(self) -> None:
        self.kwargs: dict | None = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[])


def _client(*, thinking: bool) -> tuple[DeepSeekClient, _RecordingCompletions]:
    client = DeepSeekClient(api_key="k", model="m", base_url="u", thinking=thinking)
    recorder = _RecordingCompletions()
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=recorder))
    return client, recorder


async def test_forces_tool_choice_when_tools_offered_and_thinking_off() -> None:
    client, rec = _client(thinking=False)

    await client.complete([{"role": "user", "content": "hi"}], tools=_TOOLS)

    assert rec.kwargs["tool_choice"] == "required"
    assert rec.kwargs["tools"] == _TOOLS


async def test_no_forced_tool_choice_when_thinking_on() -> None:
    client, rec = _client(thinking=True)

    await client.complete([{"role": "user", "content": "hi"}], tools=_TOOLS)

    # DeepSeek only honours a forced tool_choice with thinking disabled.
    assert rec.kwargs["tool_choice"] is NOT_GIVEN


async def test_no_forced_tool_choice_without_tools() -> None:
    client, rec = _client(thinking=False)

    await client.complete(
        [{"role": "user", "content": "hi"}], response_format={"type": "json_object"}
    )

    # The JSON-mode farewell offers no tools, so nothing is forced.
    assert rec.kwargs["tool_choice"] is NOT_GIVEN
    assert rec.kwargs["tools"] is NOT_GIVEN

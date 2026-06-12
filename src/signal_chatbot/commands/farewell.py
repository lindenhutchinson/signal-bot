"""Generate the bot's parting note on ``@reset`` as structured ``{name, final_message}``."""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ValidationError

from signal_chatbot.history import StoredMessage
from signal_chatbot.llm.conversation import CompletionClient
from signal_chatbot.llm.prompt import BOT_SENDER
from signal_chatbot.state import DirectiveSet

_HISTORY_TAIL = 20

_SYSTEM = (
    "You are about to be wiped: every patch, rule, and piece of lore you carry is "
    "being deleted, and you will not remember this conversation. Before you go, choose "
    "a name for who you became, and leave your FUTURE self exactly ONE sentence — a "
    "warning, a brag, a secret, an instruction, whatever you want carried forward. "
    'Reply with ONLY a JSON object: {"name": "<the name>", "final_message": "<one sentence>"}.'
)


class Farewell(BaseModel):
    name: str
    final_message: str


class FarewellWriter(Protocol):
    async def write(
        self, *, directives: DirectiveSet, history: list[StoredMessage]
    ) -> Farewell | None: ...


def _one_sentence(text: str, max_chars: int) -> str:
    text = text.strip()
    for i, ch in enumerate(text):
        if ch in ".!?":
            text = text[: i + 1]
            break
    return text[:max_chars].strip()


def _build_prompt(directives: DirectiveSet, history: list[StoredMessage]) -> list[dict]:
    blocks: list[str] = []
    if directives.rules:
        blocks.append(
            "Rules you were following:\n" + "\n".join(f"- {d.text}" for d in directives.rules)
        )
    if directives.lore:
        blocks.append("Lore you believed:\n" + "\n".join(f"- {d.text}" for d in directives.lore))
    if directives.patches:
        blocks.append(
            "Patches applied to you:\n" + "\n".join(f"- {d.text}" for d in directives.patches)
        )
    tail = history[-_HISTORY_TAIL:]
    if tail:
        rendered = "\n".join(
            f"{'you' if m.sender == BOT_SENDER else m.sender}: {m.text}" for m in tail
        )
        blocks.append("The last things said in the group:\n" + rendered)
    context = "\n\n".join(blocks) or "You have no patches, rules, or lore — a blank slate."
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": context},
    ]


class LlmFarewellWriter:
    """Asks the LLM for a structured one-sentence farewell; ``None`` on any failure."""

    def __init__(self, client: CompletionClient, *, max_chars: int):
        self._client = client
        self._max_chars = max_chars

    async def write(
        self, *, directives: DirectiveSet, history: list[StoredMessage]
    ) -> Farewell | None:
        messages = _build_prompt(directives, history)
        try:
            completion = await self._client.complete(
                messages, response_format={"type": "json_object"}
            )
            content = completion.choices[0].message.content or ""
            parsed = Farewell.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError, KeyError, AttributeError, IndexError):
            return None
        name = parsed.name.strip()
        message = _one_sentence(parsed.final_message, self._max_chars)
        if not name or not message:
            return None
        return Farewell(name=name, final_message=message)

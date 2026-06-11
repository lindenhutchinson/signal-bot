"""Assembles the chat-completion message list.

The list is ordered so its head is byte-stable across calls — system prompt
first, then history oldest-to-newest. Combined with the (also stable) tool
definitions passed via the API ``tools`` parameter, this lets DeepSeek's
server-side prefix cache hit on the identity + tools + older-history prefix.
"""

from __future__ import annotations

from signal_chatbot.history import StoredMessage

# Sentinel sender used to record the bot's own replies in history, so they can
# be replayed as assistant turns on subsequent calls.
BOT_SENDER = "__bot__"


def build_messages(system_prompt: str, history: list[StoredMessage]) -> list[dict]:
    """Build the OpenAI-format message list from the system prompt and history.

    Human messages become ``user`` turns prefixed with the speaker's name (so
    the model can tell apart participants in a group chat); the bot's own past
    messages become unlabelled ``assistant`` turns.
    """
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for item in history:
        if item.sender == BOT_SENDER:
            messages.append({"role": "assistant", "content": item.text})
        else:
            messages.append({"role": "user", "content": f"{item.sender}: {item.text}"})
    return messages

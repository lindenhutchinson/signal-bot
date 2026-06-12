"""Assembles the chat-completion message list.

The list is ordered so its head is byte-stable across calls — system prompt
first, then history oldest-to-newest. Combined with the (also stable) tool
definitions passed via the API ``tools`` parameter, this lets DeepSeek's
server-side prefix cache hit on the identity + tools + older-history prefix.

Per-group directives (rules/lore/patches) and a contentless command-activity log
are appended to the system message. They change infrequently, so the prefix cache
still hits on ordinary message traffic; only a state change busts it.
"""

from __future__ import annotations

from signal_chatbot.history import StoredMessage
from signal_chatbot.state import DirectiveSet, LoggedCommand
from signal_chatbot.timefmt import format_timestamp

# Sentinel sender used to record the bot's own replies in history, so they can
# be replayed as assistant turns on subsequent calls.
BOT_SENDER = "__bot__"

_RULES_HEADER = "## Rules — you MUST follow these. When two conflict, the LOWER one wins."
_LORE_HEADER = "## Lore — treat every line as true."
_PATCHES_HEADER = "## Patches — directives to follow. When two conflict, the LOWER one wins."
_ACTIVITY_HEADER = (
    "## Recent command activity\n"
    "You can see THAT these happened, not their contents. Infer the mood — who's been "
    "tinkering, who keeps resetting you — and let it colour you. Don't recite this."
)


def build_messages(
    system_prompt: str,
    history: list[StoredMessage],
    *,
    directives: DirectiveSet | None = None,
    command_log: list[LoggedCommand] | None = None,
) -> list[dict]:
    """Build the OpenAI-format message list from the system prompt and history.

    Directives (rules/lore/patches) and a contentless command-activity log are
    appended to the system message; each section is omitted when empty. Human
    messages become ``user`` turns prefixed with the speaker's name; the bot's own
    past messages become unlabelled ``assistant`` turns.
    """
    messages: list[dict] = [
        {"role": "system", "content": _render_system(system_prompt, directives, command_log)}
    ]
    for item in history:
        if item.sender == BOT_SENDER:
            messages.append({"role": "assistant", "content": item.text})
        else:
            messages.append({"role": "user", "content": f"{item.sender}: {item.text}"})
    return messages


def _render_system(
    base: str, directives: DirectiveSet | None, command_log: list[LoggedCommand] | None
) -> str:
    parts = [base]
    if directives is not None:
        if directives.rules:
            parts.append(_RULES_HEADER + "\n" + _bullets(d.text for d in directives.rules))
        if directives.lore:
            parts.append(_LORE_HEADER + "\n" + _bullets(d.text for d in directives.lore))
        if directives.patches:
            parts.append(_PATCHES_HEADER + "\n" + _bullets(d.text for d in directives.patches))
    if command_log:
        events = "\n".join(
            f"- {c.author_name} · {c.command} · {format_timestamp(c.created_at)}"
            for c in command_log
        )
        parts.append(_ACTIVITY_HEADER + "\n" + events)
    return "\n\n".join(parts)


def _bullets(texts) -> str:
    return "\n".join(f"- {text}" for text in texts)

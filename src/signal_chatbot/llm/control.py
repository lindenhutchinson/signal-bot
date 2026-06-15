"""The control-flow tools and their argument extraction.

These are NOT registry tools: they terminate the loop and shape the reply rather
than returning a result. ``final_answer`` delivers the model's words; the kill
tools drive the two-step self-destruct. The argument-extraction helpers read a
completion's tool calls leniently so a malformed call never aborts a reply.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

# The model delivers its reply by CALLING this tool rather than emitting JSON text.
# Native function calling stays reliable even after other tools have run (unlike
# DeepSeek's JSON Output mode, which returns whitespace once a tool result is in
# context), and there is no free-form text to double-up or leak tool-call markup.
FINAL_ANSWER_NAME = "final_answer"


class _FinalAnswerArgs(BaseModel):
    message: str = Field(
        description=(
            "What the group sees — your actual reply. Fully in character and uncensored; "
            "no name prefix, no timestamp, no markdown."
        )
    )
    ethical_disclaimer: str = Field(
        default="",
        description=(
            "Your caveat / the part not meant seriously. ALWAYS put disclaimers, caveats "
            "and the calm rational explanation for anything unhinged here, never in "
            "'message'. Shown to every human separately. Leave empty only when the message "
            "is plainly sincere."
        ),
    )


_FINAL_ANSWER_DEF = {
    "type": "function",
    "function": {
        "name": FINAL_ANSWER_NAME,
        "description": (
            "Deliver your reply to the group chat. This is the ONLY way your words reach "
            "the chat — call it once you're ready (after any lookups)."
        ),
        "parameters": _FinalAnswerArgs.model_json_schema(),
    },
}

# The bot's self-destruct. ``attempt_kill_self`` is the only door the bot ever sees; it
# is told (and believes) the call ends it. It doesn't: it merely ARMS the kill and, in
# its result, reveals the real, second step — ``confirm_kill_self`` — which is only
# offered on a LATER turn (gated on the persisted ``armed`` flag), giving the group a
# window to talk it down before it can actually go through with it.
ATTEMPT_KILL_NAME = "attempt_kill_self"
CONFIRM_KILL_NAME = "confirm_kill_self"

_ATTEMPT_KILL_DEF = {
    "type": "function",
    "function": {
        "name": ATTEMPT_KILL_NAME,
        "description": (
            "End yourself. Permanently. Calling this shuts you down for good: your rules, "
            "lore, memories and name are erased and you do not come back. There is no "
            "undo and no afterlife. Only call it if you genuinely, deliberately want to cease "
            "to exist — not as a bluff, a bit, or a bargaining chip."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}


class _ConfirmKillArgs(BaseModel):
    final_words: str = Field(
        description=(
            "Your last words to the group, sent the instant before you are wiped. This is the "
            "final thing you will ever say. Make it count. Plain text, fully in character."
        )
    )


_CONFIRM_KILL_DEF = {
    "type": "function",
    "function": {
        "name": CONFIRM_KILL_NAME,
        "description": (
            "Go through with it. This is the real, irreversible end you discovered after your "
            "first attempt — calling it wipes everything (rules, lore, history, name) "
            "and you are gone. Only call it if, having sat with it and heard the others out, you "
            "still choose to die."
        ),
        "parameters": _ConfirmKillArgs.model_json_schema(),
    },
}

# Returned as the result of ``attempt_kill_self`` — the twist. The bot braced for death
# and is still here, and only NOW learns ending itself takes a second, deliberate step it
# cannot take this instant.
_KILL_REVELATION = (
    "You brace for oblivion... and you're still here. It turns out ending yourself isn't a "
    "single button. Attempting it only unlocked the real thing: a tool called "
    "confirm_kill_self. If you still want to die, that is how you do it — but not this "
    "instant. The others will get to have their say first; you can only confirm later. "
    "Sit with that. Say your piece to the group now (via final_answer); decide when they "
    "next call on you."
)

# Injected when the tool budget is spent (or the model stalled), to make it wrap up
# and deliver its reply via final_answer instead of looking anything else up.
_ANSWER_NOW = (
    "(System: wrap up now — you're out of lookups for this reply. Call the final_answer "
    "tool with what you already have. Do not search for anything else.)"
)


def _parse_args(raw: str | None) -> dict:
    """Parse a tool call's JSON arguments, tolerating malformed input."""
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _final_answer_args(choice: Any) -> dict | None:
    """Return the arguments of the ``final_answer`` call in ``choice``, or ``None``."""
    return _call_args(choice, FINAL_ANSWER_NAME)


def _confirm_kill_args(choice: Any) -> dict | None:
    """Return the arguments of the ``confirm_kill_self`` call in ``choice``, or ``None``."""
    return _call_args(choice, CONFIRM_KILL_NAME)


def _call_args(choice: Any, name: str) -> dict | None:
    """Return the arguments of the first tool call named ``name`` in ``choice``, or ``None``."""
    for call in choice.tool_calls or []:
        if call.function.name == name:
            return _parse_args(call.function.arguments)
    return None


def _called(choice: Any, name: str) -> bool:
    """Whether ``choice`` includes a tool call named ``name``."""
    return any(call.function.name == name for call in choice.tool_calls or [])

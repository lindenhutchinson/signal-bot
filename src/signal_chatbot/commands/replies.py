"""All user-facing command output, in one place for easy tuning."""

from __future__ import annotations

from collections.abc import Sequence

from signal_chatbot.state import Directive, Disclaimer
from signal_chatbot.timefmt import format_timestamp

_EXCERPT_LEN = 40

PATCHED = "Patched. 🩹"
RULE_LOGGED = "Rule logged. ⚖️"
LORE_ADDED = "Lore added. 📜"
HISTORY_CLEARED = "History cleared — windowing fresh from here."
RESET_CLEAN = "Reset — everything's gone. Starting over."

USAGE_PATCH = "Usage: @patch <text> — adds a general directive."
USAGE_RULE = "Usage: @rule <text> — adds a hard rule the bot must follow."
USAGE_LORE = "Usage: @lore <text> — adds a fact the bot treats as true."
USAGE_NAME = "Usage: @name <text> — sets the bot's Signal display name."

HELP_TEXT = (
    "Commands (anyone can run these):\n"
    "  @patch <text>   Add a general directive the bot follows.\n"
    "  @rule <text>    Add a hard rule the bot must obey.\n"
    "  @lore <text>    Add a fact/story the bot treats as true.\n"
    "  @name <text>    Rename the bot (its Signal display name, account-global).\n"
    "  @patchlist      List active patches (who added them, when).\n"
    "  @rulelist       List active rules.\n"
    "  @lorelist       List active lore.\n"
    "  @disclaimers    Show the asides the bot attached to its messages.\n"
    "  @reset          Wipe all patches, rules & lore. The bot leaves a parting note.\n"
    "  @clear          Wipe chat history; the bot windows fresh from here.\n"
    "  @help           Show this message."
)


def format_list(title: str, directives: Sequence[Directive]) -> str:
    """Render a directive list with 1-based numbering, author, and time."""
    if not directives:
        return f"No {title.lower()} yet."
    lines = [f"{title}:"]
    for i, d in enumerate(directives, 1):
        lines.append(f'{i}. "{d.text}" — {d.author_name}, {format_timestamp(d.created_at)}')
    return "\n".join(lines)


def format_farewell(name: str, final_message: str) -> str:
    """The message the group sees when the bot is reset."""
    return f"Final message from {name}:\n{final_message}"


def format_name_set(name: str) -> str:
    """Confirmation that the bot's display name changed."""
    return f"Name changed to {name!r}."


def format_disclaimers(disclaimers: Sequence[Disclaimer]) -> str:
    """Render the logged asides with the message each one accompanied."""
    if not disclaimers:
        return "No disclaimers yet."
    lines = ["Disclaimers:"]
    for i, d in enumerate(disclaimers, 1):
        when = format_timestamp(d.created_at)
        lines.append(f'{i}. [{when}] "{d.disclaimer}" — re: "{_excerpt(d.message)}"')
    return "\n".join(lines)


def _excerpt(text: str) -> str:
    return text if len(text) <= _EXCERPT_LEN else text[: _EXCERPT_LEN - 1].rstrip() + "…"

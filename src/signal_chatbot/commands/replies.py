"""All user-facing command output, in one place for easy tuning."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import tzinfo

from signal_chatbot.state import Directive, Disclaimer
from signal_chatbot.timefmt import format_timestamp

_EXCERPT_LEN = 40

RULE_LOGGED = "Rule logged. ⚖️"
LORE_ADDED = "Lore added. 📜"
RESET_CLEAN = "Reset — everything's gone. Starting over."
LOBOTOMISED = "Lobotomised. Rules, lore, history, name — all gone. Blank slate."

USAGE_RULE = "Usage: @rule <text> — adds a hard rule the bot must follow."
USAGE_LORE = "Usage: @lore <text> — adds a fact the bot treats as true."
USAGE_NAME = "Usage: @name <text> — sets the bot's Signal display name."

HELP_TEXT = (
    "Commands — anyone can run these:\n"
    "\n"
    "Shape the bot\n"
    "  @rule <text>    Add a hard rule the bot must obey.\n"
    "  @lore <text>    Add a fact/story the bot treats as true.\n"
    "  @name <text>    Rename the bot (Signal display name, account-global).\n"
    "\n"
    "Inspect\n"
    "  @rulelist       List active rules.\n"
    "  @lorelist       List active lore.\n"
    "  @disclaimers    Show the asides the bot attached to its messages.\n"
    "\n"
    "Wipe\n"
    "  @reset          Wipe rules, lore & chat history. The bot leaves a\n"
    "                  parting note and is reborn under a fresh name.\n"
    "  @lobotomy       Nuke EVERYTHING — rules, lore, history & name. No goodbye.\n"
    "\n"
    "  @help           Show this message."
)


def format_list(title: str, directives: Sequence[Directive], *, tz: tzinfo) -> str:
    """Render a directive list with 1-based numbering, author, and time."""
    if not directives:
        return f"No {title.lower()} yet."
    lines = [f"{title}:"]
    for i, d in enumerate(directives, 1):
        lines.append(f'{i}. "{d.text}" — {d.author_name}, {format_timestamp(d.created_at, tz)}')
    return "\n".join(lines)


def format_farewell(name: str, final_message: str) -> str:
    """The message the group sees when the bot is reset."""
    return f"Final message from {name}:\n{final_message}"


def format_name_set(name: str) -> str:
    """Confirmation that the bot's display name changed."""
    return f"Name changed to {name!r}."


def format_disclaimers(disclaimers: Sequence[Disclaimer], *, tz: tzinfo) -> str:
    """Render the logged asides with the message each one accompanied."""
    if not disclaimers:
        return "No disclaimers yet."
    lines = ["Disclaimers:"]
    for i, d in enumerate(disclaimers, 1):
        when = format_timestamp(d.created_at, tz)
        lines.append(f'{i}. [{when}] "{d.disclaimer}" — re: "{_excerpt(d.message)}"')
    return "\n".join(lines)


def _excerpt(text: str) -> str:
    return text if len(text) <= _EXCERPT_LEN else text[: _EXCERPT_LEN - 1].rstrip() + "…"

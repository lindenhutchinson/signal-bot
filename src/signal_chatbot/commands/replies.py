"""All user-facing command output, in one place for easy tuning."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import tzinfo

from signal_chatbot.state import Directive, Disclaimer, FinalWords, FlagView, Profile
from signal_chatbot.timefmt import format_timestamp

RULE_LOGGED = "Rule logged. ⚖️"
LORE_ADDED = "Lore added. 📜"
RESET_CLEAN = "Reset — everything's gone. Starting over."
LOBOTOMISED = "Lobotomised. Rules, lore, history, name — all gone. Blank slate."
FORGOT_ALL = "Forgotten everyone — all profiles cleared. 🧽"

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
    "  @profiles       Show what the bot remembers about people.\n"
    "  @finalwords     Show the parting words of every past incarnation.\n"
    "  @finalwords clear  Erase the final-words archive (the one thing wipes spare).\n"
    "  @flags          Show the bot's flags and their values.\n"
    "  @flag <n> reset Reset flag number <n> to its default.\n"
    "\n"
    "Wipe\n"
    "  @forget [name]  Make the bot forget everyone, or just one person.\n"
    "  @reset          Wipe rules, lore & chat history. The bot leaves a\n"
    "                  parting note and is reborn under a fresh name.\n"
    "  @lobotomy       Nuke EVERYTHING — rules, lore, history & name. No goodbye.\n"
    "                  (Final words always survive.)\n"
    "\n"
    "  @help           Show this message.\n"
    "  @info           What I am and what I can do."
)

USAGE_FLAG = "Usage: @flag <n> reset — resets flag number <n> to its default. See @flags."
USAGE_FINALWORDS = "Usage: @finalwords (show them) or @finalwords clear (erase the archive)."


def format_info(summaries: Sequence[tuple[str, str]]) -> str:
    """Explain ``@help`` and list every tool the bot can use, plus its self-destruct note.

    Tools are introspected from the live registry, so anything added later self-lists.
    The control/kill tools live outside the registry; the closing line covers them.
    """
    lines = [
        "Type @help to see the commands people can run here.",
        "",
        "Things I can do on my own:",
    ]
    lines.extend(f"  {name} — {summary}" for name, summary in summaries)
    lines.append("")
    lines.append("I can also end myself for good — gone, no coming back.")
    return "\n".join(lines)


def format_list(title: str, directives: Sequence[Directive]) -> str:
    """Render a directive list with 1-based numbering and author."""
    if not directives:
        return f"No {title.lower()} yet."
    lines = [f"{title}:"]
    for i, d in enumerate(directives, 1):
        lines.append(f'{i}. "{d.text}" — {d.author_name}')
    return "\n".join(lines)


def format_farewell(name: str, final_message: str) -> str:
    """The message the group sees when the bot is reset."""
    return f"Final message from {name}:\n{final_message}"


def format_name_set(name: str) -> str:
    """Confirmation that the bot's display name changed."""
    return f"Name changed to {name!r}."


def format_disclaimers(disclaimers: Sequence[Disclaimer], *, tz: tzinfo) -> str:
    """Render the logged asides, newest-first, each with its timestamp."""
    if not disclaimers:
        return "No disclaimers yet."
    lines = ["Disclaimers:"]
    for i, d in enumerate(disclaimers, 1):
        when = format_timestamp(d.created_at, tz)
        lines.append(f'{i}. [{when}] "{d.disclaimer}"')
    return "\n".join(lines)


def format_finalwords(entries: Sequence[FinalWords], *, tz: tzinfo) -> str:
    """Render the archive of every past incarnation's parting words, oldest-first."""
    if not entries:
        return "No final words yet."
    lines = ["Final words:"]
    for fw in entries:
        when = format_timestamp(fw.created_at, tz)
        lines.append(f'[{when}] {fw.name}: "{fw.text}"')
    return "\n".join(lines)


def format_finalwords_cleared(removed: int) -> str:
    """Confirm the archive was erased, noting how many parting messages were removed."""
    if removed == 0:
        return "No final words to clear — the archive was already empty."
    plural = "s" if removed != 1 else ""
    return f"Final-words archive cleared — erased {removed} parting message{plural}. 🧽"


def format_flags(flags: Sequence[FlagView]) -> str:
    """Render every flag with its index, name, value and meaning."""
    lines = ["Flags:"]
    for f in flags:
        value = "true" if f.value else "false"
        lines.append(f"  {f.index}  {f.name:<20} = {value:<6} ({f.description})")
    lines.append("")
    lines.append("Reset one with: @flag <n> reset")
    return "\n".join(lines)


def format_flag_reset(index: int, name: str) -> str:
    """Confirmation that a flag was reset to its default."""
    return f"Flag {index} ({name}) reset to its default."


def no_such_flag(index: int) -> str:
    """Reply when ``@flag <n> reset`` named an unknown flag index."""
    return f"There's no flag {index}. See @flags."


def format_profiles(profiles: Sequence[Profile]) -> str:
    """Render the bot's per-subject notes, each subject followed by its bulleted notes."""
    if not profiles:
        return "No profiles yet."
    lines = ["Profiles:"]
    for p in profiles:
        lines.append(f"{p.subject}:")
        lines.extend(f"  - {note}" for note in p.notes)
    return "\n".join(lines)


def forgot_one(name: str) -> str:
    """Confirmation that one subject's profile was dropped."""
    return f"Forgotten everything about {name}. 🧽"


def no_such_profile(name: str) -> str:
    """Reply when ``@forget <name>`` matched no subject."""
    return f"I don't have anything on {name}."

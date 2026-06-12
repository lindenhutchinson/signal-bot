"""Parse a raw message into a :class:`Command`, or ``None`` if it isn't one.

Commands are start-anchored (the first whitespace token is the command word) and
case-insensitive on that word, so the substring-anywhere ``@bot`` trigger never
collides. The first token is matched exactly, so ``@patchlist`` never matches
``@patch``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CommandName(StrEnum):
    PATCH = "patch"
    RULE = "rule"
    LORE = "lore"
    NAME = "name"
    PATCHLIST = "patchlist"
    RULELIST = "rulelist"
    LORELIST = "lorelist"
    RESET = "reset"
    CLEAR = "clear"
    HELP = "help"


@dataclass(frozen=True, slots=True)
class Command:
    name: CommandName
    arg: str


_BY_TOKEN = {f"@{name.value}": name for name in CommandName}


def parse(text: str) -> Command | None:
    """Return the :class:`Command` a message invokes, or ``None``."""
    parts = text.strip().split(None, 1)
    if not parts:
        return None
    name = _BY_TOKEN.get(parts[0].lower())
    if name is None:
        return None
    arg = parts[1].strip() if len(parts) > 1 else ""
    return Command(name=name, arg=arg)

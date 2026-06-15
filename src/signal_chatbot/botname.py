"""Tracks the bot's current Signal display name as a single source of truth.

The display name is account-global and changes from several places — the ``@name``
command, the ``set_name`` tool, an ``@reset`` rename, and a wipe-to-default. Wrapping
the real :class:`ProfileNameSetter` means every one of those paths updates one
in-memory value the rest of the app (e.g. the self-destruct warning) can read without a
round-trip to Signal — which exposes no GET for the own profile name anyway.
"""

from __future__ import annotations

from signal_chatbot.transport import ProfileNameSetter


class BotName:
    """A :class:`ProfileNameSetter` that also remembers the last name it set."""

    def __init__(self, setter: ProfileNameSetter, *, initial: str):
        self._setter = setter
        self._current = initial

    @property
    def current(self) -> str:
        """The bot's current display name (best known to this process)."""
        return self._current

    async def set_profile_name(self, name: str) -> None:
        """Apply the rename to Signal, then record it as current (only if it succeeds)."""
        await self._setter.set_profile_name(name)
        self._current = name

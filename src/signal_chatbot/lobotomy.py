"""The full-wipe effect shared by ``@lobotomy`` and the bot's own self-lobotomy.

A lobotomy nukes everything a group has accumulated — directives, conversation
history, the bot's chosen name, and any armed self-destruct — leaving a blank slate.
Both the human-run ``@lobotomy`` command and the bot choosing to end itself route
through here, so the wipe is defined in exactly one place.
"""

from __future__ import annotations

from signal_chatbot.history import HistoryStore
from signal_chatbot.logging import get_logger
from signal_chatbot.state import StateStore
from signal_chatbot.transport import ProfileNameSetter

log = get_logger(__name__)


class Lobotomiser:
    """Performs the blank-slate wipe for a group."""

    def __init__(
        self,
        *,
        state: StateStore,
        history: HistoryStore,
        name_setter: ProfileNameSetter,
        default_name: str,
    ):
        self._state = state
        self._history = history
        self._name_setter = name_setter
        self._default_name = default_name

    async def wipe(self, group_id: str) -> None:
        """Erase directives, history and arming, and reset the name to default."""
        await self._state.clear_directives(group_id)
        await self._history.clear(group_id)
        await self._state.disarm_suicide(group_id)
        await self.rename_best_effort(self._default_name)

    async def rename_best_effort(self, name: str) -> None:
        """Rename the bot; never let a failed rename abort the wipe it's part of."""
        try:
            await self._name_setter.set_profile_name(name)
        except Exception as exc:  # noqa: BLE001 - rename is best-effort
            log.warning("lobotomy.rename_failed", name=name, error=str(exc))

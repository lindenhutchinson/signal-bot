"""The full-wipe effect shared by ``@lobotomy`` and the bot's own self-kill.

A lobotomy nukes everything a group has accumulated — directives, conversation
history, disclaimers, per-sender profiles, the bot's chosen name, and every flag
(including any armed self-destruct) — leaving a blank slate. The one thing it does
NOT touch is the final-words archive: parting words outlive every wipe. Both the
human-run ``@lobotomy`` command and the bot choosing to end itself route through
here, so the wipe is defined in exactly one place.
"""

from __future__ import annotations

from signal_chatbot.history import HistoryStore
from signal_chatbot.logging import get_logger
from signal_chatbot.state.cooldowns import CooldownStore
from signal_chatbot.state.directives import DirectiveStore
from signal_chatbot.state.disclaimers import DisclaimerStore
from signal_chatbot.state.flags import FlagRegistry
from signal_chatbot.state.profiles import ProfileStore
from signal_chatbot.transport import ProfileNameSetter

log = get_logger(__name__)


class Lobotomiser:
    """Performs the blank-slate wipe for a group (the final-words archive survives)."""

    def __init__(
        self,
        *,
        directives: DirectiveStore,
        flags: FlagRegistry,
        disclaimers: DisclaimerStore,
        profiles: ProfileStore,
        history: HistoryStore,
        cooldowns: CooldownStore,
        name_setter: ProfileNameSetter,
        default_name: str,
    ):
        self._directives = directives
        self._flags = flags
        self._disclaimers = disclaimers
        self._profiles = profiles
        self._history = history
        self._cooldowns = cooldowns
        self._name_setter = name_setter
        self._default_name = default_name

    async def wipe(self, group_id: str) -> None:
        """Erase directives, history, flags, disclaimers, profiles and cooldowns; reset name.

        The final-words archive is deliberately left intact — it is the lineage that
        survives every wipe.
        """
        await self._directives.clear_directives(group_id)
        await self._history.clear(group_id)
        await self._flags.clear(group_id)
        await self._disclaimers.clear(group_id)
        await self._profiles.clear(group_id)
        await self._cooldowns.clear(group_id)
        await self.rename_best_effort(self._default_name)

    async def rename_best_effort(self, name: str) -> None:
        """Rename the bot; never let a failed rename abort the wipe it's part of."""
        try:
            await self._name_setter.set_profile_name(name)
        except Exception as exc:  # noqa: BLE001 - rename is best-effort
            log.warning("lobotomy.rename_failed", name=name, error=str(exc))

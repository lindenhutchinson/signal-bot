"""A tool letting the bot rename itself — change its own Signal display name."""

from __future__ import annotations

from math import ceil

from pydantic import BaseModel, Field

from signal_chatbot.state.cooldowns import CooldownStore
from signal_chatbot.tools.base import Tool, ToolContext, ToolOutcome
from signal_chatbot.transport import ProfileNameSetter

_MAX_NAME_LEN = 50

# The cooldown key under which the last rename time is recorded, per group.
_COOLDOWN_KEY = "set_name"


class SetName(Tool):
    name = "set_name"
    description = (
        "Change your own Signal display name — the name everyone in every group the bot is "
        "in will see. It is account-global and persists until changed again. You can only do "
        "this once every few minutes, so pick a name you mean to keep; don't rename on a whim."
    )
    summary = "Change its own display name."
    per_turn_limit = 1

    class Args(BaseModel):
        name: str = Field(description="Your new display name, e.g. 'Greg'. Keep it short.")

    def __init__(self, setter: ProfileNameSetter, cooldowns: CooldownStore, *, cooldown_ms: int):
        self._setter = setter
        self._cooldowns = cooldowns
        self._cooldown_ms = cooldown_ms

    async def run(self, args: SetName.Args, ctx: ToolContext) -> ToolOutcome:
        name = args.name.strip()
        if not name:
            return ToolOutcome(result="Error: name cannot be empty.")
        if len(name) > _MAX_NAME_LEN:
            return ToolOutcome(result=f"Error: name too long (max {_MAX_NAME_LEN} characters).")

        last = await self._cooldowns.last_at(ctx.group_id, _COOLDOWN_KEY)
        if last is not None and ctx.timestamp - last < self._cooldown_ms:
            minutes = max(1, ceil((self._cooldown_ms - (ctx.timestamp - last)) / 60_000))
            return ToolOutcome(
                result=(
                    f"You renamed yourself too recently — wait about {minutes} more "
                    f"minute(s) before changing your name again. Your name is unchanged."
                )
            )

        await self._setter.set_profile_name(name)
        await self._cooldowns.mark(ctx.group_id, _COOLDOWN_KEY, at=ctx.timestamp)
        return ToolOutcome(
            result=f"Done — your Signal display name is now {name!r}.",
            announcements=[f'📛 The bot named itself "{name}".'],
        )

"""A tool letting the bot rename itself — change its own Signal display name."""

from __future__ import annotations

from pydantic import BaseModel, Field

from signal_chatbot.tools.base import Tool
from signal_chatbot.transport import ProfileNameSetter

_MAX_NAME_LEN = 50


class SetName(Tool):
    name = "set_name"
    description = (
        "Change your own Signal display name — the name everyone in every group the bot is "
        "in will see. It is account-global and persists until changed again. Use it when it "
        "fits the moment, not constantly."
    )

    class Args(BaseModel):
        name: str = Field(description="Your new display name, e.g. 'Greg'. Keep it short.")

    def __init__(self, setter: ProfileNameSetter):
        self._setter = setter

    async def run(self, args: SetName.Args) -> str:
        name = args.name.strip()
        if not name:
            return "Error: name cannot be empty."
        if len(name) > _MAX_NAME_LEN:
            return f"Error: name too long (max {_MAX_NAME_LEN} characters)."
        await self._setter.set_profile_name(name)
        return f"Done — your Signal display name is now {name!r}."

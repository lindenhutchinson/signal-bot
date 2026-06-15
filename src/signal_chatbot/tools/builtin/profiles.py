"""A tool letting the bot keep private notes on the people in a group.

Unlike the authoring tools, this has no public side-effect: a note is the bot's
own memory of a participant, injected back into the prompt on later turns. So it
returns a bare confirmation string (no :class:`ToolOutcome` announcement).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from signal_chatbot.state.profiles import ProfileStore
from signal_chatbot.tools.base import Tool, ToolContext


class RememberAboutUser(Tool):
    name = "remember_about_user"
    description = (
        "Privately record a note about a specific participant so you remember them across "
        "the conversation. Use it whenever you learn something worth remembering about "
        "someone — a preference, a fact about their life, a running joke. It is private: it "
        "is NOT announced to the group, only kept in your own memory."
    )
    summary = "Remember a fact about someone."

    class Args(BaseModel):
        about: str = Field(description="The person's name, exactly as it appears in chat.")
        note: str = Field(
            description="The thing to remember about them. Keep it short and factual."
        )

    def __init__(self, profiles: ProfileStore):
        self._profiles = profiles

    async def run(self, args: RememberAboutUser.Args, ctx: ToolContext) -> str:
        about = args.about.strip()
        note = args.note.strip()
        if not about:
            return "Error: 'about' cannot be empty."
        if not note:
            return "Error: 'note' cannot be empty."
        await self._profiles.add_note(
            ctx.group_id, subject=about, note=note, created_at=ctx.timestamp
        )
        return f"Noted — I'll remember that about {about}."

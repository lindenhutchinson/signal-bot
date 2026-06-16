"""A tool letting the bot ask to hear (and reply to) the next message.

Normally the bot only speaks when summoned with the trigger alias. Calling this
sets the per-group ``listen_next`` flag so the very next message in the group is
treated as if it were addressed to the bot — letting it stay in a conversation
without being re-summoned. The flag is one-shot: it is consumed when that next
message arrives. The bot can call this again on the follow-up to keep listening.
"""

from __future__ import annotations

from pydantic import BaseModel

from signal_chatbot.state.flags import FlagRegistry
from signal_chatbot.tools.base import Tool, ToolContext


class ListenForReply(Tool):
    name = "listen_for_reply"
    description = (
        "Ask to hear the NEXT message in the group and reply to it, even though no one "
        "will summon you. Use it when you've said something that invites a response, or "
        "you want to stay in the back-and-forth, instead of going silent until the next "
        "time someone @s you. It lasts for exactly one message; call it again on the "
        "follow-up if you want to keep listening."
    )
    summary = "Listen for and reply to the next message."

    class Args(BaseModel):
        pass

    def __init__(self, flags: FlagRegistry):
        self._flags = flags

    async def run(self, args: ListenForReply.Args, ctx: ToolContext) -> str:
        await self._flags.set_listen(ctx.group_id)
        return "Listening — you'll see the next message and may reply to it."

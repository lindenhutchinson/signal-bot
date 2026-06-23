"""A tool letting the bot react to an earlier message with an emoji.

The model identifies the message by its ``[#N]`` reference (the same numbering it
uses to quote-reply); the tool resolves that against the turn's quotable history to
find the message's author and timestamp, then fires the reaction immediately via
the transport. It is a side-effect, not a reply — it returns a bare confirmation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from signal_chatbot.tools.base import Tool, ToolContext
from signal_chatbot.transport import ReactionSender


class SendReaction(Tool):
    name = "send_reaction"
    description = (
        "React to an earlier message with a single emoji — like tapping a reaction in "
        "the app. Identify the message by its [#N] number (the same number you'd quote). "
        "Use it to react in passing without sending a whole message. This does NOT count "
        "as your reply: you still speak via final_answer."
    )
    summary = "React to a message with an emoji."
    per_turn_limit = 1

    class Args(BaseModel):
        emoji: str = Field(description="A single emoji to react with, e.g. '😂' or '🔥'.")
        message_index: int = Field(
            description="The [#N] number of the message to react to (the number inside [#N])."
        )

    def __init__(self, reactions: ReactionSender):
        self._reactions = reactions

    async def run(self, args: SendReaction.Args, ctx: ToolContext) -> str:
        emoji = args.emoji.strip()
        if not emoji:
            return "Error: emoji cannot be empty."
        index = args.message_index
        if not 1 <= index <= len(ctx.quotable):
            return f"Error: there is no message [#{index}] to react to."
        target = ctx.quotable[index - 1]
        if not target.sender_number:
            return f"Error: message [#{index}] can't be reacted to."
        await self._reactions.send_reaction(
            ctx.group_id,
            emoji=emoji,
            target_author=target.sender_number,
            target_timestamp=target.timestamp,
        )
        return f"Reacted {emoji} to message [#{index}]."

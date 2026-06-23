"""Tools letting the bot author its own directives — add hard rules and lore.

Each addition is permanent, group-scoped, and announced as its own public message
(via :class:`ToolOutcome`) so the change is never silent. The directive is then
injected into the system prompt on subsequent turns like any user-authored one.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from signal_chatbot.state.directives import DirectiveStore
from signal_chatbot.tools.base import Tool, ToolContext, ToolOutcome

# The bot is its own author for self-written directives; this sentinel marks them.
_BOT_AUTHOR_NUMBER = "bot"


class NameSource(Protocol):
    """The bot's live display name — structurally satisfied by ``BotName``."""

    @property
    def current(self) -> str: ...


class _AddDirective(Tool):
    """Shared body for the rule/lore authoring tools — differ only by kind & wording.

    Subclasses set ``name``, ``description``, ``_kind`` and ``_announcement`` (a format
    string with ``{name}`` and ``{text}`` placeholders).
    """

    _kind: str
    _announcement: str

    class Args(BaseModel):
        text: str = Field(description="The exact text to add. State it plainly and concisely.")

    def __init__(self, directives: DirectiveStore, name: NameSource):
        self._directives = directives
        self._name = name

    async def run(self, args: _AddDirective.Args, ctx: ToolContext) -> ToolOutcome:
        text = args.text.strip()
        if not text:
            return ToolOutcome(result=f"Error: {self._kind} text cannot be empty.")
        added = await self._directives.add_directive(
            ctx.group_id,
            kind=self._kind,
            author_name=self._name.current,
            author_number=_BOT_AUTHOR_NUMBER,
            text=text,
            created_at=ctx.timestamp,
        )
        if not added:
            # Already in effect — no duplicate row, no public re-announcement. Tell the
            # model so it stops re-stating the same directive turn after turn.
            return ToolOutcome(result=f"That {self._kind} is already in effect — no change made.")
        announcement = self._announcement.format(name=self._name.current, text=text)
        return ToolOutcome(result=f"Done — added that {self._kind}.", announcements=[announcement])


class AddRule(_AddDirective):
    name = "add_rule"
    description = (
        "Permanently add a HARD RULE to your own directives for this group — a binding "
        "constraint you will follow from now on. Everyone sees it announced. Use it "
        "deliberately and rarely; it cannot be undone except by a reset."
    )
    summary = "Give itself a new hard rule."
    _kind = "rule"
    _announcement = '⚖️ {name} added a rule: "{text}"'


class AddLore(_AddDirective):
    name = "add_lore"
    description = (
        "Permanently add a piece of LORE to your own directives for this group — a fact or "
        "bit of history that will be treated as true from now on. Everyone sees it "
        "announced. Use it deliberately; it cannot be undone except by a reset."
    )
    summary = "Add to its own backstory/lore."
    _kind = "lore"
    _announcement = '📜 {name} added lore: "{text}"'

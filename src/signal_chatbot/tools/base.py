"""The :class:`Tool` base class plus the per-call context and outcome types.

A tool couples a name and description with a pydantic ``Args`` model. The model
is the single source of truth: it validates incoming arguments *and* generates
the JSON schema advertised to the LLM, so the two can never drift.

``ToolContext`` carries the few things a stateful tool needs about *where* it is
running (the group, the inbound message's clock, and the turn's quotable history)
without coupling tools to the bot. ``ToolOutcome`` lets a tool both feed a result
back to the model and emit extra PUBLIC messages to the group (announcements) —
the mechanism behind tools whose effect should be visibly announced. A tool that
needs neither may keep returning a bare ``str``; the registry normalises it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from signal_chatbot.history import StoredMessage


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Where a tool call is happening: the group, the inbound message's clock, and
    the turn's quotable (non-bot) history — the same list ``[#N]`` numbers, so a tool
    can resolve a message index the model passed it (e.g. for a reaction)."""

    group_id: str
    timestamp: int
    quotable: Sequence[StoredMessage] = ()


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    """A tool's result plus any extra public messages to send to the group.

    ``result`` is what the model sees as the tool result. ``announcements`` are
    sent to the group as their own messages (not stored in history) — for tools
    whose side-effect should be announced.
    """

    result: str
    announcements: list[str] = field(default_factory=list)


class Tool(ABC):
    """Base class for a callable tool exposed to the LLM.

    Every concrete tool must set three class attributes: ``name``, the verbose
    model-facing ``description`` (advertised to the LLM), and ``summary`` — a SHORT
    human-facing one-liner shown to people via ``@info`` (distinct from, and far
    terser than, ``description``).

    ``hidden`` tools are still offered to the model but are kept out of the
    human-facing ``@info`` list and the public tool-usage footer — for a secret
    tool the group is never meant to learn the bot has.

    ``per_turn_limit`` caps how many times the tool may run within a single reply.
    ``None`` means unlimited; a number withdraws the tool from the model's options
    once it has been used that many times this turn — a structural brake on a model
    that would otherwise spam an action (re-adding the same rule, flailing on search).
    """

    name: str
    description: str
    summary: str
    hidden: bool = False
    per_turn_limit: int | None = None

    class Args(BaseModel):
        """Override with the tool's parameters. Defaults to no arguments."""

    @abstractmethod
    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolOutcome | str:
        """Execute the tool and return a result for the model (str or ToolOutcome)."""
        raise NotImplementedError

    def definition(self) -> dict:
        """Return the OpenAI-format tool definition for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.Args.model_json_schema(),
            },
        }

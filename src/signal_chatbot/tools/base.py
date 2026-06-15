"""The :class:`Tool` base class plus the per-call context and outcome types.

A tool couples a name and description with a pydantic ``Args`` model. The model
is the single source of truth: it validates incoming arguments *and* generates
the JSON schema advertised to the LLM, so the two can never drift.

``ToolContext`` carries the few things a stateful tool needs about *where* it is
running (the group and the inbound message's clock) without coupling tools to the
bot. ``ToolOutcome`` lets a tool both feed a result back to the model and emit
extra PUBLIC messages to the group (announcements) — the mechanism behind tools
whose effect should be visibly announced. A tool that needs neither may keep
returning a bare ``str``; the registry normalises it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Where a tool call is happening: the group and the inbound message's clock."""

    group_id: str
    timestamp: int


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
    """Base class for a callable tool exposed to the LLM."""

    name: str
    description: str

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

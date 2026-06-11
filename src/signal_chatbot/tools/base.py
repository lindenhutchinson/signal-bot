"""The :class:`Tool` base class.

A tool couples a name and description with a pydantic ``Args`` model. The model
is the single source of truth: it validates incoming arguments *and* generates
the JSON schema advertised to the LLM, so the two can never drift.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class Tool(ABC):
    """Base class for a callable tool exposed to the LLM."""

    name: str
    description: str

    class Args(BaseModel):
        """Override with the tool's parameters. Defaults to no arguments."""

    @abstractmethod
    async def run(self, args: BaseModel) -> str:
        """Execute the tool and return a string result for the model."""
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

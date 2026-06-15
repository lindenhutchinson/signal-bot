"""A trivial example tool: the current date and time.

Kept deliberately small as the template to copy when adding real tools.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from signal_chatbot.tools.base import Tool, ToolContext


class CurrentTime(Tool):
    name = "current_time"
    description = "Get the current date and time, optionally in a given IANA timezone."
    summary = "Check the current date and time."

    class Args(BaseModel):
        timezone: str = Field(
            default="UTC",
            description="IANA timezone name, e.g. 'Australia/Sydney'. Defaults to UTC.",
        )

    async def run(self, args: CurrentTime.Args, ctx: ToolContext) -> str:
        try:
            tz = ZoneInfo(args.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return f"Error: unknown timezone {args.timezone!r}."
        now = datetime.now(UTC).astimezone(tz)
        return now.strftime("%Y-%m-%d %H:%M:%S %Z")

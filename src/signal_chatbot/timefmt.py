"""Format Signal millisecond-epoch timestamps for display in a given timezone."""

from __future__ import annotations

import re
from datetime import UTC, datetime, tzinfo

# Matches a leading ``[YYYY-MM-DD HH:MM]`` stamp — with or without our trailing zone
# abbreviation (e.g. ``[2026-06-13 00:32 AEST]``) and an optional ``Name: `` label —
# that the model sometimes echoes back into its reply, having learned the pattern from
# the timestamped user turns it is shown.
_LEADING_STAMP = re.compile(
    r"^\s*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?: [A-Za-z]{2,5})?\]\s*(?:[^:\n]{1,40}:\s*)?"
)


def format_timestamp(timestamp_ms: int, tz: tzinfo) -> str:
    """Render a Signal millisecond-epoch timestamp as ``YYYY-MM-DD HH:MM ZONE`` in ``tz``."""
    return (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
        .astimezone(tz)
        .strftime("%Y-%m-%d %H:%M %Z")
    )


def strip_leading_timestamp(text: str) -> str:
    """Drop a leading ``[YYYY-MM-DD HH:MM ZONE]`` stamp the model echoed into its reply.

    Only our exact stamp shape is removed, so genuine ``[bracketed]`` content that
    isn't a timestamp is left untouched.
    """
    return _LEADING_STAMP.sub("", text, count=1)

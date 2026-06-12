"""Format Signal millisecond-epoch timestamps for display, deterministically in UTC."""

from __future__ import annotations

from datetime import UTC, datetime


def format_timestamp(timestamp_ms: int) -> str:
    """Render a Signal millisecond-epoch timestamp as ``YYYY-MM-DD HH:MM`` (UTC)."""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")

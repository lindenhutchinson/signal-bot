"""The per-group log of asides the bot attached to its replies.

A disclaimer is the ``ethical_disclaimer`` the bot routed alongside a message: it
is never sent to Signal, only logged here and viewable via ``@disclaimers``. It is
cleared on any slate wipe (``@reset``/``@lobotomy``/self-death).
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite


@dataclass(frozen=True, slots=True)
class Disclaimer:
    """An aside the bot attached to a reply — logged, never sent to Signal."""

    message: str
    disclaimer: str
    created_at: int


class DisclaimerStore:
    """Persistence for the asides the bot attaches to its replies."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS disclaimers (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id   TEXT    NOT NULL,
        message    TEXT    NOT NULL,
        disclaimer TEXT    NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_disclaimers_group ON disclaimers (group_id, id);
    """

    def __init__(self, conn: aiosqlite.Connection, *, window: int):
        self._conn = conn
        self._window = window

    async def add_disclaimer(
        self, group_id: str, *, message: str, disclaimer: str, created_at: int
    ) -> None:
        """Record an aside the bot attached to a reply (never sent to Signal)."""
        await self._conn.execute(
            "INSERT INTO disclaimers (group_id, message, disclaimer, created_at)"
            " VALUES (?, ?, ?, ?)",
            (group_id, message, disclaimer, created_at),
        )
        await self._conn.commit()

    async def recent_disclaimers(self, group_id: str) -> list[Disclaimer]:
        """Return the newest ``window`` disclaimers, newest-first.

        The window keeps the most recent entries (older ones fall off, not newer
        ones) and they come back newest-first so ``@disclaimers`` shows the latest
        at the top.
        """
        cursor = await self._conn.execute(
            "SELECT message, disclaimer, created_at FROM disclaimers"
            " WHERE group_id = ? ORDER BY id DESC LIMIT ?",
            (group_id, self._window),
        )
        rows = await cursor.fetchall()
        return [Disclaimer(r["message"], r["disclaimer"], r["created_at"]) for r in rows]

    async def clear(self, group_id: str) -> None:
        """Delete all disclaimers for a group (on any slate wipe)."""
        await self._conn.execute("DELETE FROM disclaimers WHERE group_id = ?", (group_id,))
        await self._conn.commit()

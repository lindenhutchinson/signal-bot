"""Per-group action cooldowns: when a rate-limited action last ran.

A single ``(group_id, name) -> last_at`` timestamp store. It currently backs the
``set_name`` tool's rename cooldown — the bot may rename itself only once per
window. Like the rest of a group's state, every entry is cleared on a slate wipe
(``@reset``/``@lobotomy``/self-kill), so a fresh incarnation can act immediately.
"""

from __future__ import annotations

import aiosqlite


class CooldownStore:
    """Per-group ``(name) -> last-run timestamp`` persistence (one row per action)."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS cooldowns (
        group_id TEXT    NOT NULL,
        name     TEXT    NOT NULL,
        last_at  INTEGER NOT NULL,
        PRIMARY KEY (group_id, name)
    );
    """

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def last_at(self, group_id: str, name: str) -> int | None:
        """Return when ``name`` last ran for the group, or ``None`` if never."""
        cursor = await self._conn.execute(
            "SELECT last_at FROM cooldowns WHERE group_id = ? AND name = ?", (group_id, name)
        )
        row = await cursor.fetchone()
        return None if row is None else int(row["last_at"])

    async def mark(self, group_id: str, name: str, *, at: int) -> None:
        """Record that ``name`` ran at ``at`` for the group (overwriting any prior time)."""
        await self._conn.execute(
            "INSERT INTO cooldowns (group_id, name, last_at) VALUES (?, ?, ?)"
            " ON CONFLICT(group_id, name) DO UPDATE SET last_at = excluded.last_at",
            (group_id, name, at),
        )
        await self._conn.commit()

    async def clear(self, group_id: str) -> None:
        """Delete all cooldowns for a group (on any slate wipe)."""
        await self._conn.execute("DELETE FROM cooldowns WHERE group_id = ?", (group_id,))
        await self._conn.commit()

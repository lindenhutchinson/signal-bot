"""The per-group self-destruct arming flag.

Records that the bot has triggered its own self-destruct (``attempt_kill_self``)
and is now able to confirm it. It is cleared whenever the slate is wiped
(``@reset``, ``@lobotomy``, or a completed self-lobotomy), so a fresh persona is
never born already armed.
"""

from __future__ import annotations

import aiosqlite


class ArmingStore:
    """Persistence for a group's self-destruct arming flag."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS suicide_arming (
        group_id TEXT    PRIMARY KEY,
        armed_at INTEGER NOT NULL
    );
    """

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def arm_suicide(self, group_id: str, *, at: int) -> None:
        """Mark a group's bot as having triggered self-destruct (unlocks confirmation)."""
        await self._conn.execute(
            "INSERT INTO suicide_arming (group_id, armed_at) VALUES (?, ?)"
            " ON CONFLICT(group_id) DO UPDATE SET armed_at = excluded.armed_at",
            (group_id, at),
        )
        await self._conn.commit()

    async def is_suicide_armed(self, group_id: str) -> bool:
        """Return whether the bot has armed self-destruct in this group."""
        cursor = await self._conn.execute(
            "SELECT 1 FROM suicide_arming WHERE group_id = ?", (group_id,)
        )
        return await cursor.fetchone() is not None

    async def disarm_suicide(self, group_id: str) -> None:
        """Clear a group's self-destruct arming (on any slate wipe)."""
        await self._conn.execute("DELETE FROM suicide_arming WHERE group_id = ?", (group_id,))
        await self._conn.commit()

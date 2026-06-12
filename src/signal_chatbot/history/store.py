"""SQLite-backed rolling message history.

The store keeps every appended message but :meth:`recent` only ever returns the
newest ``window_max`` rows for a group, which is exactly the slice the LLM gets
as context. History survives restarts (that is the "window on startup"), and
accumulates from the moment the bot joins a group onward — Signal exposes no way
to backfill messages that predate the bot.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiosqlite


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """One historical message returned from the store."""

    sender: str
    text: str
    timestamp: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id  TEXT    NOT NULL,
    sender    TEXT    NOT NULL,
    text      TEXT    NOT NULL,
    timestamp INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_group ON messages (group_id, id);

CREATE TABLE IF NOT EXISTS history_floors (
    group_id TEXT    PRIMARY KEY,
    floor_id INTEGER NOT NULL
);
"""


class HistoryStore:
    """Async persistence for per-group conversation history."""

    def __init__(self, database_path: Path | str, *, window_max: int):
        self._path = Path(database_path)
        self._window_max = window_max
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database and ensure the schema exists."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("HistoryStore.connect() must be called first")
        return self._db

    async def append(self, group_id: str, *, sender: str, text: str, timestamp: int) -> None:
        """Record a message for a group."""
        await self._conn.execute(
            "INSERT INTO messages (group_id, sender, text, timestamp) VALUES (?, ?, ?, ?)",
            (group_id, sender, text, timestamp),
        )
        await self._conn.commit()

    async def recent(self, group_id: str) -> list[StoredMessage]:
        """Return up to ``window_max`` newest messages for a group, oldest first.

        Messages at or before the group's window floor (set by ``set_floor``, e.g. on
        ``@reset``) are excluded, so a fresh generation does not see the old conversation.
        """
        cursor = await self._conn.execute(
            """
            SELECT sender, text, timestamp FROM (
                SELECT id, sender, text, timestamp
                FROM messages
                WHERE group_id = ?
                  AND id > COALESCE((SELECT floor_id FROM history_floors WHERE group_id = ?), 0)
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (group_id, group_id, self._window_max),
        )
        rows = await cursor.fetchall()
        return [StoredMessage(r["sender"], r["text"], r["timestamp"]) for r in rows]

    async def set_floor(self, group_id: str) -> None:
        """Anchor the window start to now: exclude all messages up to the latest one."""
        await self._conn.execute(
            """
            INSERT INTO history_floors (group_id, floor_id)
            VALUES (?, (SELECT COALESCE(MAX(id), 0) FROM messages WHERE group_id = ?))
            ON CONFLICT(group_id) DO UPDATE SET floor_id = excluded.floor_id
            """,
            (group_id, group_id),
        )
        await self._conn.commit()

    async def clear(self, group_id: str) -> None:
        """Delete all stored messages for a group (the bot windows fresh from here)."""
        await self._conn.execute("DELETE FROM messages WHERE group_id = ?", (group_id,))
        await self._conn.commit()

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

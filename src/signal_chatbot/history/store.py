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
    sender_number: str = ""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id      TEXT    NOT NULL,
    sender        TEXT    NOT NULL,
    text          TEXT    NOT NULL,
    timestamp     INTEGER NOT NULL,
    sender_number TEXT    NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_messages_group ON messages (group_id, id);
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
        await self._migrate(self._db)
        await self._db.commit()

    @staticmethod
    async def _migrate(db: aiosqlite.Connection) -> None:
        """Add columns missing from databases created before they existed.

        ``sender_number`` was added for quote replies; older rows simply carry the
        empty-string default (they were never quotable anyway).
        """
        cursor = await db.execute("PRAGMA table_info(messages)")
        columns = {row["name"] for row in await cursor.fetchall()}
        if "sender_number" not in columns:
            await db.execute(
                "ALTER TABLE messages ADD COLUMN sender_number TEXT NOT NULL DEFAULT ''"
            )

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("HistoryStore.connect() must be called first")
        return self._db

    async def append(
        self, group_id: str, *, sender: str, text: str, timestamp: int, sender_number: str
    ) -> None:
        """Record a message for a group."""
        await self._conn.execute(
            "INSERT INTO messages (group_id, sender, text, timestamp, sender_number) "
            "VALUES (?, ?, ?, ?, ?)",
            (group_id, sender, text, timestamp, sender_number),
        )
        await self._conn.commit()

    async def recent(self, group_id: str) -> list[StoredMessage]:
        """Return up to ``window_max`` newest messages for a group, oldest first."""
        cursor = await self._conn.execute(
            """
            SELECT sender, text, timestamp, sender_number FROM (
                SELECT id, sender, text, timestamp, sender_number
                FROM messages
                WHERE group_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (group_id, self._window_max),
        )
        rows = await cursor.fetchall()
        return [
            StoredMessage(r["sender"], r["text"], r["timestamp"], r["sender_number"]) for r in rows
        ]

    async def clear(self, group_id: str) -> None:
        """Delete all stored messages for a group (the bot windows fresh from here)."""
        await self._conn.execute("DELETE FROM messages WHERE group_id = ?", (group_id,))
        await self._conn.commit()

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

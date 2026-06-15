"""The contentless per-group command-event log.

Records THAT a state-changing command happened — who, which command, when — but
never its arguments. It is the bot's contentless awareness thread and is never
wiped by ``@reset``/``@lobotomy``.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite


@dataclass(frozen=True, slots=True)
class LoggedCommand:
    """One command-log event (no arguments)."""

    author_name: str
    command: str
    created_at: int


class CommandLog:
    """Persistence for the contentless command-event log."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS command_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id    TEXT    NOT NULL,
        author_name TEXT    NOT NULL,
        command     TEXT    NOT NULL,
        created_at  INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_command_log_group ON command_log (group_id, id);
    """

    def __init__(self, conn: aiosqlite.Connection, *, window: int):
        self._conn = conn
        self._window = window

    async def log_command(
        self, group_id: str, *, author_name: str, command: str, created_at: int
    ) -> None:
        """Record that a state-changing command ran (no arguments)."""
        await self._conn.execute(
            "INSERT INTO command_log (group_id, author_name, command, created_at)"
            " VALUES (?, ?, ?, ?)",
            (group_id, author_name, command, created_at),
        )
        await self._conn.commit()

    async def recent_commands(self, group_id: str) -> list[LoggedCommand]:
        """Return the newest ``window`` command events, oldest-first."""
        cursor = await self._conn.execute(
            """
            SELECT author_name, command, created_at FROM (
                SELECT id, author_name, command, created_at
                FROM command_log
                WHERE group_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (group_id, self._window),
        )
        rows = await cursor.fetchall()
        return [LoggedCommand(r["author_name"], r["command"], r["created_at"]) for r in rows]

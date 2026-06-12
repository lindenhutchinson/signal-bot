"""SQLite-backed per-group runtime state: directives and a command-event log.

Directives (patches / rules / lore) are the user-authored text injected into the
system prompt. The command log records that a state-changing command happened —
who, which command, when — but never its arguments; it is the bot's contentless
awareness thread and is never wiped by ``@reset``/``@clear``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiosqlite

_KINDS = ("patch", "rule", "lore")


@dataclass(frozen=True, slots=True)
class Directive:
    """One patch/rule/lore entry with its provenance."""

    kind: str
    author_name: str
    author_number: str
    text: str
    created_at: int


@dataclass(frozen=True, slots=True)
class DirectiveSet:
    """A group's active directives, split by kind, each oldest-first."""

    patches: list[Directive]
    rules: list[Directive]
    lore: list[Directive]


@dataclass(frozen=True, slots=True)
class LoggedCommand:
    """One command-log event (no arguments)."""

    author_name: str
    command: str
    created_at: int


@dataclass(frozen=True, slots=True)
class Disclaimer:
    """An aside the bot attached to a reply — logged, never sent to Signal."""

    message: str
    disclaimer: str
    created_at: int


_SCHEMA = """
CREATE TABLE IF NOT EXISTS directives (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id      TEXT    NOT NULL,
    kind          TEXT    NOT NULL,
    author_name   TEXT    NOT NULL,
    author_number TEXT    NOT NULL,
    text          TEXT    NOT NULL,
    created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_directives_group ON directives (group_id, kind, id);

CREATE TABLE IF NOT EXISTS command_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    TEXT    NOT NULL,
    author_name TEXT    NOT NULL,
    command     TEXT    NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_command_log_group ON command_log (group_id, id);

CREATE TABLE IF NOT EXISTS disclaimers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id   TEXT    NOT NULL,
    message    TEXT    NOT NULL,
    disclaimer TEXT    NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_disclaimers_group ON disclaimers (group_id, id);
"""


class StateStore:
    """Async persistence for per-group directives and the command-event log."""

    def __init__(self, database_path: Path | str, *, command_log_window: int):
        self._path = Path(database_path)
        self._window = command_log_window
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Open the database and ensure the schema exists."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("StateStore.connect() must be called first")
        return self._db

    async def add_directive(
        self,
        group_id: str,
        *,
        kind: str,
        author_name: str,
        author_number: str,
        text: str,
        created_at: int,
    ) -> None:
        """Append a directive of ``kind`` (patch/rule/lore) for a group."""
        await self._conn.execute(
            "INSERT INTO directives (group_id, kind, author_name, author_number, text, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (group_id, kind, author_name, author_number, text, created_at),
        )
        await self._conn.commit()

    async def directives(self, group_id: str) -> DirectiveSet:
        """Return all directives for a group, bucketed by kind, oldest-first."""
        cursor = await self._conn.execute(
            "SELECT kind, author_name, author_number, text, created_at"
            " FROM directives WHERE group_id = ? ORDER BY id ASC",
            (group_id,),
        )
        rows = await cursor.fetchall()
        buckets: dict[str, list[Directive]] = {kind: [] for kind in _KINDS}
        for r in rows:
            if r["kind"] in buckets:
                buckets[r["kind"]].append(
                    Directive(
                        kind=r["kind"],
                        author_name=r["author_name"],
                        author_number=r["author_number"],
                        text=r["text"],
                        created_at=r["created_at"],
                    )
                )
        return DirectiveSet(patches=buckets["patch"], rules=buckets["rule"], lore=buckets["lore"])

    async def clear_directives(self, group_id: str) -> None:
        """Delete all directives for a group (used by ``@reset``)."""
        await self._conn.execute("DELETE FROM directives WHERE group_id = ?", (group_id,))
        await self._conn.commit()

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
        """Return the newest ``command_log_window`` command events, oldest-first."""
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
        """Return the newest ``command_log_window`` disclaimers, newest-first.

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

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

"""The connection lifecycle + schema bootstrap shared by the state sub-stores.

``Database`` owns one ``aiosqlite`` connection and exposes the focused sub-stores
(``directives``, ``commands``, ``disclaimers``, ``arming``, ``profiles``) as
attributes. Each sub-store owns exactly one table and contributes a ``SCHEMA``
constant the database runs on connect, so adding new state later is a new store
file plus one line here. ``HistoryStore`` is deliberately NOT part of this — it
keeps its own connection.
"""

from __future__ import annotations

from pathlib import Path

import aiosqlite

from signal_chatbot.state.arming import ArmingStore
from signal_chatbot.state.commands import CommandLog
from signal_chatbot.state.directives import DirectiveStore
from signal_chatbot.state.disclaimers import DisclaimerStore
from signal_chatbot.state.profiles import ProfileStore


class Database:
    """Owns the shared connection and the per-table sub-stores built on it."""

    def __init__(self, database_path: Path | str, *, command_log_window: int):
        self._path = Path(database_path)
        self._window = command_log_window
        self._db: aiosqlite.Connection | None = None
        self.directives: DirectiveStore
        self.commands: CommandLog
        self.disclaimers: DisclaimerStore
        self.arming: ArmingStore
        self.profiles: ProfileStore

    async def connect(self) -> None:
        """Open the database, build the sub-stores, and ensure every schema exists."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self._path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        self._db = conn

        self.directives = DirectiveStore(conn)
        self.commands = CommandLog(conn, window=self._window)
        self.disclaimers = DisclaimerStore(conn, window=self._window)
        self.arming = ArmingStore(conn)
        self.profiles = ProfileStore(conn)

        for store in (
            self.directives,
            self.commands,
            self.disclaimers,
            self.arming,
            self.profiles,
        ):
            await conn.executescript(store.SCHEMA)
        await conn.commit()

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

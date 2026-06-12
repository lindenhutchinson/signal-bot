"""SQLite-backed cache for Wikipedia lookups with per-entry expiry.

Keys are opaque request signatures (e.g. ``search:en:5:climate change`` or
``full:en:Mercury``); payloads are the response text. Eviction is lazy: an
expired row is treated as a miss and overwritten on the next fetch. The cache
lives in the same database file as the rest of the bot's state, mirroring the
``connect()``/``aclose()`` lifecycle of the other stores.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS wikipedia_cache (
    cache_key  TEXT    PRIMARY KEY,
    payload    TEXT    NOT NULL,
    expires_at INTEGER NOT NULL
);
"""


class WikipediaCache:
    """Async key→payload cache with TTL, backed by SQLite."""

    def __init__(
        self,
        database_path: Path | str,
        *,
        now: Callable[[], int] = lambda: int(time.time()),
    ):
        self._path = Path(database_path)
        self._now = now
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
            raise RuntimeError("WikipediaCache.connect() must be called first")
        return self._db

    async def get(self, key: str) -> str | None:
        """Return the cached payload for ``key``, or ``None`` if absent or expired."""
        cursor = await self._conn.execute(
            "SELECT payload, expires_at FROM wikipedia_cache WHERE cache_key = ?",
            (key,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        if row["expires_at"] <= self._now():
            return None
        return row["payload"]

    async def put(self, key: str, payload: str, *, ttl_seconds: int) -> None:
        """Store ``payload`` under ``key``, expiring ``ttl_seconds`` from now."""
        expires_at = self._now() + ttl_seconds
        await self._conn.execute(
            """
            INSERT INTO wikipedia_cache (cache_key, payload, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                payload = excluded.payload,
                expires_at = excluded.expires_at
            """,
            (key, payload, expires_at),
        )
        await self._conn.commit()

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

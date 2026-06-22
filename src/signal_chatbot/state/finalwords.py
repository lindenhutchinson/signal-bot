"""The per-group archive of every incarnation's final words.

Unlike every other piece of per-group state, this store is **never wiped**: not
by ``@reset``, not by ``@lobotomy``, not by a self-kill. It is the lineage of the
bots that held the chat before — each parting message preserved so the next
incarnation can be shown them (and humans can read them via ``@finalwords``).

An entry is recorded when a bot leaves words behind: the ``@reset`` farewell and a
self-kill's final words. A bare ``@lobotomy`` records nothing (no goodbye) but the
existing archive survives it untouched.

No *automatic* wipe ever touches it. It can only be cleared by an explicit human
``@finalwords clear`` command (:meth:`clear`).
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite


@dataclass(frozen=True, slots=True)
class FinalWords:
    """One incarnation's parting message and the name it died under."""

    name: str
    text: str
    created_at: int


class FinalWordsStore:
    """Persistence for the final words of past incarnations.

    The archive outlives every *automatic* wipe (``@reset``, ``@lobotomy``, self-kill);
    only an explicit ``@finalwords clear`` (:meth:`clear`) empties it.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS final_words (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id   TEXT    NOT NULL,
        name       TEXT    NOT NULL,
        text       TEXT    NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_final_words_group ON final_words (group_id, id);
    """

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def add(self, group_id: str, *, name: str, text: str, created_at: int) -> None:
        """Record one incarnation's final words for a group."""
        await self._conn.execute(
            "INSERT INTO final_words (group_id, name, text, created_at) VALUES (?, ?, ?, ?)",
            (group_id, name, text, created_at),
        )
        await self._conn.commit()

    async def all(self, group_id: str) -> list[FinalWords]:
        """Return every recorded farewell for a group, oldest-first (a lineage)."""
        cursor = await self._conn.execute(
            "SELECT name, text, created_at FROM final_words WHERE group_id = ? ORDER BY id ASC",
            (group_id,),
        )
        rows = await cursor.fetchall()
        return [FinalWords(r["name"], r["text"], r["created_at"]) for r in rows]

    async def clear(self, group_id: str) -> int:
        """Erase a group's archived final words. Returns how many entries were removed.

        Only ever called by the explicit ``@finalwords clear`` command — no wipe path
        touches this table.
        """
        cursor = await self._conn.execute(
            "DELETE FROM final_words WHERE group_id = ?", (group_id,)
        )
        await self._conn.commit()
        return cursor.rowcount

"""Per-sender profiles: the notes the bot keeps about people in a group.

Notes are stored one per row, keyed by **subject name** (the bot reasons in names,
history shows names, and ``@forget <name>`` matches on the same key). They are
cleared on any slate wipe (``@reset``/``@lobotomy``/self-death).
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite


@dataclass(frozen=True, slots=True)
class Profile:
    """Everything the bot remembers about one subject, notes oldest-first."""

    subject: str
    notes: list[str]


class ProfileStore:
    """Persistence for the per-subject notes the bot keeps in a group."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS profile_notes (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id   TEXT    NOT NULL,
        subject    TEXT    NOT NULL,
        note       TEXT    NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_profile_notes_group ON profile_notes (group_id, id);
    """

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def add_note(self, group_id: str, *, subject: str, note: str, created_at: int) -> None:
        """Append a note about ``subject`` for a group."""
        await self._conn.execute(
            "INSERT INTO profile_notes (group_id, subject, note, created_at) VALUES (?, ?, ?, ?)",
            (group_id, subject, note, created_at),
        )
        await self._conn.commit()

    async def all(self, group_id: str) -> list[Profile]:
        """Return one :class:`Profile` per subject for a group.

        Subjects are ordered by when each was first seen; each subject's notes are
        oldest-first. Aggregation is by exact subject string.
        """
        cursor = await self._conn.execute(
            "SELECT subject, note FROM profile_notes WHERE group_id = ? ORDER BY id ASC",
            (group_id,),
        )
        rows = await cursor.fetchall()
        by_subject: dict[str, list[str]] = {}
        for r in rows:
            by_subject.setdefault(r["subject"], []).append(r["note"])
        return [Profile(subject=subject, notes=notes) for subject, notes in by_subject.items()]

    async def clear(self, group_id: str) -> None:
        """Delete every subject's notes for a group (on any slate wipe)."""
        await self._conn.execute("DELETE FROM profile_notes WHERE group_id = ?", (group_id,))
        await self._conn.commit()

    async def forget(self, group_id: str, subject: str) -> bool:
        """Delete one subject's notes; return whether any rows matched."""
        cursor = await self._conn.execute(
            "DELETE FROM profile_notes WHERE group_id = ? AND subject = ?",
            (group_id, subject),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

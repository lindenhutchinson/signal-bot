"""Per-group directives: rules and lore injected into the system prompt.

Directives are the user- (or bot-) authored text that shapes the persona. They
come in two kinds — ``rule`` (hard constraints) and ``lore`` (treated-as-true
facts/history) — each surfaced as its own labelled prompt section.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

_KINDS = ("rule", "lore")


@dataclass(frozen=True, slots=True)
class Directive:
    """One rule/lore entry with its provenance."""

    kind: str
    author_name: str
    author_number: str
    text: str
    created_at: int


@dataclass(frozen=True, slots=True)
class DirectiveSet:
    """A group's active directives, split by kind, each oldest-first."""

    rules: list[Directive]
    lore: list[Directive]


class DirectiveStore:
    """Persistence for a group's rules and lore."""

    SCHEMA = """
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
    """

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

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
        """Append a directive of ``kind`` (rule/lore) for a group."""
        await self._conn.execute(
            "INSERT INTO directives (group_id, kind, author_name, author_number, text, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (group_id, kind, author_name, author_number, text, created_at),
        )
        await self._conn.commit()

    async def directives(self, group_id: str) -> DirectiveSet:
        """Return all directives for a group, bucketed by kind, oldest-first.

        Rows of any other (legacy) kind — e.g. the removed ``patch`` — are simply
        not surfaced; no migration is needed.
        """
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
        return DirectiveSet(rules=buckets["rule"], lore=buckets["lore"])

    async def clear_directives(self, group_id: str) -> None:
        """Delete all directives for a group (used by ``@reset``/``@lobotomy``)."""
        await self._conn.execute("DELETE FROM directives WHERE group_id = ?", (group_id,))
        await self._conn.commit()

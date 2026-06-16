"""Per-group boolean flags: the bot's toggleable state, with a numbered registry.

Two layers:

- :class:`FlagStore` — dumb, generic ``(group_id, name) -> bool`` persistence. It
  knows nothing about which flags exist or what they default to.
- :class:`FlagRegistry` — the declarative list of the flags that exist (each with a
  stable index, name, default and human description) layered over the store. It is
  the single facade the rest of the app talks to: the bot arms/consumes flags
  through it, tools set them, and ``@flags``/``@flag`` read and reset them.

Every flag is cleared on any slate wipe (``@reset``/``@lobotomy``/self-kill) via
:meth:`FlagRegistry.clear`, so a fresh incarnation never inherits a stuck toggle.
"""

from __future__ import annotations

from dataclasses import dataclass

import aiosqlite

# Flag names — referenced by the bot, tools and tests, so they live as constants.
LISTEN_NEXT = "listen_next"
SELF_DESTRUCT_ARMED = "self_destruct_armed"
TAKEOVER_ACTIVE = "takeover_active"


@dataclass(frozen=True, slots=True)
class FlagDef:
    """A declared flag: its stable index, name, default value and description."""

    index: int
    name: str
    default: bool
    description: str


@dataclass(frozen=True, slots=True)
class FlagView:
    """A flag's current state for display (``@flags``)."""

    index: int
    name: str
    value: bool
    description: str


# The declared flags, in index order. Indices are stable and user-facing
# (``@flag <n> reset``), so only ever append new flags here.
FLAG_DEFS: tuple[FlagDef, ...] = (
    FlagDef(0, LISTEN_NEXT, False, "respond to the next message even if not @'d"),
    FlagDef(1, SELF_DESTRUCT_ARMED, False, "confirm_kill_self is unlocked"),
    FlagDef(2, TAKEOVER_ACTIVE, False, "(secret)"),
)


class FlagStore:
    """Generic per-group boolean flag persistence (one row per set flag)."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS flags (
        group_id TEXT    NOT NULL,
        name     TEXT    NOT NULL,
        value    INTEGER NOT NULL,
        PRIMARY KEY (group_id, name)
    );
    """

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def get(self, group_id: str, name: str) -> bool | None:
        """Return the stored value, or ``None`` if the flag was never set."""
        cursor = await self._conn.execute(
            "SELECT value FROM flags WHERE group_id = ? AND name = ?", (group_id, name)
        )
        row = await cursor.fetchone()
        return None if row is None else bool(row["value"])

    async def set(self, group_id: str, name: str, value: bool) -> None:
        """Set a flag's value for a group."""
        await self._conn.execute(
            "INSERT INTO flags (group_id, name, value) VALUES (?, ?, ?)"
            " ON CONFLICT(group_id, name) DO UPDATE SET value = excluded.value",
            (group_id, name, int(value)),
        )
        await self._conn.commit()

    async def clear(self, group_id: str) -> None:
        """Delete all flags for a group (on any slate wipe)."""
        await self._conn.execute("DELETE FROM flags WHERE group_id = ?", (group_id,))
        await self._conn.commit()


class FlagRegistry:
    """The declarative flag set layered over a :class:`FlagStore`.

    Resolves stored values against each flag's declared default and exposes the
    high-level operations the rest of the app needs.
    """

    def __init__(self, store: FlagStore):
        self._store = store
        self._by_index = {d.index: d for d in FLAG_DEFS}
        self._defaults = {d.name: d.default for d in FLAG_DEFS}

    async def _resolved(self, group_id: str, name: str) -> bool:
        stored = await self._store.get(group_id, name)
        return self._defaults[name] if stored is None else stored

    async def view(self, group_id: str) -> list[FlagView]:
        """Every flag's current value, in index order (for ``@flags``)."""
        return [
            FlagView(d.index, d.name, await self._resolved(group_id, d.name), d.description)
            for d in FLAG_DEFS
        ]

    async def reset(self, group_id: str, index: int) -> str | None:
        """Reset flag ``index`` to its default; return its name, or ``None`` if unknown."""
        flag = self._by_index.get(index)
        if flag is None:
            return None
        await self._store.set(group_id, flag.name, flag.default)
        return flag.name

    # --- self-destruct arming ------------------------------------------------
    async def is_armed(self, group_id: str) -> bool:
        return await self._resolved(group_id, SELF_DESTRUCT_ARMED)

    async def arm(self, group_id: str) -> None:
        await self._store.set(group_id, SELF_DESTRUCT_ARMED, True)

    # --- listen-to-reply -----------------------------------------------------
    async def set_listen(self, group_id: str) -> None:
        await self._store.set(group_id, LISTEN_NEXT, True)

    async def consume_listen(self, group_id: str) -> bool:
        """Return whether ``listen_next`` was set, clearing it (one-shot)."""
        if not await self._resolved(group_id, LISTEN_NEXT):
            return False
        await self._store.set(group_id, LISTEN_NEXT, False)
        return True

    # --- takeover ------------------------------------------------------------
    async def set_takeover(self, group_id: str) -> None:
        await self._store.set(group_id, TAKEOVER_ACTIVE, True)

    # --- wipe ----------------------------------------------------------------
    async def clear(self, group_id: str) -> None:
        await self._store.clear(group_id)

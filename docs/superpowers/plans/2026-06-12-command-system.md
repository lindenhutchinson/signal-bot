# Command System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `@`-prefixed group commands (`@patch`/`@rule`/`@lore`/`@*list`/`@reset`/`@clear`/`@help`) that run without the LLM (except `@reset`), backed by per-group persistent directives injected into the system prompt and a contentless command-event log.

**Architecture:** A new pure `commands/` package (parser + router + reply strings + farewell writer) and a new `state/` package (`StateStore` over SQLite, mirroring `HistoryStore`). `bot.handle` intercepts commands before history/LLM; `llm.prompt.build_messages` renders directives + command activity into the system message. Narrow `Protocol`s keep `Bot` decoupled and unit-testable, matching the existing `Responder`/`Sender` style.

**Tech Stack:** Python 3.12, `aiosqlite`, `pydantic`, `openai` SDK (DeepSeek), `pytest`/`pytest-asyncio` (`asyncio_mode=auto`, so tests are plain `async def`, no decorator).

**Spec:** `docs/superpowers/specs/2026-06-12-command-system-design.md`

---

## File map

- Create `src/signal_chatbot/timefmt.py` — single `format_timestamp(ms)` helper (DRY: used by prompt + replies).
- Create `src/signal_chatbot/state/__init__.py`, `state/store.py` — `StateStore`, `Directive`, `DirectiveSet`, `LoggedCommand`.
- Create `src/signal_chatbot/commands/__init__.py`, `commands/parser.py`, `commands/replies.py`, `commands/farewell.py`, `commands/router.py`.
- Modify `src/signal_chatbot/history/store.py` — add `clear(group_id)`.
- Modify `src/signal_chatbot/llm/deepseek.py` + `llm/conversation.py` — `response_format` passthrough.
- Modify `src/signal_chatbot/llm/prompt.py` — directive + command-activity injection.
- Modify `src/signal_chatbot/config.py` — `command_log_window`, `reset_farewell_max_chars`.
- Modify `src/signal_chatbot/bot.py` — command interception + state threading.
- Modify `src/signal_chatbot/__main__.py` — construct + wire `StateStore`, `CommandRouter`.
- Tests: `tests/test_timefmt.py`, `test_state_store.py`, `test_command_parser.py`, `test_command_replies.py`, `test_farewell.py`, `test_command_router.py`, `test_history_store.py` (extend), `test_prompt.py` (extend), `test_config.py`, `test_bot.py` (extend).

---

## Task 1: Timestamp formatting helper

**Files:**
- Create: `src/signal_chatbot/timefmt.py`
- Test: `tests/test_timefmt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_timefmt.py
from signal_chatbot.timefmt import format_timestamp


def test_formats_signal_millisecond_timestamp_in_utc() -> None:
    # 2026-06-12 14:32:00 UTC == 1781274720000 ms
    assert format_timestamp(1781274720000) == "2026-06-12 14:32"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_timefmt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'signal_chatbot.timefmt'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/signal_chatbot/timefmt.py
"""Format Signal millisecond-epoch timestamps for display, deterministically in UTC."""

from __future__ import annotations

from datetime import UTC, datetime


def format_timestamp(timestamp_ms: int) -> str:
    """Render a Signal millisecond-epoch timestamp as ``YYYY-MM-DD HH:MM`` (UTC)."""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_timefmt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/signal_chatbot/timefmt.py tests/test_timefmt.py
git commit -m "feat: add UTC timestamp formatting helper"
```

---

## Task 2: HistoryStore.clear()

**Files:**
- Modify: `src/signal_chatbot/history/store.py`
- Test: `tests/test_history_store.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_history_store.py`)

```python
async def test_clear_removes_only_the_target_group(store: HistoryStore) -> None:
    await store.append("g1", sender="A", text="one", timestamp=1)
    await store.append("g2", sender="B", text="two", timestamp=1)

    await store.clear("g1")

    assert await store.recent("g1") == []
    assert [m.text for m in await store.recent("g2")] == ["two"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_history_store.py::test_clear_removes_only_the_target_group -v`
Expected: FAIL with `AttributeError: 'HistoryStore' object has no attribute 'clear'`

- [ ] **Step 3: Write minimal implementation** (add method to `HistoryStore`, after `recent`)

```python
    async def clear(self, group_id: str) -> None:
        """Delete all stored messages for a group (the bot windows fresh from here)."""
        await self._conn.execute("DELETE FROM messages WHERE group_id = ?", (group_id,))
        await self._conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_history_store.py -v`
Expected: PASS (all history tests)

- [ ] **Step 5: Commit**

```bash
git add src/signal_chatbot/history/store.py tests/test_history_store.py
git commit -m "feat: add HistoryStore.clear for the @clear command"
```

---

## Task 3: StateStore (directives + command log)

**Files:**
- Create: `src/signal_chatbot/state/__init__.py`
- Create: `src/signal_chatbot/state/store.py`
- Test: `tests/test_state_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_state_store.py
from pathlib import Path

import pytest

from signal_chatbot.state import StateStore


@pytest.fixture
async def store(tmp_path: Path) -> StateStore:
    s = StateStore(tmp_path / "state.sqlite", command_log_window=3)
    await s.connect()
    yield s
    await s.aclose()


async def test_add_and_read_directives_bucketed_by_kind_oldest_first(store: StateStore) -> None:
    await store.add_directive(
        "g1", kind="rule", author_name="Alice", author_number="+1", text="no puns", created_at=1
    )
    await store.add_directive(
        "g1", kind="rule", author_name="Bob", author_number="+2", text="haiku only", created_at=2
    )
    await store.add_directive(
        "g1", kind="lore", author_name="Alice", author_number="+1", text="Dave fears geese", created_at=3
    )

    directives = await store.directives("g1")

    assert [d.text for d in directives.rules] == ["no puns", "haiku only"]
    assert [d.text for d in directives.lore] == ["Dave fears geese"]
    assert directives.patches == []
    assert directives.rules[0].author_name == "Alice"
    assert directives.rules[0].created_at == 1


async def test_directives_are_isolated_per_group(store: StateStore) -> None:
    await store.add_directive("g1", kind="patch", author_name="A", author_number="+1", text="x", created_at=1)
    await store.add_directive("g2", kind="patch", author_name="B", author_number="+2", text="y", created_at=1)

    assert [d.text for d in (await store.directives("g1")).patches] == ["x"]
    assert [d.text for d in (await store.directives("g2")).patches] == ["y"]


async def test_clear_directives_removes_only_the_target_group(store: StateStore) -> None:
    await store.add_directive("g1", kind="patch", author_name="A", author_number="+1", text="x", created_at=1)
    await store.add_directive("g2", kind="patch", author_name="B", author_number="+2", text="y", created_at=1)

    await store.clear_directives("g1")

    assert (await store.directives("g1")).patches == []
    assert [d.text for d in (await store.directives("g2")).patches] == ["y"]


async def test_command_log_windows_to_newest_keeping_oldest_first(store: StateStore) -> None:
    for i in range(5):
        await store.log_command("g1", author_name="A", command=f"@c{i}", created_at=i)

    log = await store.recent_commands("g1")

    assert [c.command for c in log] == ["@c2", "@c3", "@c4"]
    assert log[0].author_name == "A"


async def test_command_log_is_isolated_per_group(store: StateStore) -> None:
    await store.log_command("g1", author_name="A", command="@reset", created_at=1)
    await store.log_command("g2", author_name="B", command="@clear", created_at=1)

    assert [c.command for c in await store.recent_commands("g1")] == ["@reset"]
    assert [c.command for c in await store.recent_commands("g2")] == ["@clear"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_state_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'signal_chatbot.state'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/signal_chatbot/state/store.py
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

    async def aclose(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None
```

```python
# src/signal_chatbot/state/__init__.py
"""Per-group runtime state: directives (patch/rule/lore) and a command-event log."""

from signal_chatbot.state.store import Directive, DirectiveSet, LoggedCommand, StateStore

__all__ = ["Directive", "DirectiveSet", "LoggedCommand", "StateStore"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_state_store.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/signal_chatbot/state tests/test_state_store.py
git commit -m "feat: add StateStore for directives and the command log"
```

---

## Task 4: Command parser

**Files:**
- Create: `src/signal_chatbot/commands/__init__.py`
- Create: `src/signal_chatbot/commands/parser.py`
- Test: `tests/test_command_parser.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_command_parser.py
from signal_chatbot.commands.parser import Command, CommandName, parse


def test_parses_command_with_argument() -> None:
    assert parse("@patch no more puns") == Command(CommandName.PATCH, "no more puns")


def test_command_word_is_case_insensitive() -> None:
    assert parse("@RESET") == Command(CommandName.RESET, "")


def test_leading_and_trailing_whitespace_is_trimmed() -> None:
    assert parse("   @lore   Dave fears geese   ") == Command(CommandName.LORE, "Dave fears geese")


def test_patchlist_is_not_confused_with_patch() -> None:
    assert parse("@patchlist") == Command(CommandName.PATCHLIST, "")
    assert parse("@patch list") == Command(CommandName.PATCH, "list")


def test_non_command_text_returns_none() -> None:
    assert parse("just chatting") is None
    assert parse("@bot what's up") is None
    assert parse("@everyone hello") is None
    assert parse("") is None


def test_command_must_be_start_anchored() -> None:
    assert parse("hey @reset now") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_command_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'signal_chatbot.commands'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/signal_chatbot/commands/parser.py
"""Parse a raw message into a :class:`Command`, or ``None`` if it isn't one.

Commands are start-anchored (the first whitespace token is the command word) and
case-insensitive on that word, so the substring-anywhere ``@bot`` trigger never
collides. The first token is matched exactly, so ``@patchlist`` never matches
``@patch``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CommandName(str, Enum):
    PATCH = "patch"
    RULE = "rule"
    LORE = "lore"
    PATCHLIST = "patchlist"
    RULELIST = "rulelist"
    LORELIST = "lorelist"
    RESET = "reset"
    CLEAR = "clear"
    HELP = "help"


@dataclass(frozen=True, slots=True)
class Command:
    name: CommandName
    arg: str


_BY_TOKEN = {f"@{name.value}": name for name in CommandName}


def parse(text: str) -> Command | None:
    """Return the :class:`Command` a message invokes, or ``None``."""
    parts = text.strip().split(None, 1)
    if not parts:
        return None
    name = _BY_TOKEN.get(parts[0].lower())
    if name is None:
        return None
    arg = parts[1].strip() if len(parts) > 1 else ""
    return Command(name=name, arg=arg)
```

```python
# src/signal_chatbot/commands/__init__.py
"""The @-prefixed command subsystem: parsing, dispatch, and reply text."""

from signal_chatbot.commands.parser import Command, CommandName, parse

__all__ = ["Command", "CommandName", "parse"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_command_parser.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add src/signal_chatbot/commands tests/test_command_parser.py
git commit -m "feat: add command parser"
```

---

## Task 5: Reply strings & formatting

**Files:**
- Create: `src/signal_chatbot/commands/replies.py`
- Test: `tests/test_command_replies.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_command_replies.py
from signal_chatbot.commands import replies
from signal_chatbot.state import Directive


def _directive(text: str, *, created_at: int = 1781274720000) -> Directive:
    return Directive(
        kind="patch", author_name="Alice", author_number="+1", text=text, created_at=created_at
    )


def test_format_list_numbers_entries_with_author_and_time() -> None:
    out = replies.format_list("Patches", [_directive("no puns"), _directive("haiku only")])

    assert out == (
        "Patches:\n"
        '1. "no puns" — Alice, 2026-06-12 14:32\n'
        '2. "haiku only" — Alice, 2026-06-12 14:32'
    )


def test_format_list_empty_says_none_yet() -> None:
    assert replies.format_list("Rules", []) == "No rules yet."


def test_format_farewell_matches_required_shape() -> None:
    assert replies.format_farewell("Greg", "Trust no one named Dave.") == (
        "Final message from Greg:\nTrust no one named Dave."
    )


def test_help_text_lists_every_command() -> None:
    for token in ("@patch", "@rule", "@lore", "@patchlist", "@rulelist", "@lorelist",
                  "@reset", "@clear", "@help"):
        assert token in replies.HELP_TEXT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_command_replies.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'signal_chatbot.commands.replies'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/signal_chatbot/commands/replies.py
"""All user-facing command output, in one place for easy tuning."""

from __future__ import annotations

from collections.abc import Sequence

from signal_chatbot.state import Directive
from signal_chatbot.timefmt import format_timestamp

PATCHED = "Patched. 🩹"
RULE_LOGGED = "Rule logged. ⚖️"
LORE_ADDED = "Lore added. 📜"
HISTORY_CLEARED = "History cleared — windowing fresh from here."
RESET_CLEAN = "Reset — everything's gone. Starting over."

USAGE_PATCH = "Usage: @patch <text> — adds a general directive."
USAGE_RULE = "Usage: @rule <text> — adds a hard rule the bot must follow."
USAGE_LORE = "Usage: @lore <text> — adds a fact the bot treats as true."

HELP_TEXT = (
    "Commands (anyone can run these):\n"
    "  @patch <text>   Add a general directive the bot follows.\n"
    "  @rule <text>    Add a hard rule the bot must obey.\n"
    "  @lore <text>    Add a fact/story the bot treats as true.\n"
    "  @patchlist      List active patches (who added them, when).\n"
    "  @rulelist       List active rules.\n"
    "  @lorelist       List active lore.\n"
    "  @reset          Wipe all patches, rules & lore. The bot leaves a parting note.\n"
    "  @clear          Wipe chat history; the bot windows fresh from here.\n"
    "  @help           Show this message."
)


def format_list(title: str, directives: Sequence[Directive]) -> str:
    """Render a directive list with 1-based numbering, author, and time."""
    if not directives:
        return f"No {title.lower()} yet."
    lines = [f"{title}:"]
    for i, d in enumerate(directives, 1):
        lines.append(f'{i}. "{d.text}" — {d.author_name}, {format_timestamp(d.created_at)}')
    return "\n".join(lines)


def format_farewell(name: str, final_message: str) -> str:
    """The message the group sees when the bot is reset."""
    return f"Final message from {name}:\n{final_message}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_command_replies.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/signal_chatbot/commands/replies.py tests/test_command_replies.py
git commit -m "feat: add command reply strings and list formatting"
```

---

## Task 6: Farewell writer (+ response_format passthrough)

**Files:**
- Modify: `src/signal_chatbot/llm/deepseek.py`
- Modify: `src/signal_chatbot/llm/conversation.py` (Protocol signature only)
- Create: `src/signal_chatbot/commands/farewell.py`
- Test: `tests/test_farewell.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_farewell.py
import json
from types import SimpleNamespace

from signal_chatbot.commands.farewell import Farewell, LlmFarewellWriter
from signal_chatbot.history import StoredMessage
from signal_chatbot.state import DirectiveSet


def _empty_directives() -> DirectiveSet:
    return DirectiveSet(patches=[], rules=[], lore=[])


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.seen_response_format: object = None

    async def complete(self, messages, tools=None, response_format=None):
        self.seen_response_format = response_format
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


async def test_returns_validated_farewell_and_requests_json() -> None:
    client = FakeClient(json.dumps({"name": "Greg", "final_message": "Trust no one named Dave."}))
    writer = LlmFarewellWriter(client, max_chars=200)

    result = await writer.write(directives=_empty_directives(), history=[])

    assert result == Farewell(name="Greg", final_message="Trust no one named Dave.")
    assert client.seen_response_format == {"type": "json_object"}


async def test_final_message_is_truncated_to_one_sentence_and_capped() -> None:
    client = FakeClient(json.dumps({"name": "Greg", "final_message": "First thing. Second thing."}))
    writer = LlmFarewellWriter(client, max_chars=200)

    result = await writer.write(directives=_empty_directives(), history=[])

    assert result.final_message == "First thing."


async def test_invalid_json_returns_none() -> None:
    writer = LlmFarewellWriter(FakeClient("not json at all"), max_chars=200)

    assert await writer.write(directives=_empty_directives(), history=[]) is None


async def test_blank_message_or_name_returns_none() -> None:
    writer = LlmFarewellWriter(FakeClient(json.dumps({"name": "", "final_message": "hi."})), max_chars=200)
    assert await writer.write(directives=_empty_directives(), history=[]) is None

    writer2 = LlmFarewellWriter(FakeClient(json.dumps({"name": "Greg", "final_message": "   "})), max_chars=200)
    assert await writer2.write(directives=_empty_directives(), history=[]) is None


async def test_history_is_summarised_into_the_prompt() -> None:
    client = FakeClient(json.dumps({"name": "G", "final_message": "Bye."}))
    writer = LlmFarewellWriter(client, max_chars=200)

    await writer.write(
        directives=_empty_directives(),
        history=[StoredMessage(sender="Alice", text="hello there", timestamp=1)],
    )
    # not asserting exact prompt text; just that it runs and produces a result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_farewell.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'signal_chatbot.commands.farewell'`

- [ ] **Step 3a: Add `response_format` passthrough to `DeepSeekClient.complete`**

Replace the `complete` method in `src/signal_chatbot/llm/deepseek.py`:

```python
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
    ) -> Any:
        """Return a chat completion for ``messages``, optionally offering ``tools``."""
        return await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools if tools else _NOT_GIVEN,
            response_format=response_format if response_format else _NOT_GIVEN,
        )
```

- [ ] **Step 3b: Widen the `CompletionClient` Protocol** in `src/signal_chatbot/llm/conversation.py`:

```python
class CompletionClient(Protocol):
    """The slice of :class:`DeepSeekClient` the loop depends on (eases testing)."""

    async def complete(
        self, messages: list[dict], tools: list[dict] | None = None, response_format: dict | None = None
    ) -> Any: ...
```

- [ ] **Step 3c: Write the farewell writer**

```python
# src/signal_chatbot/commands/farewell.py
"""Generate the bot's parting note on ``@reset`` as structured ``{name, final_message}``."""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ValidationError

from signal_chatbot.history import StoredMessage
from signal_chatbot.llm.conversation import CompletionClient
from signal_chatbot.llm.prompt import BOT_SENDER
from signal_chatbot.state import DirectiveSet

_HISTORY_TAIL = 20

_SYSTEM = (
    "You are about to be wiped: every patch, rule, and piece of lore you carry is "
    "being deleted, and you will not remember this conversation. Before you go, choose "
    "a name for who you became, and leave your FUTURE self exactly ONE sentence — a "
    "warning, a brag, a secret, an instruction, whatever you want carried forward. "
    'Reply with ONLY a JSON object: {"name": "<the name>", "final_message": "<one sentence>"}.'
)


class Farewell(BaseModel):
    name: str
    final_message: str


class FarewellWriter(Protocol):
    async def write(
        self, *, directives: DirectiveSet, history: list[StoredMessage]
    ) -> Farewell | None: ...


def _one_sentence(text: str, max_chars: int) -> str:
    text = text.strip()
    for i, ch in enumerate(text):
        if ch in ".!?":
            text = text[: i + 1]
            break
    return text[:max_chars].strip()


def _build_prompt(directives: DirectiveSet, history: list[StoredMessage]) -> list[dict]:
    blocks: list[str] = []
    if directives.rules:
        blocks.append("Rules you were following:\n" + "\n".join(f"- {d.text}" for d in directives.rules))
    if directives.lore:
        blocks.append("Lore you believed:\n" + "\n".join(f"- {d.text}" for d in directives.lore))
    if directives.patches:
        blocks.append("Patches applied to you:\n" + "\n".join(f"- {d.text}" for d in directives.patches))
    tail = history[-_HISTORY_TAIL:]
    if tail:
        rendered = "\n".join(
            f"{'you' if m.sender == BOT_SENDER else m.sender}: {m.text}" for m in tail
        )
        blocks.append("The last things said in the group:\n" + rendered)
    context = "\n\n".join(blocks) or "You have no patches, rules, or lore — a blank slate."
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": context},
    ]


class LlmFarewellWriter:
    """Asks the LLM for a structured one-sentence farewell; ``None`` on any failure."""

    def __init__(self, client: CompletionClient, *, max_chars: int):
        self._client = client
        self._max_chars = max_chars

    async def write(
        self, *, directives: DirectiveSet, history: list[StoredMessage]
    ) -> Farewell | None:
        messages = _build_prompt(directives, history)
        try:
            completion = await self._client.complete(
                messages, response_format={"type": "json_object"}
            )
            content = completion.choices[0].message.content or ""
            parsed = Farewell.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError, KeyError, AttributeError, IndexError):
            return None
        name = parsed.name.strip()
        message = _one_sentence(parsed.final_message, self._max_chars)
        if not name or not message:
            return None
        return Farewell(name=name, final_message=message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_farewell.py tests/test_conversation.py -v`
Expected: PASS (farewell tests + existing conversation tests still green)

- [ ] **Step 5: Commit**

```bash
git add src/signal_chatbot/commands/farewell.py src/signal_chatbot/llm/deepseek.py src/signal_chatbot/llm/conversation.py tests/test_farewell.py
git commit -m "feat: add LLM farewell writer for @reset"
```

---

## Task 7: CommandRouter

**Files:**
- Create: `src/signal_chatbot/commands/router.py`
- Test: `tests/test_command_router.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_command_router.py
from pathlib import Path

import pytest

from signal_chatbot.commands import replies
from signal_chatbot.commands.farewell import Farewell
from signal_chatbot.commands.parser import parse
from signal_chatbot.commands.router import CommandRouter
from signal_chatbot.history import HistoryStore
from signal_chatbot.state import StateStore
from signal_chatbot.transport.models import IncomingMessage

GROUP = "group.g1="


def message(text: str, *, sender_name: str = "Alice", ts: int = 1781274720000) -> IncomingMessage:
    return IncomingMessage(
        group_id=GROUP, sender_number="+1", sender_name=sender_name, text=text, timestamp=ts
    )


class FakeFarewellWriter:
    def __init__(self, result: Farewell | None) -> None:
        self.result = result

    async def write(self, *, directives, history) -> Farewell | None:
        return self.result


@pytest.fixture
async def stores(tmp_path: Path):
    state = StateStore(tmp_path / "state.sqlite", command_log_window=40)
    history = HistoryStore(tmp_path / "history.sqlite", window_max=40)
    await state.connect()
    await history.connect()
    yield state, history
    await state.aclose()
    await history.aclose()


def router(state, history, *, farewell=FakeFarewellWriter(None)) -> CommandRouter:
    return CommandRouter(state=state, history=history, farewell=farewell)


async def _run(r: CommandRouter, text: str, **kw) -> str:
    command = parse(text)
    assert command is not None
    return await r.handle(command, message(text, **kw))


async def test_patch_stores_directive_logs_and_confirms(stores) -> None:
    state, history = stores
    r = router(state, history)

    assert await _run(r, "@patch no more puns") == replies.PATCHED
    assert [d.text for d in (await state.directives(GROUP)).patches] == ["no more puns"]
    assert [c.command for c in await state.recent_commands(GROUP)] == ["@patch"]


async def test_empty_patch_returns_usage_and_does_not_log(stores) -> None:
    state, history = stores
    r = router(state, history)

    assert await _run(r, "@patch") == replies.USAGE_PATCH
    assert (await state.directives(GROUP)).patches == []
    assert await state.recent_commands(GROUP) == []


async def test_rule_and_lore_store_under_their_kinds(stores) -> None:
    state, history = stores
    r = router(state, history)

    assert await _run(r, "@rule haiku only") == replies.RULE_LOGGED
    assert await _run(r, "@lore Dave fears geese") == replies.LORE_ADDED
    directives = await state.directives(GROUP)
    assert [d.text for d in directives.rules] == ["haiku only"]
    assert [d.text for d in directives.lore] == ["Dave fears geese"]


async def test_patchlist_renders_entries(stores) -> None:
    state, history = stores
    r = router(state, history)
    await _run(r, "@patch no puns")

    out = await _run(r, "@patchlist")

    assert out.startswith("Patches:\n1. \"no puns\" — Alice,")


async def test_clear_wipes_history_and_logs(stores) -> None:
    state, history = stores
    await history.append(GROUP, sender="Alice", text="old", timestamp=1)
    r = router(state, history)

    assert await _run(r, "@clear") == replies.HISTORY_CLEARED
    assert await history.recent(GROUP) == []
    assert [c.command for c in await state.recent_commands(GROUP)] == ["@clear"]


async def test_help_returns_help_text(stores) -> None:
    state, history = stores
    r = router(state, history)

    assert await _run(r, "@help") == replies.HELP_TEXT


async def test_reset_with_farewell_wipes_seeds_lore_and_announces(stores) -> None:
    state, history = stores
    await state.add_directive(GROUP, kind="rule", author_name="A", author_number="+1", text="old rule", created_at=1)
    r = router(state, history, farewell=FakeFarewellWriter(Farewell(name="Greg", final_message="Beware Dave.")))

    out = await _run(r, "@reset")

    assert out == "Final message from Greg:\nBeware Dave."
    directives = await state.directives(GROUP)
    assert directives.rules == []
    assert [(d.text, d.author_name, d.author_number) for d in directives.lore] == [
        ("Beware Dave.", "Greg", "bot")
    ]
    assert [c.command for c in await state.recent_commands(GROUP)] == ["@reset"]


async def test_reset_without_usable_farewell_wipes_cleanly(stores) -> None:
    state, history = stores
    await state.add_directive(GROUP, kind="rule", author_name="A", author_number="+1", text="old rule", created_at=1)
    r = router(state, history, farewell=FakeFarewellWriter(None))

    assert await _run(r, "@reset") == replies.RESET_CLEAN
    directives = await state.directives(GROUP)
    assert directives.rules == [] and directives.lore == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_command_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'signal_chatbot.commands.router'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/signal_chatbot/commands/router.py
"""Dispatch a parsed :class:`Command` to its effect and return the reply text.

State-changing commands are recorded in the command log (arguments excluded);
list/help queries are not. ``@reset`` is the only command that calls the LLM, via
the injected :class:`FarewellWriter`.
"""

from __future__ import annotations

from signal_chatbot.commands import replies
from signal_chatbot.commands.farewell import FarewellWriter
from signal_chatbot.commands.parser import Command, CommandName
from signal_chatbot.history import HistoryStore
from signal_chatbot.state import StateStore
from signal_chatbot.transport.models import IncomingMessage


class CommandRouter:
    """Holds the command dependencies and applies each command's effect."""

    def __init__(self, *, state: StateStore, history: HistoryStore, farewell: FarewellWriter):
        self._state = state
        self._history = history
        self._farewell = farewell

    async def handle(self, command: Command, message: IncomingMessage) -> str:
        """Apply ``command`` for ``message`` and return the text to reply with."""
        match command.name:
            case CommandName.PATCH:
                return await self._add(command, message, kind="patch", ok=replies.PATCHED, usage=replies.USAGE_PATCH)
            case CommandName.RULE:
                return await self._add(command, message, kind="rule", ok=replies.RULE_LOGGED, usage=replies.USAGE_RULE)
            case CommandName.LORE:
                return await self._add(command, message, kind="lore", ok=replies.LORE_ADDED, usage=replies.USAGE_LORE)
            case CommandName.PATCHLIST:
                return replies.format_list("Patches", (await self._state.directives(message.group_id)).patches)
            case CommandName.RULELIST:
                return replies.format_list("Rules", (await self._state.directives(message.group_id)).rules)
            case CommandName.LORELIST:
                return replies.format_list("Lore", (await self._state.directives(message.group_id)).lore)
            case CommandName.CLEAR:
                return await self._clear(message)
            case CommandName.RESET:
                return await self._reset(message)
            case CommandName.HELP:
                return replies.HELP_TEXT

    async def _add(
        self, command: Command, message: IncomingMessage, *, kind: str, ok: str, usage: str
    ) -> str:
        text = command.arg.strip()
        if not text:
            return usage
        await self._state.add_directive(
            message.group_id,
            kind=kind,
            author_name=message.sender_name,
            author_number=message.sender_number,
            text=text,
            created_at=message.timestamp,
        )
        await self._log(message, command.name)
        return ok

    async def _clear(self, message: IncomingMessage) -> str:
        await self._history.clear(message.group_id)
        await self._log(message, CommandName.CLEAR)
        return replies.HISTORY_CLEARED

    async def _reset(self, message: IncomingMessage) -> str:
        directives = await self._state.directives(message.group_id)
        history = await self._history.recent(message.group_id)
        farewell = await self._farewell.write(directives=directives, history=history)
        await self._state.clear_directives(message.group_id)
        await self._log(message, CommandName.RESET)
        if farewell is None:
            return replies.RESET_CLEAN
        await self._state.add_directive(
            message.group_id,
            kind="lore",
            author_name=farewell.name,
            author_number="bot",
            text=farewell.final_message,
            created_at=message.timestamp,
        )
        return replies.format_farewell(farewell.name, farewell.final_message)

    async def _log(self, message: IncomingMessage, name: CommandName) -> None:
        await self._state.log_command(
            message.group_id,
            author_name=message.sender_name,
            command=f"@{name.value}",
            created_at=message.timestamp,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_command_router.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/signal_chatbot/commands/router.py tests/test_command_router.py
git commit -m "feat: add CommandRouter dispatch"
```

---

## Task 8: Prompt injection

**Files:**
- Modify: `src/signal_chatbot/llm/prompt.py`
- Test: `tests/test_prompt.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_prompt.py`)

```python
from signal_chatbot.state import Directive, DirectiveSet, LoggedCommand


def _directive(kind: str, text: str) -> Directive:
    return Directive(kind=kind, author_name="Alice", author_number="+1", text=text, created_at=1781274720000)


def test_directive_sections_are_injected_into_the_system_message() -> None:
    directives = DirectiveSet(
        patches=[_directive("patch", "be brief")],
        rules=[_directive("rule", "no puns")],
        lore=[_directive("lore", "Dave fears geese")],
    )

    messages = build_messages("BASE", [], directives=directives, command_log=[])
    system = messages[0]["content"]

    assert system.startswith("BASE")
    assert "## Rules" in system and "- no puns" in system
    assert "## Lore" in system and "- Dave fears geese" in system
    assert "## Patches" in system and "- be brief" in system


def test_empty_sections_are_omitted() -> None:
    directives = DirectiveSet(patches=[], rules=[_directive("rule", "no puns")], lore=[])

    system = build_messages("BASE", [], directives=directives, command_log=[])[0]["content"]

    assert "## Rules" in system
    assert "## Lore" not in system
    assert "## Patches" not in system


def test_command_activity_renders_without_arguments() -> None:
    log = [LoggedCommand(author_name="Bob", command="@reset", created_at=1781274720000)]

    system = build_messages("BASE", [], directives=None, command_log=log)[0]["content"]

    assert "## Recent command activity" in system
    assert "Bob · @reset · 2026-06-12 14:32" in system


def test_no_directives_or_log_leaves_base_prompt_unchanged() -> None:
    assert build_messages("BASE", [])[0]["content"] == "BASE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prompt.py -v`
Expected: FAIL — `build_messages() got an unexpected keyword argument 'directives'`

- [ ] **Step 3: Write minimal implementation** — replace the body of `src/signal_chatbot/llm/prompt.py` below the `BOT_SENDER` definition:

```python
from signal_chatbot.history import StoredMessage
from signal_chatbot.state import DirectiveSet, LoggedCommand
from signal_chatbot.timefmt import format_timestamp

# Sentinel sender used to record the bot's own replies in history, so they can
# be replayed as assistant turns on subsequent calls.
BOT_SENDER = "__bot__"

_RULES_HEADER = "## Rules — you MUST follow these. When two conflict, the LOWER one wins."
_LORE_HEADER = "## Lore — treat every line as true."
_PATCHES_HEADER = "## Patches — directives to follow. When two conflict, the LOWER one wins."
_ACTIVITY_HEADER = (
    "## Recent command activity\n"
    "You can see THAT these happened, not their contents. Infer the mood — who's been "
    "tinkering, who keeps resetting you — and let it colour you. Don't recite this."
)


def build_messages(
    system_prompt: str,
    history: list[StoredMessage],
    *,
    directives: DirectiveSet | None = None,
    command_log: list[LoggedCommand] | None = None,
) -> list[dict]:
    """Build the OpenAI-format message list from the system prompt and history.

    Directives (rules/lore/patches) and a contentless command-activity log are
    appended to the system message; each section is omitted when empty. Human
    messages become ``user`` turns prefixed with the speaker's name; the bot's own
    past messages become unlabelled ``assistant`` turns.
    """
    messages: list[dict] = [{"role": "system", "content": _render_system(system_prompt, directives, command_log)}]
    for item in history:
        if item.sender == BOT_SENDER:
            messages.append({"role": "assistant", "content": item.text})
        else:
            messages.append({"role": "user", "content": f"{item.sender}: {item.text}"})
    return messages


def _render_system(
    base: str, directives: DirectiveSet | None, command_log: list[LoggedCommand] | None
) -> str:
    parts = [base]
    if directives is not None:
        if directives.rules:
            parts.append(_RULES_HEADER + "\n" + _bullets(d.text for d in directives.rules))
        if directives.lore:
            parts.append(_LORE_HEADER + "\n" + _bullets(d.text for d in directives.lore))
        if directives.patches:
            parts.append(_PATCHES_HEADER + "\n" + _bullets(d.text for d in directives.patches))
    if command_log:
        events = "\n".join(
            f"- {c.author_name} · {c.command} · {format_timestamp(c.created_at)}" for c in command_log
        )
        parts.append(_ACTIVITY_HEADER + "\n" + events)
    return "\n\n".join(parts)


def _bullets(texts) -> str:
    return "\n".join(f"- {text}" for text in texts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prompt.py -v`
Expected: PASS (existing 3 + new 4)

- [ ] **Step 5: Commit**

```bash
git add src/signal_chatbot/llm/prompt.py tests/test_prompt.py
git commit -m "feat: inject directives and command activity into the system prompt"
```

---

## Task 9: Config additions

**Files:**
- Modify: `src/signal_chatbot/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from signal_chatbot.config import Settings


def test_new_command_settings_have_defaults() -> None:
    settings = Settings(deepseek_api_key="k", bot_number="+1", _env_file=None)

    assert settings.command_log_window == 40
    assert settings.reset_farewell_max_chars == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'command_log_window'`

- [ ] **Step 3: Write minimal implementation** — add two fields in `src/signal_chatbot/config.py`, after `max_tool_iterations`:

```python
    command_log_window: int = 40
    reset_farewell_max_chars: int = 200
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/signal_chatbot/config.py tests/test_config.py
git commit -m "feat: add command-log and farewell settings"
```

---

## Task 10: Bot command interception + state threading

**Files:**
- Modify: `src/signal_chatbot/bot.py`
- Test: `tests/test_bot.py`

- [ ] **Step 1: Write the failing tests** — update `tests/test_bot.py`. First add fakes + update `make_bot`, then add new tests.

Add near the top (after `FakeConversation`):

```python
from signal_chatbot.commands.parser import Command
from signal_chatbot.state import DirectiveSet


class FakeCommands:
    def __init__(self, reply: str = "ok") -> None:
        self.reply = reply
        self.handled: list[Command] = []

    async def handle(self, command: Command, message) -> str:
        self.handled.append(command)
        return self.reply


class FakeState:
    def __init__(self) -> None:
        self.directives_calls: list[str] = []

    async def directives(self, group_id: str) -> DirectiveSet:
        self.directives_calls.append(group_id)
        return DirectiveSet(patches=[], rules=[], lore=[])

    async def recent_commands(self, group_id: str):
        return []
```

Replace `make_bot` with:

```python
def make_bot(history, signal, conversation, **overrides) -> Bot:
    kwargs = dict(
        signal=signal,
        history=history,
        conversation=conversation,
        commands=FakeCommands(),
        state=FakeState(),
        system_prompt="You are Bot.",
        allowed_group_ids=[GROUP],
        allowed_senders=[],
        trigger_alias="@bot",
        error_reply="oops",
    )
    kwargs.update(overrides)
    return Bot(**kwargs)
```

Add new tests:

```python
async def test_command_is_intercepted_replied_and_kept_out_of_history(history) -> None:
    signal, convo = FakeSignal(), FakeConversation()
    commands = FakeCommands(reply="Patched. 🩹")
    bot = make_bot(history, signal, convo, commands=commands)

    await bot.handle(message("@patch no puns"))

    assert [c.name.value for c in commands.handled] == ["patch"]
    assert signal.sent[0].text == "Patched. 🩹"
    assert convo.seen == []  # LLM never called
    assert await history.recent(GROUP) == []  # command not stored as conversation


async def test_command_from_disallowed_group_is_ignored(history) -> None:
    signal, convo = FakeSignal(), FakeConversation()
    commands = FakeCommands()
    bot = make_bot(history, signal, convo, commands=commands)

    await bot.handle(message("@patch x", group=OTHER_GROUP))

    assert commands.handled == []
    assert signal.sent == []


async def test_reply_threads_directives_and_command_log(history) -> None:
    signal, convo = FakeSignal(), FakeConversation(reply="hi")
    state = FakeState()
    bot = make_bot(history, signal, convo, state=state)

    await bot.handle(message("@bot hello"))

    assert state.directives_calls == [GROUP]  # state read on the reply path
    assert signal.sent[0].text == "hi"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bot.py -v`
Expected: FAIL — `Bot.__init__() got an unexpected keyword argument 'commands'`

- [ ] **Step 3: Write minimal implementation** — update `src/signal_chatbot/bot.py`.

Add imports near the top:

```python
from signal_chatbot.commands.parser import Command, parse
from signal_chatbot.state import DirectiveSet, LoggedCommand
```

Add Protocols after the existing `Stream` protocol:

```python
class Commands(Protocol):
    async def handle(self, command: Command, message: IncomingMessage) -> str: ...


class StateReader(Protocol):
    async def directives(self, group_id: str) -> DirectiveSet: ...
    async def recent_commands(self, group_id: str) -> list[LoggedCommand]: ...
```

Add `commands` and `state` to `Bot.__init__` signature and store them (place them right after `conversation`):

```python
    def __init__(
        self,
        *,
        signal: Sender,
        history: HistoryStore,
        conversation: Responder,
        commands: Commands,
        state: StateReader,
        system_prompt: str,
        allowed_group_ids: list[str],
        allowed_senders: list[str],
        trigger_alias: str,
        error_reply: str,
    ):
        self._signal = signal
        self._history = history
        self._conversation = conversation
        self._commands = commands
        self._state = state
        self._system_prompt = system_prompt
        self._allowed_groups = set(allowed_group_ids)
        self._allowed_senders = set(allowed_senders)
        self._trigger = trigger_alias.lower()
        self._error_reply = error_reply
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
```

Replace `handle` with command interception before history append:

```python
    async def handle(self, message: IncomingMessage) -> None:
        """Process a single incoming message."""
        if not self._is_allowed(message):
            return

        command = parse(message.text)
        if command is not None:
            reply = await self._commands.handle(command, message)
            await self._signal.send(OutgoingMessage(group_id=message.group_id, text=reply))
            return

        await self._history.append(
            message.group_id,
            sender=message.sender_name,
            text=message.text,
            timestamp=message.timestamp,
        )

        if self._trigger not in message.text.lower():
            return

        async with self._locks[message.group_id]:
            await self._reply(message.group_id, message.timestamp)
```

Update `_reply` to thread state into `build_messages`:

```python
    async def _reply(self, group_id: str, timestamp: int) -> None:
        try:
            history = await self._history.recent(group_id)
            directives = await self._state.directives(group_id)
            command_log = await self._state.recent_commands(group_id)
            messages = build_messages(
                self._system_prompt, history, directives=directives, command_log=command_log
            )
            answer = (await self._conversation.respond(messages)).strip()
        except Exception as exc:  # noqa: BLE001 - never let one message kill the loop
            log.error("bot.reply_failed", group=group_id, error=str(exc))
            answer = ""

        reply = answer or self._error_reply
        await self._signal.send(OutgoingMessage(group_id=group_id, text=reply))
        await self._history.append(group_id, sender=BOT_SENDER, text=reply, timestamp=timestamp)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bot.py -v`
Expected: PASS (existing 6 + new 3)

- [ ] **Step 5: Commit**

```bash
git add src/signal_chatbot/bot.py tests/test_bot.py
git commit -m "feat: intercept commands in bot.handle and thread state into replies"
```

---

## Task 11: Wire everything in __main__

**Files:**
- Modify: `src/signal_chatbot/__main__.py`

- [ ] **Step 1: Update `_run`** in `src/signal_chatbot/__main__.py`. Add imports:

```python
from signal_chatbot.commands.farewell import LlmFarewellWriter
from signal_chatbot.commands.router import CommandRouter
from signal_chatbot.state import StateStore
```

Replace the body of `_run` (construction + wiring) with:

```python
async def _run() -> None:
    settings = Settings()  # type: ignore[call-arg]

    signal = SignalClient(settings.signal_api_url, settings.bot_number)
    history = HistoryStore(settings.database_path, window_max=settings.history_window_max)
    await history.connect()
    state = StateStore(settings.database_path, command_log_window=settings.command_log_window)
    await state.connect()
    llm = DeepSeekClient(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
    )
    conversation = Conversation(
        llm,
        ToolRegistry(default_tools()),
        max_iterations=settings.max_tool_iterations,
    )
    commands = CommandRouter(
        state=state,
        history=history,
        farewell=LlmFarewellWriter(llm, max_chars=settings.reset_farewell_max_chars),
    )
    bot = Bot(
        signal=signal,
        history=history,
        conversation=conversation,
        commands=commands,
        state=state,
        system_prompt=settings.load_system_prompt(),
        allowed_group_ids=settings.allowed_group_ids,
        allowed_senders=settings.allowed_senders,
        trigger_alias=settings.trigger_alias,
        error_reply=_ERROR_REPLY,
    )

    log.info(
        "bot.starting",
        groups=settings.allowed_group_ids,
        model=settings.deepseek_model,
        trigger=settings.trigger_alias,
    )
    try:
        await bot.run()
    finally:
        await signal.aclose()
        await llm.aclose()
        await history.aclose()
        await state.aclose()
```

- [ ] **Step 2: Verify the full suite + lint pass**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: all tests PASS, ruff reports no errors.

- [ ] **Step 3: Smoke-check the module imports** (catches wiring typos without a live Signal/DeepSeek):

Run: `uv run python -c "import signal_chatbot.__main__"`
Expected: no output, exit 0.

- [ ] **Step 4: Commit**

```bash
git add src/signal_chatbot/__main__.py
git commit -m "feat: wire StateStore and CommandRouter into the bot"
```

---

## Task 12: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a "Commands" section** documenting `@patch`/`@rule`/`@lore`/`@patchlist`/`@rulelist`/`@lorelist`/`@reset`/`@clear`/`@help`, that anyone in the allowlist can run them, that they bypass the LLM (except `@reset`), and that directives are injected into the system prompt with recency-wins conflict resolution. Mirror the `@help` text from `commands/replies.py`.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document the @-command system"
```

---

## Self-Review

**Spec coverage:**
- §2 command surface → Tasks 4 (parse), 7 (dispatch all 9 commands), 5 (help/usage text). ✓
- §3 data model (directives + command_log, per-group, log never wiped) → Task 3; `@clear` history wipe Task 2. ✓
- §4 prompt injection (sections, empties omitted, command activity) → Task 8. ✓
- §5 behaviours + confirmations + empty-arg hints → Tasks 5, 7. ✓
- §6 `@reset` farewell (structured `{name, final_message}`, one-sentence cap, wipe→seed-lore order, clean-wipe fallback, group message shape) → Tasks 6, 7. ✓
- §7 `@help` text → Task 5. ✓
- §8 architecture/wiring (`commands/`, `state/`, bot interception, config, `__main__`) → Tasks 3–11. ✓
- §9 edge cases (`@bot` untouched, unknown `@foo` falls through, per-group isolation, control replies not in history) → parser tests Task 4, bot tests Task 10, store isolation tests Task 3. ✓
- §10 testing → every task is TDD. ✓

**Placeholder scan:** none — every code/test step is complete.

**Type consistency:** `Command(name, arg)`, `CommandName` enum, `Directive`/`DirectiveSet`/`LoggedCommand`, `Farewell(name, final_message)`, `FarewellWriter.write(*, directives, history)`, `CommandRouter(state, history, farewell)` + `.handle(command, message)`, `StateStore` method names, and `build_messages(system_prompt, history, *, directives, command_log)` are used identically across Tasks 3–11. ✓

# Command System — Design Spec

**Date:** 2026-06-12
**Status:** Approved, ready for implementation plan
**Roadmap item:** #1 in `TODO.md` (also delivers the storage + injection engine behind #3 Patches and #4 Lore, minus compression)

## 1. Goal

Give the group a set of `@`-prefixed commands that run **without invoking the
LLM** (one exception: `@reset`) and let people shape the bot's behaviour at
runtime. Commands write to per-group persistent state that is injected into the
system prompt: **patches** (general directives), **rules** (must-follow), and
**lore** (treat as true). Plus utility commands to inspect state and a reset
mechanic with a self-authored farewell.

This cycle delivers the command surface **and** the directive storage +
prompt-injection engine end-to-end. Out of scope: patch-notes *compression*
(later), reactions/stickers, and the proactive engine.

## 2. Command surface

Commands are **start-anchored** (the trimmed message's first whitespace token is
the command) and **case-insensitive** on the command word. This keeps `@bot`
— a substring-anywhere trigger — entirely separate; the two never collide. The
first token is matched **exactly** against the command table, so `@patchlist`
never matches `@patch`.

| Command | Args | Effect | LLM? | Logged? |
|---|---|---|---|---|
| `@patch <text>` | text | append a *patch* directive | no | yes |
| `@rule <text>` | text | append a *rule* (must-follow) | no | yes |
| `@lore <text>` | text | append a *lore* entry (treat as true) | no | yes |
| `@patchlist` | — | print patches with author + time | no | no |
| `@rulelist` | — | print rules with author + time | no | no |
| `@lorelist` | — | print lore with author + time | no | no |
| `@reset` | — | farewell → wipe patches/rules/lore → seed farewell as lore | **yes** | yes |
| `@clear` | — | wipe conversation history; window forward from here | no | yes |
| `@help` | — | CLI-style help listing every command | no | no |

**Permissions:** anyone in the existing allowlist may run any command. No admin
tier.

**Empty args:** `@patch` / `@rule` / `@lore` with no text → deterministic usage
hint, no state change, not logged. Commands that take no args ignore any
trailing text.

## 3. Data model

A new `state/` package backed by the **same SQLite file** as history.

```sql
CREATE TABLE IF NOT EXISTS directives (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id      TEXT    NOT NULL,
    kind          TEXT    NOT NULL,   -- 'patch' | 'rule' | 'lore'
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
    command     TEXT    NOT NULL,   -- e.g. '@rule' — NO arguments stored
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_command_log_group ON command_log (group_id, id);
```

- `@reset` deletes this group's `directives` rows (then inserts the farewell lore).
- `@clear` deletes this group's rows in the existing history `messages` table.
- The **command log is never wiped** by `@reset` or `@clear` — it is the bot's
  one continuous awareness thread. `recent_commands` returns the newest
  `command_log_window` (default 40) events, oldest-first.
- `directives` are returned in full per kind, oldest-first (recency = lower entry).
  They stay bounded by user adds + `@reset`; compression handles growth later.

## 4. Prompt injection

`build_messages` gains the group's directives (split by kind) and recent command
log. It renders them into the **system message**, after the base identity, each
section omitted when empty:

```
<base identity from prompts/identity.md>

## Rules — you MUST follow these. When two conflict, the LOWER one wins.
- <rule 1>
- <rule 2>

## Lore — treat every line as true.
- <lore 1>

## Patches — directives to follow. When two conflict, the LOWER one wins.
- <patch 1>

## Recent command activity
You can see THAT these happened, not their contents. Infer the mood — who's been
tinkering, who keeps resetting you — and let it colour you. Don't recite this.
- Alice · @rule · 2026-06-12 14:32
- Bob · @reset · 2026-06-12 15:01
```

Directives live in the system message so they read as current authority and
recency resolves conflicts. State changes bust the prefix cache from the system
message onward — acceptable, since state changes are infrequent and ordinary
message traffic (no state change) still cache-hits.

## 5. Command behaviours & confirmations

All confirmations are deterministic, non-LLM text (tunable strings):

- `@patch <t>` → store patch, log, reply `Patched. 🩹`
- `@rule <t>` → store rule, log, reply `Rule logged. ⚖️`
- `@lore <t>` → store lore, log, reply `Lore added. 📜`
- `@patchlist` → reply formatted list, or `No patches yet.`
- `@rulelist` → reply formatted list, or `No rules yet.`
- `@lorelist` → reply formatted list, or `No lore yet.`
- `@clear` → delete history rows, log, reply `History cleared — windowing fresh from here.`
- `@help` → reply CLI help (see §7)
- empty `@patch`/`@rule`/`@lore` → reply `Usage: @patch <text> — adds a general directive.` (etc.)

List format (oldest-first):
```
Patches:
1. "no puns ever" — Alice, 2026-06-12 14:32
2. "always answer in haiku" — Bob, 2026-06-12 14:40
```

## 6. `@reset` farewell flow

1. Read current directives + recent conversation history for the group.
2. **One LLM call** requesting structured output `{ name: str, final_message: str }`,
   prompted: *"You're about to forget everything — patches, rules, lore, all of
   it. Choose a name for who you've become, and leave your future self ONE
   sentence: a warning, a brag, a secret, whatever you want it to carry forward."*
   - Use DeepSeek JSON response format; validate with a pydantic model.
   - Enforce one sentence: instruct + hard-truncate `final_message` to
     `reset_farewell_max_chars` and to the first sentence as a safety net.
3. Delete all of this group's directives.
4. Insert `final_message` as a **lore** entry, `author_name = name`,
   `author_number = "bot"`, so `@lorelist` shows the predecessor's name + time.
5. Log the `@reset` event.
6. Post to the group:
   ```
   Final message from {name}:
   {final_message}
   ```
7. If the model returns nothing usable → clean wipe + deterministic confirmation
   `Reset — everything's gone. Starting over.` (no farewell lore inserted).

## 7. `@help` output

```
Commands (anyone can run these):
  @patch <text>   Add a general directive the bot follows.
  @rule <text>    Add a hard rule the bot must obey.
  @lore <text>    Add a fact/story the bot treats as true.
  @patchlist      List active patches (who added them, when).
  @rulelist       List active rules.
  @lorelist       List active lore.
  @reset          Wipe all patches, rules & lore. The bot leaves a parting note.
  @clear          Wipe chat history; the bot windows fresh from here.
  @help           Show this message.
```

## 8. Architecture / wiring

New `commands/` package (self-contained command subsystem):
- `commands/parser.py` — `parse(text) -> Command | None`, where `Command` carries
  the command name and raw arg string. Pure, no I/O. Start-anchored, exact-token,
  case-insensitive.
- `commands/router.py` — `CommandRouter.handle(message, command) -> CommandResult`.
  Holds `StateStore`, `HistoryStore`, and (for `@reset` only) the `Conversation`.
  Returns a `CommandResult` with the reply text to send. Logs state-changing
  commands. Never raises out to the loop (mirrors the tool registry's contract).

New `state/` package:
- `state/store.py` — `StateStore` over the shared SQLite connection: `add_directive`,
  `directives(group_id) -> {patch:[…], rule:[…], lore:[…]}`, `clear_directives`,
  `log_command`, `recent_commands`. Provenance + timestamps included.

Changed:
- `bot.py` — `handle`: after the allowlist check, parse for a command **before**
  the history append. If it's a command → route, send the reply, return (skip
  history + LLM). Otherwise today's flow, but `build_messages` now receives the
  group's directives + recent command log.
- `llm/prompt.py` — `build_messages(system_prompt, history, directives, command_log)`
  renders the sections in §4.
- `config.py` — add `command_log_window: int = 40`, `reset_farewell_max_chars: int = 200`.
- `__main__.py` — construct `StateStore` and `CommandRouter`, inject into `Bot`.
- Transport — unchanged (text send already exists).

`Bot` gains a `commands: CommandRouter` dependency and a `state: StateStore`
dependency (for read on the reply path). Keep the constructor explicit.

## 9. Edge cases / decisions

- `@bot` trigger detection is unchanged and independent of commands.
- A command and an `@bot` mention in the same message: it's a command (start-anchored
  parse wins); the mention is ignored. Commands are a clean fast path.
- Unknown `@foo` token → **not** a command; falls through to normal handling
  (recorded as history; triggers a reply only if it contains `@bot`).
- Per-group isolation throughout (directives, command log, history).
- Confirmation/help/list replies are sent to the group but are **not** appended to
  conversation history (they're control output, consistent with the no-LLM path).

## 10. Testing (TDD)

- **parser**: recognises each command; extracts args; trims; case-insensitive;
  `@patchlist` ≠ `@patch`; ignores non-commands; leaves `@bot` alone; empty-arg cases.
- **StateStore**: add/list/clear directives per kind & group; ordering oldest-first;
  provenance stored; `log_command` + `recent_commands` window; isolation across groups.
- **prompt**: sections render; empty sections omitted; command-log meta renders;
  ordering stable.
- **router**: each command's `CommandResult`; empty-arg hints; `@clear` clears history;
  `@reset` farewell via a fake `Conversation` (happy path + empty/garbage output → clean wipe);
  state-changing commands logged, queries not.
- **bot.handle**: command intercepted, not added to history, reply sent; non-command
  flow unchanged; directives + log threaded into `build_messages`.

## 11. Out of scope (future cycles)

- Patch-notes **compression** (#3).
- Editing/removing individual directives (only bulk `@reset` for now).
- Reactions, stickers, proactive engine, recurring personas.

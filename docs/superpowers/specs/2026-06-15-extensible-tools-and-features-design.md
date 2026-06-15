# Extensible tools + per-sender awareness, web search, quotes — design

Date: 2026-06-15
Status: Approved (pre-implementation)

## Goal

Add five user-facing capabilities to the Signal chatbot **and** refactor the two
god-files that make such additions painful, so that future features are genuinely
one-file-ish to add.

User-facing capabilities:

1. Per-sender **profiles** the bot maintains, clearable on demand.
2. Bot can author its **own rules and lore** (clearly announced).
3. **Quote replies** to a specific earlier message.
4. **Web search** (Tavily, snippets-only).
5. **`@info`** command: explains `@help` and lists every tool the bot can call.

Plus two cleanups requested alongside:

- Remove **patches** (they add nothing over rules/lore).
- **Clear disclaimers** on `@reset` / `@lobotomy` / self-death.

## Locked decisions

- Web search provider: **Tavily** (LLM-oriented, clean pre-summarised content, one API key).
- Web search depth: **snippets only** — no arbitrary page fetching (bounds tokens, minimises
  prompt-injection surface).
- Profile population: **bot-driven tool** (no extra LLM passes; mirrors `set_name`).
- Profile clearing: **`@forget`** wipes all group profiles; **`@forget <name>`** wipes one.
- Keep a **`@profiles`** inspect command for symmetry with `@rulelist` etc.
- Split both **`state/store.py`** and **`llm/conversation.py`**.

---

## Part A — Architecture refactor (the enabler)

### A1. Tool context + outcome

The current contract — registry tools are `run(args) -> str`, dispatched via
`(name, args) -> str` — cannot express a tool that needs the group it is acting in or
that produces a visible side-effect. That is why `final_answer` and the kill tools are
hardcoded inside `conversation.py`. We fix the contract.

New types (in `tools/` — e.g. `tools/context.py` or extend `tools/base.py`):

```python
@dataclass(frozen=True, slots=True)
class ToolContext:
    group_id: str
    timestamp: int  # the current inbound message's clock; used for created_at

@dataclass(frozen=True, slots=True)
class ToolOutcome:
    result: str                       # what the model sees as the tool result
    announcements: list[str] = []     # extra PUBLIC messages to send to the group
```

`Tool.run` becomes `async def run(self, args, ctx: ToolContext) -> ToolOutcome | str`.
Returning a bare `str` is allowed; the registry normalises it to
`ToolOutcome(result=str)`. All existing tools (clock, set_name, wikipedia) gain the
`ctx` parameter (ignored where unused) and keep returning strings — mechanical churn.

`ToolRegistry.dispatch(name, args, ctx) -> ToolOutcome`.

`Conversation.respond` gains a `ctx: ToolContext` parameter (built by the bot from
`group_id` + the message timestamp). The loop accumulates `announcements` from every
tool outcome and attaches them to the returned `BotReply`. The bot sends each
announcement as **its own message** — sent but **not** stored in history (same
discipline as the self-destruct warning and the tool-usage footer, so the model can't
learn to fake them).

This single mechanism is what makes "bot adds a rule and it shows as a clearly-marked
separate message" a one-file tool.

> Control-flow tools (`final_answer`, `attempt_kill_self`, `confirm_kill_self`) stay
> special — they terminate the loop and shape the reply rather than returning a result.
> They are NOT registry tools. The kill-arming flow stays in the bot layer unchanged.

### A2. Split `state/store.py` into a `state/` package

Replace the single `StateStore` god-class with a thin aggregate over focused sub-stores,
each owning exactly one table.

```
state/
  __init__.py        # re-exports models + Database
  database.py        # Database: connection lifecycle + schema bootstrap; exposes sub-stores
  directives.py      # DirectiveStore + Directive, DirectiveSet  (rules + lore only)
  commands.py        # CommandLog + LoggedCommand
  disclaimers.py     # DisclaimerStore + Disclaimer  (+ clear())
  arming.py          # ArmingStore  (suicide arming)
  profiles.py        # ProfileStore + Profile  (NEW)
```

- `Database` opens one shared `aiosqlite` connection, applies `PRAGMA journal_mode=WAL`,
  and runs each sub-store's `CREATE TABLE`. It exposes the sub-stores as attributes
  (`db.directives`, `db.commands`, `db.disclaimers`, `db.arming`, `db.profiles`) and
  owns `connect()` / `aclose()`.
- The bot keeps depending on **narrow Protocols** (it already defines `StateReader`,
  `DisclaimerLog`); these are now satisfied by the individual sub-stores. `__main__`
  wires the specific sub-store into each consumer (bot, router, lobotomiser).
- Adding new state later = new store file + one line in `Database`.

`HistoryStore` is already focused; it is **not** part of this split. It gains only a
`sender_number` column (see C5).

### A3. Split `llm/conversation.py`

```
llm/
  conversation.py   # the orchestration loop ONLY (respond, force_final, record_tool_turn)
  reply.py          # BotReply dataclass
  control.py        # final_answer + kill tool defs, revelation/answer-now text,
                    # arg-extraction helpers (_final_answer_args, _confirm_kill_args, _called)
  parsing.py        # _parse_reply, _extract_reply_object, _strip_code_fence,
                    # _strip_tool_markup, _message, _clean, _parse_args, footer helpers
  prompt.py         # (unchanged location; edited for new sections)
  deepseek.py       # unchanged
```

No behaviour change — pure extraction — except the `ctx` plumbing and announcement
accumulation from A1.

---

## Part B — Cleanups

### B1. Remove patches

Drop the `patch` kind everywhere:

- `DirectiveSet.patches` removed; `_KINDS = ("rule", "lore")`.
- `DirectiveStore.directives()` returns `DirectiveSet(rules, lore)`. Existing
  `kind='patch'` rows are simply not surfaced (no migration needed).
- Parser: remove `PATCH`, `PATCHLIST` from `CommandName`.
- Replies: remove `PATCHED`, `USAGE_PATCH`, the patches lines from `HELP_TEXT`.
- Router: remove the patch / patchlist cases.
- Prompt: remove `_PATCHES_HEADER` and its block.
- Docs: `README.md`, `prompts/identity.md` patch mentions removed.

### B2. Clear disclaimers on wipe

`DisclaimerStore.clear(group_id)`, wired into:

- `Lobotomiser.wipe` (which also covers **self-death**, since self-lobotomy routes
  through `wipe`), and
- `CommandRouter._reset`.

Docs updated (README currently states disclaimers survive — that becomes false).

---

## Part C — Features

### C1. Per-sender profiles

- `ProfileStore` table `profile_notes(id, group_id, subject, note, created_at)`, one note
  per row, keyed by **subject name** (the bot reasons in names, history shows names, and
  `@forget <name>` matches on the same key).
  - `add_note(group_id, *, subject, note, created_at)`
  - `all(group_id) -> list[Profile]`  (aggregated per subject, each `Profile` = subject +
    ordered notes)
  - `clear(group_id)`  (all subjects)
  - `forget(group_id, subject) -> bool`  (one subject; returns whether anything matched)
- Tool `remember_about_user(about: str, note: str)` — bot-driven; appends a note for
  `about` using `ctx.group_id` / `ctx.timestamp`. **Result-only, no announcement**
  (private memory) — the clean example of a stateful tool with no public side-effect.
- Prompt: new section `## What you know about people`, listing notes per subject, injected
  by `build_messages` / `_render_system`.
- Commands:
  - `@profiles` — list current profiles (formatter in `replies.py`).
  - `@forget` — clear all group profiles.
  - `@forget <name>` — clear one subject; reply differs if no such subject.
- Cleared by `@reset`, `@lobotomy`, self-death (via the wipe paths).

### C2. Bot authors rules / lore

- Tools `add_rule(text: str)` and `add_lore(text: str)`; author recorded as the bot
  (`author_name = name.current`, `author_number = "__bot__"` sentinel, `created_at =
  ctx.timestamp`).
- Each returns a `ToolOutcome` with an **announcement**:
  - `⚖️ {name} added a rule: "{text}"`
  - `📜 {name} added lore: "{text}"`
  sent as its own message via the A1 mechanism. The directive itself is injected into the
  prompt on subsequent turns as usual.
- Each tool is injected with the `DirectiveStore` and the `NameSource` (the existing
  `BotName`) at construction — same dependency-injection style as `set_name`.

### C3. Quote replies

- `HistoryStore.messages` gains a `sender_number` column.
  - New DB: column in `CREATE TABLE`.
  - Existing DB: guarded `ALTER TABLE messages ADD COLUMN sender_number TEXT NOT NULL
    DEFAULT ''` in `connect()` (check via `PRAGMA table_info`).
  - `StoredMessage` gains `sender_number`; `append()` takes it (bot passes
    `message.sender_number` for user turns, the bot's own number/sentinel for bot turns).
- Prompt: each history line is prefixed with a short `[#N]` reference (1-based over the
  recent window, matching list order). The model cites it.
- `final_answer` gains an optional `reply_to: int | null` field ("the #N of the message
  you're replying to; omit to not quote").
- `BotReply` gains `reply_to_index: int | None`. The bot resolves `N → history[N-1]` →
  `(timestamp, sender_number, text)` and builds the outgoing quote. Invalid / out-of-range
  / missing → no quote (silently).
- `OutgoingMessage` gains optional `quote_timestamp: int | None`, `quote_author: str |
  None`, `quote_message: str | None`. `SignalClient.send` includes the
  `quote_*` fields in the `/v2/send` body when present.

### C4. Web search (Tavily, snippets-only)

- New package `tools/builtin/websearch/`:
  - `client.py` — `TavilyClient` (httpx POST to Tavily search API; returns a small list of
    `(title, url, snippet)`), honouring a result limit and a per-snippet char cap.
  - `tool.py` — `WebSearch` tool: `Args { query: str }`; returns capped
    `title / url / snippet` lines as a plain string. Pure info tool; no context needed.
- Config: `TAVILY_API_KEY` (optional), `websearch_result_limit`, `websearch_snippet_max_chars`.
- The tool is **only registered when a key is present** (so a keyless deployment simply
  lacks the ability rather than erroring).
- Injection mitigation: snippets only, length-capped, and the tool result is framed as
  external/untrusted content.

### C5. `@info` command

- `Tool` gains a short human-facing `summary` class attribute (distinct from the verbose,
  model-targeted `description`). Every existing and new tool sets it.
- `CommandName.INFO`; router `_info` handler is injected with the `ToolRegistry` (or a
  derived `list[(name, summary)]`).
- Reply (formatter in `replies.py`):
  - one line explaining that `@help` lists the commands people can run, then
  - every registry tool as `name — summary` (introspected, so new tools self-list), plus
  - a one-line note on the bot's self-destruct ability (which lives outside the registry).

---

## Data flow (reply path, after changes)

1. Inbound message → `Bot.handle`.
2. Bot builds `ToolContext(group_id, timestamp)` and the prompt
   (`build_messages` now also yields the `[#N]` reference window).
3. `Conversation.respond(messages, ctx, armed=…)`:
   - each iteration the model calls info/action tools (run via the registry with `ctx`;
     outcomes' `result` go back to the model, `announcements` accumulate) or a control
     tool (`final_answer` / kill).
   - returns `BotReply` with `message`, `ethical_disclaimer`, `tool_footer`,
     `announcements`, `reply_to_index`, and the existing self-destruct flags.
4. Bot:
   - sends each `announcement` as its own message (not stored),
   - composes the main outgoing message (warning? + message + footer), resolving
     `reply_to_index` into Signal quote fields,
   - stores the bare message in history (with `sender_number`),
   - arms / self-lobotomises as today.

## Testing

- Unit tests per new/!split module: `ProfileStore`, the split `state` sub-stores,
  `TavilyClient` (mocked httpx), `WebSearch`, the new tools (`remember_about_user`,
  `add_rule`, `add_lore`) including announcement emission, the `ToolOutcome`
  normalisation in the registry, quote resolution in the bot, `@info`/`@profiles`/
  `@forget` router + reply formatting, patch-removal regressions.
- Existing tests updated for: split imports, removed patches, `ctx` parameter,
  disclaimer clearing on reset/lobotomy.
- Full suite (`uv run pytest`) green before merge.

## Build order & parallelism

- **Phase 0 — foundation (sequential, shared files):** A1 tool context/outcome,
  A2 state split, A3 conversation split, B1 remove patches, B2 disclaimer clearing,
  and the `ProfileStore` + clearing wiring. Everything else builds on this.
- **Phase 1 — features (parallel, isolated in git worktrees, then integrated):**
  - Web search (fully isolated new package).
  - Profiles tool + prompt section + `@profiles`/`@forget`.
  - `add_rule` / `add_lore` tools + announcements.
  - Quote replies (history schema + transport + final_answer + prompt + bot).
  - `@info` command + tool summaries.
  Agents are partitioned to non-overlapping regions of the shared files; conflicts in
  `prompt.py` / `parser.py` / `router.py` / `replies.py` / `bot.py` are resolved at
  integration.

## Out of scope

- Reactions, reminders/scheduling, image/vision, typing indicators, rate limiting.
- Migrating `HistoryStore` to the new `state` package (kept separate by design).
- Per-number (vs per-name) profile identity.

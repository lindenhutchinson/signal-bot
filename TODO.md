# Bot Feature Roadmap

Wishlist of bot upgrades, ordered by **fun/impact ÷ effort**. Command system is
pinned first (it's the control surface everything else hangs off); stickers are
pinned last (deprioritized). Each item gets its own spec → plan → implement cycle.

Status legend: `todo` · `spec` · `building` · `done`

| # | Feature | Fun/Impact | Effort | Depends on | Status |
|---|---------|-----------|--------|-----------|--------|
| 1 | **Command system** — `@`-prefixed commands intercepted before the LLM (`@patch`/`@rule`/`@lore`/`@reset`/`@clear`/`@*list`/`@help`). Also delivers the directive storage + prompt-injection engine (the write-half of #3 & #4) and a command-event tracker. Spec: `docs/superpowers/specs/2026-06-12-command-system-design.md` · Plan: `docs/superpowers/plans/2026-06-12-command-system.md`. | High (enabler) | Med | — | `done` |
| 2 | **Weird utility tools** — dice rolls, vibe checks, semi-useful nonsense. Drops straight into the existing `tools/` framework. | Med-High | Low | — | `todo` |
| 3 | **Patch system — compression** — the storage/injection ships in #1; this cycle adds compressing old patches/rules into terse "patch notes" to save tokens. | High (novel) | Med | #1 | `todo` |
| 4 | **Group lore / memory** — storage/injection ships in #1; this cycle adds richer recall/callbacks beyond raw `@lore` entries. | High | Med | #1 | `todo` |
| 5 | **Reactions** — bot adds an emoji reaction to a message instead of (or alongside) replying. Output restricted to one emoji. | High | Med | transport + proactive trigger | `todo` |
| 6 | **Random chime-in** — low-probability check after any message lets the bot speak unprompted (no `@bot`). | Med-High | Med | proactive engine | `todo` |
| 7 | **Recurring character mode** — personas that surface unprompted on a schedule/trigger. | High | High | #4, proactive engine | `todo` |
| 8 | **Stickers** — bot sends Signal stickers (pack id + sticker id). | Med | Med (fiddly pack ids) | transport | `todo` |

## Notes & risks

- **Proactive engine** (the "act when *not* mentioned" decision layer) is shared by
  #5, #6, #7. It's where spam, cost blowups, and annoyance live — build it carefully
  and last among the behavioural features.
- **Reactions risk:** reacting needs the target message's author + timestamp from the
  received envelope. The known upstream signal-cli `serverGuid`/sealed-sender receive
  bug (see memory) could make this unreliable regardless of our code. Confirm receive
  works before sinking effort into #5.
- **Reactions split:** the *ability* to send a reaction (transport) is cheap and could
  ship early as an explicit tool; the *decision* to react randomly belongs to the
  proactive engine. May split #5 across two cycles.

## Architecture touchpoints (reference)

- `bot.py` — orchestrator; command interception + proactive trigger hook here.
- `transport/` — `SignalClient` (ws receive, REST send) + `models.py`; reactions/stickers
  and richer `IncomingMessage` (carry author/timestamp/serverGuid) land here.
- `llm/prompt.py` — `build_messages`; patch + lore injection point.
- `tools/` — `Tool` base + registry; utility tools and a reaction/sticker tool.
- `history/store.py` — SQLite; new tables for patches & lore.
- `prompts/identity.md` — base system prompt.

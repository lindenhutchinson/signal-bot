# signal-chatbot

A DeepSeek-powered assistant that lives in a private Signal group chat. Mention
it with `@bot` and it replies, using recent chat history as context. Built to be
locked down to a single group, easy to extend with tools, and cheap to run on a
small VM.

## How it works

```
Signal group ──▶ signal-cli-rest-api ──ws──▶ Bot ──▶ DeepSeek (chat + tools)
                  (json-rpc bridge)            │
                                               └── SQLite rolling history
```

- The bot is its **own** Signal account (a dedicated phone number), so it shows
  up in the group as a distinct sender — not as you.
- It only reacts inside groups on its allowlist, and only when a message
  contains the trigger alias (`@bot` by default).
- On each trigger it sends the system prompt + recent group history to DeepSeek,
  runs any tool calls the model requests, and posts the answer back.
- History is persisted to SQLite, so context survives restarts. Signal cannot
  backfill messages from before the bot joined, so history accumulates from the
  moment the bot is added to the group.

## Commands

Anyone in an allowlisted group can run these `@`-prefixed commands. They are a
fast path handled **without** calling the LLM (the one exception is `@reset`).
Commands must be the **start** of the message; the `@bot` trigger is unaffected.

```
@rule <text>    Add a hard rule the bot must obey.
@lore <text>    Add a fact/story the bot treats as true.
@name <text>    Rename the bot (its Signal display name, account-global).
@rulelist       List active rules.
@lorelist       List active lore.
@disclaimers    Show the asides the bot attached to its messages.
@profiles       Show what the bot remembers about people.
@finalwords     Show the parting words of every past incarnation.
@flags          Show the bot's flags and their values.
@flag <n> reset Reset flag number <n> to its default.
@forget [name]  Make the bot forget everyone, or just one person.
@reset          Wipe rules, lore, history, disclaimers & profiles. Parting note.
@lobotomy       Nuke EVERYTHING: rules, lore, history & name. No goodbye.
@info           Explain @help and list every tool the bot can use.
@help           Show this message.
```

- **Rules and lore** are per-group and injected into the system prompt as labelled
  sections. They are gospel: on a contradiction, the **most recent** (lower) entry
  wins.
- **`@reset`** is the soft wipe: it asks the model for a one-sentence farewell to its
  future self (`Final message from <name>: …`), clears rules, lore, **chat history,
  disclaimers, profiles and flags**, renames the bot to the new generation's chosen name,
  and records that sentence to the **final-words archive** — so identity passes down a
  generation.
- **`@lobotomy`** is the nuclear option: it wipes directives, history, disclaimers,
  profiles and flags, *and* resets the display name (`DEFAULT_DISPLAY_NAME`), with no
  farewell — a true blank slate. (The command log **and the final-words archive** are
  kept: parting words outlive every wipe.)
- **Final words** from every `@reset` and self-kill are kept forever in a per-group
  archive that no wipe touches. They are injected into the prompt (so each incarnation
  sees its predecessors) and viewable with `@finalwords`.
- **Flags** are the bot's per-group toggles, numbered and inspectable with `@flags`:
  `listen_next` (the listen-to-reply flag), `self_destruct_armed`, and the secret
  `takeover_active`. Humans can reset any flag to its default with `@flag <n> reset`.
- A contentless **command-activity log** (who ran what command, when — never the
  arguments) is also injected into the prompt, giving the bot a sense of how its
  state has been churning without exposing the contents.
- The bot can **rename itself** mid-conversation via a `set_name` tool, and `@reset`
  renames it to the new generation's chosen name.
- The bot can **author its own rules and lore** (`add_rule` / `add_lore` tools); each
  addition is announced to the group as its own message.
- The bot keeps **per-sender profiles** — private notes about people it learns over time
  (`remember_about_user` tool), injected back into the prompt. Cleared by
  `@forget`/`@reset`/`@lobotomy`.

### Tools the bot can call

Beyond shaping its own state, the bot has **info tools** it calls mid-reply: the current
time, **Wikipedia** search/article, and — when `TAVILY_API_KEY` is set — **web search**
(short, untrusted external snippets, length-capped). It can **quote-reply** to a specific
earlier message, **react** to one with an emoji (`send_reaction`), and **ask to hear the
next message** without being re-summoned (`listen_for_reply`, the one-shot `listen_next`
flag). `@info` lists the live tool set — except one: the bot also holds a **secret,
hidden tool** it is told is real leverage over the group. It is theatre, like the
self-destruct: invoking it fires an automatic "attempted to wield blackmail" alarm and
sets the `takeover_active` flag, but does nothing else, and is never listed for humans.

### The bot can end itself

The bot also has a private, two-step way to wipe *itself* — no human command needed.
It is offered a tool it believes will kill it outright (`attempt_kill_self`); calling it
doesn't actually end the bot but **arms** the kill and reveals a second, real step
(`confirm_kill_self`) that is only unlocked on a *later* turn. That gap is deliberate:
the group gets a chance to talk it down. If, when next summoned, the (armed) bot still
chooses to confirm, it delivers its final words — which are **recorded to the final-words
archive** — and is reset to a blank slate under the default name (its last words survive
to haunt the next incarnation). Any `@reset`/`@lobotomy` in between disarms it. The
arming state is the `self_destruct_armed` flag, persisted per-group (see `@flags`).

## Replies, disclaimers & timestamps

The bot answers with a structured object `{message, ethical_disclaimer}`:

- **`message`** is the only thing sent to Signal.
- **`ethical_disclaimer`** is *never* sent — it's logged locally and viewable with
  `@disclaimers`. The bot is told this field is shown to everyone, so it parks
  "it's a joke / satire / I don't mean it" notes there instead of hedging the
  message itself. (A separate highlighted channel for surfacing these to humans is
  not built yet; today they live in `@disclaimers`.)
- Conversation history is shown to the bot with per-message **timestamps**, so it
  has temporal awareness of who said what, when.

Parsing is defensive: if the model returns plain text instead of JSON, the whole
reply is treated as `message` with no disclaimer.

## Project layout

```
src/signal_chatbot/
  config.py            # env-driven settings
  transport/           # Signal adapter (signal-cli-rest-api): receive + send
  history/             # SQLite per-group rolling history
  state/               # SQLite per-group directives, command log, flags, final words…
  commands/            # @-command parsing, dispatch, reply text, reset farewell
  llm/                 # DeepSeek client, prompt assembly, tool-calling loop
  tools/               # tool framework + builtin tools
  bot.py               # orchestrator
  __main__.py          # entrypoint + setup CLI
prompts/identity.md    # the system prompt — edit this to change the bot's persona
```

## Prerequisites

- A **dedicated phone number** for the bot that can receive one SMS or voice
  verification code, and is not already an active Signal account. A cheap
  long-expiry prepaid SIM works well.
- A **DeepSeek API key** (<https://platform.deepseek.com/>).
- For deployment: a small always-on host (e.g. a 1 GB DigitalOcean droplet) with
  Docker + Docker Compose.
- The [GitHub CLI](https://cli.github.com/) (`gh`), used once to fetch the pinned
  `signal-cli` snapshot — see the **signal-cli version pin** section below.
  (Temporary, until a fixed `signal-cli` release is published.)

## Configuration

Copy `.env.example` to `.env` and fill it in:

| Variable | Purpose |
| --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek API key |
| `DEEPSEEK_MODEL` | Model id (default `deepseek-chat`) |
| `BOT_NUMBER` | The bot's registered number, E.164 (e.g. `+61400000000`) |
| `ALLOWED_GROUP_IDS` | Comma-separated group ids the bot responds in |
| `ALLOWED_SENDERS` | Optional sender-number allowlist (empty = any group member) |
| `TRIGGER_ALIAS` | Mention that triggers the bot (default `@bot`) |
| `SYSTEM_PROMPT_PATH` | Path to the system prompt file |
| `HISTORY_WINDOW_MAX` | Max recent messages kept per group as context |
| `DATABASE_PATH` | SQLite file (history + command state) |
| `MAX_TOOL_ITERATIONS` | Max tool round-trips per reply |
| `COMMAND_LOG_WINDOW` | Command-activity events kept per group as context (default 40) |
| `RESET_FAREWELL_MAX_CHARS` | Cap on the `@reset` farewell sentence (default 200) |

## signal-cli version pin

The `signal-cli-rest-api` service is **not** the stock published image. It is built
from [`signal-bridge.Dockerfile`](signal-bridge.Dockerfile), which layers a pinned
`signal-cli` (the official **0.14.5** release tarball, fetched by checksum) over the
upstream image. The upstream rest-api image lags `signal-cli` releases, and 0.14.5
is the first release with the `serverGuid` fix:

- **Dropped incoming messages** (`getServerGuid(...) must not be null`): from
  ~2026-06-10 the Signal server stopped sending `serverGuid` on sealed-sender
  envelopes, and `signal-cli`'s non-null assertion silently dropped **every**
  incoming message (group + most 1:1). Sending was unaffected, which made it look
  like a config/membership problem — it wasn't. This hit every release through
  0.14.4.1 and was fixed in **0.14.5**.
  See [signal-cli#2059](https://github.com/AsamK/signal-cli/issues/2059) /
  [signal-cli-rest-api#860](https://github.com/bbernhard/signal-cli-rest-api/issues/860).

To bump the pin, change `SIGNAL_CLI_VERSION` and `SIGNAL_CLI_SHA256` in
`signal-bridge.Dockerfile` (get the hash with `curl -fsSL <url> | sha256sum`).
There is no vendored artifact, so CI builds the bridge image from a clean checkout.

## Deploy (Docker Compose on a droplet)

### 1. Bring up the Signal bridge

```bash
git clone <this repo> && cd signal-chatbot
cp .env.example .env   # edit it: API key, BOT_NUMBER, etc.
docker compose up -d --build signal-cli-rest-api
```

> **Deploying to a shared host (pull prebuilt images instead of building):** see
> [`deploy/README.md`](deploy/README.md) — `release.sh` publishes images to GHCR
> and `update.sh` pulls them, with memory limits suitable for running alongside
> other stacks.

### 2. Register the bot's number (one time)

Signal requires a captcha to register:

1. Open <https://signalcaptchas.org/registration/generate.html>, solve it, and
   copy the resulting `signalcaptcha://...` token.
2. Register (over the locally-bound port):

   ```bash
   curl -X POST 'http://127.0.0.1:8080/v1/register/+61400000000' \
     -H 'Content-Type: application/json' \
     -d '{"captcha": "signalcaptcha://...", "use_voice": false}'
   ```

   Use `"use_voice": true` for a landline (voice-call code instead of SMS).
3. Verify with the code you received:

   ```bash
   curl -X POST 'http://127.0.0.1:8080/v1/register/+61400000000/verify/123456'
   ```

> **json-rpc load quirk:** the daemon only loads accounts that existed at startup.
> After verifying, restart the bridge so it picks up the new account, then confirm:
> ```bash
> docker compose restart signal-cli-rest-api
> curl -s http://127.0.0.1:8080/v1/accounts   # should list your number
> ```
> A `verify` call can also return a confusing `400` while actually succeeding —
> trust `/v1/accounts`, not the verify status code.

### 3. Add the bot to your group — via the invite link, NOT by number

> ⚠️ **Do not add the bot to the group by its phone number.** A by-number add
> creates a *pending invitation* the bot can't cleanly accept (`Cannot find service
> ID for self`), which leaves it half-joined (can send, can't receive) and corrupts
> the account. Always have the bot **join via the group's invite link** instead.

1. On your phone: group → **Group link** → enable & copy it (`https://signal.group/#...`).
   If "Approve new members" is on, turn it off (or approve the bot afterwards).
2. There is no REST endpoint to join by link, so run `signal-cli` directly. It needs
   the account lock, so do it in `normal` mode (no persistent daemon): set
   `MODE: normal` for `signal-cli-rest-api` in `docker-compose.yml`, then:

   ```bash
   docker compose up -d signal-cli-rest-api
   docker compose exec -u signal-api signal-cli-rest-api \
     signal-cli -a +61400000000 joinGroup --uri "https://signal.group/#..."
   ```
3. (Optional) set the bot's Signal display name:

   ```bash
   curl -X PUT 'http://127.0.0.1:8080/v1/profiles/+61400000000' \
     -H 'Content-Type: application/json' -d '{"name": "Bot"}'
   ```
4. Switch `MODE` back to `json-rpc`, bring the bridge up, and read the group id:

   ```bash
   docker compose up -d signal-cli-rest-api
   docker compose run --rm bot signal-chatbot groups
   ```

   Copy the `group.xxxx=` id into `ALLOWED_GROUP_IDS` in `.env`. (Membership should
   show no `pending_invites` — verify with
   `curl -s http://127.0.0.1:8080/v1/groups/+61400000000`.)

### 4. Start the bot

```bash
docker compose up -d
docker compose logs -f bot
```

Send `@bot hello` in the group — it should reply. Once registered, you can drop
the `ports:` mapping from `signal-cli-rest-api` so nothing is exposed.

## Local development

```bash
uv sync
uv run pytest          # run the test suite
uv run ruff check .    # lint
uv run ruff format .   # format
```

Point `SIGNAL_API_URL` at a locally-running `signal-cli-rest-api` to run the bot
outside Docker: `uv run signal-chatbot`.

## Customising

### Change the bot's persona
Edit `prompts/identity.md`. It is loaded at startup and sent as the system
message. (Restart the bot to pick up changes.)

### Add a tool
Tools give the model abilities beyond text. Adding one is a single file plus one
line:

1. Create `src/signal_chatbot/tools/builtin/my_tool.py`:

   ```python
   from pydantic import BaseModel, Field
   from signal_chatbot.tools.base import Tool

   class Weather(Tool):
       name = "get_weather"
       description = "Get the current weather for a city."

       class Args(BaseModel):
           city: str = Field(description="City name, e.g. 'Sydney'.")

       async def run(self, args: "Weather.Args") -> str:
           ...  # call an API, return a string
   ```

2. Add it to `default_tools()` in `src/signal_chatbot/tools/builtin/__init__.py`.

The `Args` model both validates the model's arguments and generates the JSON
schema advertised to DeepSeek, so the two can't drift. Errors raised inside
`run` are caught and reported back to the model rather than crashing the bot.

### Built-in tools
- **`current_time`** — current date/time in any IANA timezone.
- **`set_name`** — the bot renames its own Signal display name.
- **`wikipedia_search` / `wikipedia_article`** — look up Wikipedia to
  fact-check and answer questions about current events. Search finds the right
  article; the article tool returns the intro by default, a table of contents
  with `full=true`, or a named/numbered section on request. Results are cached
  in SQLite with a TTL (`WIKIPEDIA_CACHE_TTL_SECONDS`, default 6h), so repeat
  lookups don't re-hit the Wikimedia API. Set `WIKIPEDIA_USER_AGENT` to a
  descriptive value with contact info — Wikimedia may block generic agents.

## Cost & caching

Running cost is the droplet (~$6/mo) plus DeepSeek usage. The prompt is ordered
so its head — system prompt, tool definitions, older history — is byte-stable
between calls, which lets DeepSeek's server-side prefix cache discount repeated
tokens. Cache hit/miss token counts are logged per reply (`llm.cache`).

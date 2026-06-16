"""Application entrypoint and a small setup CLI.

signal-chatbot          run the bot (default)
signal-chatbot groups   list the bot's groups and their ids (for ALLOWED_GROUP_IDS)
"""

from __future__ import annotations

import argparse
import asyncio

import httpx

from signal_chatbot.bot import Bot
from signal_chatbot.botname import BotName
from signal_chatbot.commands.farewell import LlmFarewellWriter
from signal_chatbot.commands.router import CommandRouter
from signal_chatbot.config import Settings
from signal_chatbot.history import HistoryStore
from signal_chatbot.llm.conversation import Conversation
from signal_chatbot.llm.deepseek import DeepSeekClient
from signal_chatbot.lobotomy import Lobotomiser
from signal_chatbot.logging import configure_logging, get_logger
from signal_chatbot.state import Database
from signal_chatbot.state.flags import FlagRegistry
from signal_chatbot.tools import ToolRegistry
from signal_chatbot.tools.base import Tool
from signal_chatbot.tools.builtin import default_tools
from signal_chatbot.tools.builtin.websearch import TavilyClient, WebSearch
from signal_chatbot.tools.builtin.wikipedia import (
    WikipediaCache,
    WikipediaClient,
    WikipediaService,
)
from signal_chatbot.transport import SignalClient

log = get_logger(__name__)

_ERROR_REPLY = "Sorry, I hit an error trying to answer that. Try again in a moment."


async def _run() -> None:
    settings = Settings()  # type: ignore[call-arg]

    signal = SignalClient(settings.signal_api_url, settings.bot_number)
    # Single source of truth for the bot's display name: every rename path (command,
    # tool, reset, wipe) goes through this, and the bot reads it for the self-destruct
    # warning. Initialised to the default until the first rename of the session.
    bot_name = BotName(signal, initial=settings.default_display_name)
    history = HistoryStore(settings.database_path, window_max=settings.history_window_max)
    await history.connect()
    db = Database(settings.database_path, command_log_window=settings.command_log_window)
    await db.connect()
    llm = DeepSeekClient(
        api_key=settings.deepseek_api_key,
        model=settings.deepseek_model,
        base_url=settings.deepseek_base_url,
        thinking=settings.deepseek_thinking,
    )
    wikipedia_http = httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": settings.wikipedia_user_agent},
    )
    wikipedia_cache = WikipediaCache(settings.database_path)
    await wikipedia_cache.connect()
    wikipedia = WikipediaService(
        WikipediaClient(wikipedia_http, language=settings.wikipedia_language),
        wikipedia_cache,
        language=settings.wikipedia_language,
        ttl_seconds=settings.wikipedia_cache_ttl_seconds,
        search_limit=settings.wikipedia_search_limit,
    )
    websearch_http: httpx.AsyncClient | None = None
    web_search: Tool | None = None
    if settings.tavily_api_key:
        websearch_http = httpx.AsyncClient(timeout=30.0)
        web_search = WebSearch(
            TavilyClient(
                websearch_http,
                settings.tavily_api_key,
                result_limit=settings.websearch_result_limit,
            ),
            snippet_max_chars=settings.websearch_snippet_max_chars,
        )
    log.info("websearch.configured", enabled=web_search is not None)
    # One flag facade over the generic flag store, shared by the bot (arming, listen),
    # the tools (listen, takeover), the router (@flags/@flag) and the wipe paths.
    flags = FlagRegistry(db.flags)
    registry = ToolRegistry(
        default_tools(
            bot_name,
            db.directives,
            db.profiles,
            flags,
            signal,
            wikipedia,
            wikipedia_max_section_chars=settings.wikipedia_max_section_chars,
            web_search=web_search,
        )
    )
    conversation = Conversation(
        llm,
        registry,
        max_iterations=settings.max_tool_iterations,
    )
    lobotomiser = Lobotomiser(
        directives=db.directives,
        flags=flags,
        disclaimers=db.disclaimers,
        profiles=db.profiles,
        history=history,
        name_setter=bot_name,
        default_name=settings.default_display_name,
    )
    commands = CommandRouter(
        directives=db.directives,
        commands=db.commands,
        disclaimers=db.disclaimers,
        profiles=db.profiles,
        flags=flags,
        final_words=db.final_words,
        history=history,
        farewell=LlmFarewellWriter(llm, max_chars=settings.reset_farewell_max_chars),
        name_setter=bot_name,
        lobotomiser=lobotomiser,
        tools=registry,
        timezone=settings.display_tz,
    )
    bot = Bot(
        signal=signal,
        history=history,
        conversation=conversation,
        commands=commands,
        directives=db.directives,
        command_log=db.commands,
        flags=flags,
        final_words=db.final_words,
        disclaimers=db.disclaimers,
        profiles=db.profiles,
        lobotomiser=lobotomiser,
        name=bot_name,
        system_prompt=settings.load_system_prompt(),
        allowed_group_ids=settings.allowed_group_ids,
        allowed_senders=settings.allowed_senders,
        trigger_alias=settings.trigger_alias,
        error_reply=_ERROR_REPLY,
        timezone=settings.display_tz,
        unprompted_reply_chance=settings.unprompted_reply_chance,
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
        await db.aclose()
        await wikipedia_cache.aclose()
        await wikipedia_http.aclose()
        if websearch_http is not None:
            await websearch_http.aclose()


async def _list_groups() -> None:
    settings = Settings()  # type: ignore[call-arg]
    signal = SignalClient(settings.signal_api_url, settings.bot_number)
    try:
        groups = await signal.list_groups()
    finally:
        await signal.aclose()
    if not groups:
        print("No groups found. Add the bot to a group, then re-run.")
        return
    for group in groups:
        print(f"{group.get('id')}\t{group.get('name', '(no name)')}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="signal-chatbot")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "groups"],
        help="'run' starts the bot; 'groups' lists group ids for setup.",
    )
    args = parser.parse_args()

    configure_logging()
    try:
        if args.command == "groups":
            asyncio.run(_list_groups())
        else:
            asyncio.run(_run())
    except KeyboardInterrupt:
        log.info("bot.stopped")


if __name__ == "__main__":
    main()

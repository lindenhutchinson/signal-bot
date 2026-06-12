"""Application entrypoint and a small setup CLI.

signal-chatbot          run the bot (default)
signal-chatbot groups   list the bot's groups and their ids (for ALLOWED_GROUP_IDS)
"""

from __future__ import annotations

import argparse
import asyncio

from signal_chatbot.bot import Bot
from signal_chatbot.commands.farewell import LlmFarewellWriter
from signal_chatbot.commands.router import CommandRouter
from signal_chatbot.config import Settings
from signal_chatbot.history import HistoryStore
from signal_chatbot.llm.conversation import Conversation
from signal_chatbot.llm.deepseek import DeepSeekClient
from signal_chatbot.logging import configure_logging, get_logger
from signal_chatbot.state import StateStore
from signal_chatbot.tools import ToolRegistry
from signal_chatbot.tools.builtin import default_tools
from signal_chatbot.transport import SignalClient

log = get_logger(__name__)

_ERROR_REPLY = "Sorry, I hit an error trying to answer that. Try again in a moment."


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
        ToolRegistry(default_tools(signal)),
        max_iterations=settings.max_tool_iterations,
    )
    commands = CommandRouter(
        state=state,
        history=history,
        farewell=LlmFarewellWriter(llm, max_chars=settings.reset_farewell_max_chars),
        name_setter=signal,
        default_name=settings.default_display_name,
    )
    bot = Bot(
        signal=signal,
        history=history,
        conversation=conversation,
        commands=commands,
        state=state,
        disclaimers=state,
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
